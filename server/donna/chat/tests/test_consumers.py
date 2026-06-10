"""
WebSocket integration — :class:`donna.chat.consumers.ChatConsumer`.

Drives the consumer through the in-process ASGI stack via
``channels.testing.WebsocketCommunicator``. No live uvicorn / network.

Coverage:
- WS opens with valid JWT subprotocol; rejects anonymous (4401).
- Phase 1.1: ``delete_message`` rejects non-author non-admin, succeeds
  for channel admin (REST + WS agree).
- Phase 1.2: ``add_member`` dual broadcast — invitee's presence group
  receives ``channel.added.to_you``.
- Phase 1.4: ``open_dm`` accepts ``workspace_id`` and creates the DM
  in the requested workspace.
"""
from __future__ import annotations

import asyncio

from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase

from donna.asgi import application
from donna.chat.models import Channel, ChannelMembership, Message
from donna.chat.services import ChannelService
from donna.chat.tests.factories import make_channel, make_message
from donna.core.tests.helpers import jwt_for
from donna.users.tests.factories import make_user
from donna.workspaces.models import WorkspaceMembership
from donna.workspaces.tests.factories import make_workspace


async def _open_ws(user, *, drain: int = 3, timeout: float = 1.0):
    """
    Open a WS connection and drain the burst of opening events
    (``connected`` + ``presence``).

    Returns the communicator; caller must call ``await comm.disconnect()``.
    """
    comm = WebsocketCommunicator(
        application,
        "/ws/",
        subprotocols=["bearer", jwt_for(user)],
    )
    connected, _ = await comm.connect()
    assert connected, "WS handshake failed"
    # Drain up to `drain` opening frames within `timeout` total
    end = asyncio.get_event_loop().time() + timeout
    for _ in range(drain):
        remaining = end - asyncio.get_event_loop().time()
        if remaining <= 0:
            break
        try:
            await asyncio.wait_for(comm.receive_json_from(), timeout=remaining)
        except asyncio.TimeoutError:
            break
    return comm


async def _next_matching(comm, predicate, *, timeout: float = 3.0):
    """Drain frames from ``comm`` until ``predicate(frame)`` is True."""
    end = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = end - asyncio.get_event_loop().time()
        if remaining <= 0:
            return None
        try:
            r = await asyncio.wait_for(comm.receive_json_from(), timeout=remaining)
        except asyncio.TimeoutError:
            return None
        if predicate(r):
            return r


class WSConnectTest(TransactionTestCase):
    """Handshake-only tests — no DB-dependent action."""

    def test_anonymous_handshake_rejected(self):
        async def go():
            # No bearer subprotocol → consumer closes with 4401.
            comm = WebsocketCommunicator(application, "/ws/")
            connected, code = await comm.connect()
            self.assertFalse(connected)
            self.assertEqual(code, 4401)

        asyncio.run(go())

    def test_authenticated_handshake_emits_connected_event(self):
        user = make_user(email="ws-connect@chat.test")

        async def go():
            comm = WebsocketCommunicator(
                application, "/ws/",
                subprotocols=["bearer", jwt_for(user)],
            )
            connected, _ = await comm.connect()
            self.assertTrue(connected)
            frame = await asyncio.wait_for(comm.receive_json_from(), timeout=1.0)
            self.assertEqual(frame["event"], "connected")
            self.assertEqual(frame["user_id"], str(user.id))
            await comm.disconnect()

        asyncio.run(go())


class WSAdminDeleteMessageTest(TransactionTestCase):
    """Phase 1.1 — author / channel-admin can delete via WS; others 403."""

    def setUp(self):
        self.alice = make_user(email="alice@ws.test")
        self.bob = make_user(email="bob@ws.test")
        self.charlie = make_user(email="charlie@ws.test")
        self.workspace = make_workspace(
            name="WS-AdminDel", owner=self.alice,
            members=[
                (self.bob, WorkspaceMembership.Role.MEMBER),
                (self.charlie, WorkspaceMembership.Role.MEMBER),
            ],
        )
        self.channel = make_channel(
            workspace=self.workspace, name="general", slug="general",
            admins=[self.alice], members=[self.bob, self.charlie],
        )

    def test_non_author_non_admin_delete_is_forbidden(self):
        msg = make_message(channel=self.channel, author=self.bob)

        async def go():
            comm = await _open_ws(self.charlie)
            await comm.send_json_to(
                {"action": "delete_message", "message_id": str(msg.id)}
            )
            r = await _next_matching(comm, lambda f: f.get("event") == "error")
            self.assertIsNotNone(r)
            self.assertIn("admin", r["detail"].lower())
            await comm.disconnect()

        asyncio.run(go())
        # Message still exists.
        self.assertTrue(Message.objects.filter(id=msg.id).exists())

    def test_channel_admin_delete_broadcasts_message_deleted(self):
        msg = make_message(channel=self.channel, author=self.bob)

        async def go():
            comm = await _open_ws(self.alice)
            await comm.send_json_to(
                {"action": "subscribe_channel", "channel_id": str(self.channel.id)}
            )
            await _next_matching(comm, lambda f: f.get("event") == "subscribed")
            await comm.send_json_to(
                {"action": "delete_message", "message_id": str(msg.id)}
            )
            r = await _next_matching(
                comm, lambda f: f.get("event") == "message.deleted"
            )
            self.assertIsNotNone(r)
            self.assertEqual(r["message_id"], str(msg.id))
            await comm.disconnect()

        asyncio.run(go())
        self.assertFalse(Message.objects.filter(id=msg.id).exists())


class WSInviteBroadcastTest(TransactionTestCase):
    """Phase 1.2 — invitee receives ``channel.added.to_you`` on their WS."""

    def setUp(self):
        self.alice = make_user(email="alice@ws-inv.test")
        self.bob = make_user(email="bob@ws-inv.test")
        self.workspace = make_workspace(
            name="WS-Inv", owner=self.alice,
            members=[(self.bob, WorkspaceMembership.Role.MEMBER)],
        )
        self.secret = make_channel(
            workspace=self.workspace, name="secret", slug="secret",
            visibility=Channel.Visibility.PRIVATE,
            admins=[self.alice],
        )

    def test_invitee_presence_group_receives_channel_added_to_you(self):
        async def go():
            comm = await _open_ws(self.bob)
            # Alice invites Bob — service call (sync) inside async context.
            await sync_to_async(ChannelService.add_member)(
                channel=self.secret, user=self.bob, added_by=self.alice,
            )
            r = await _next_matching(
                comm,
                lambda f: f.get("event") == "channel.added.to_you",
            )
            self.assertIsNotNone(r)
            self.assertEqual(r["channel"]["id"], str(self.secret.id))
            self.assertEqual(r["added_by"], str(self.alice.id))
            await comm.disconnect()

        asyncio.run(go())
        # And the row landed.
        self.assertTrue(
            ChannelMembership.objects.filter(
                channel=self.secret, user=self.bob
            ).exists()
        )


class WSOpenDMWorkspaceIdTest(TransactionTestCase):
    """Phase 1.4 — ``open_dm`` with explicit ``workspace_id`` scopes the DM."""

    def setUp(self):
        self.alice = make_user(email="alice@ws-dm.test")
        self.bob = make_user(email="bob@ws-dm.test")
        self.ws_a = make_workspace(
            name="A", owner=self.alice,
            members=[(self.bob, WorkspaceMembership.Role.MEMBER)],
        )
        self.ws_b = make_workspace(
            name="B", owner=self.alice,
            members=[(self.bob, WorkspaceMembership.Role.MEMBER)],
        )

    def test_open_dm_scoped_to_explicit_workspace_id(self):
        async def go():
            comm = await _open_ws(self.alice)
            await comm.send_json_to({
                "action": "open_dm",
                "peer_user_id": str(self.bob.id),
                "workspace_id": str(self.ws_b.id),
            })
            r = await _next_matching(comm, lambda f: f.get("event") == "dm.opened")
            self.assertIsNotNone(r)
            channel = await sync_to_async(Channel.objects.get)(id=r["channel_id"])
            self.assertEqual(str(channel.workspace_id), str(self.ws_b.id))
            await comm.disconnect()

        asyncio.run(go())


class WSSubscribeAuthorizationTest(TransactionTestCase):
    """``subscribe_channel`` / ``unsubscribe_channel`` actions."""

    def setUp(self):
        self.alice = make_user(email="alice@sub.test")
        self.bob = make_user(email="bob@sub.test")
        self.workspace = make_workspace(
            name="SubWS", owner=self.alice,
            members=[(self.bob, WorkspaceMembership.Role.MEMBER)],
        )
        self.channel = make_channel(
            workspace=self.workspace, name="ch", slug="ch", admins=[self.alice],
        )

    def test_subscribe_as_member_emits_subscribed(self):
        async def go():
            comm = await _open_ws(self.alice)
            await comm.send_json_to({
                "action": "subscribe_channel",
                "channel_id": str(self.channel.id),
            })
            r = await _next_matching(
                comm, lambda f: f.get("event") == "subscribed"
            )
            self.assertIsNotNone(r)
            self.assertEqual(r["channel_id"], str(self.channel.id))
            await comm.disconnect()

        asyncio.run(go())

    def test_subscribe_as_non_member_returns_forbidden(self):
        async def go():
            comm = await _open_ws(self.bob)  # not a member of `ch`
            await comm.send_json_to({
                "action": "subscribe_channel",
                "channel_id": str(self.channel.id),
            })
            r = await _next_matching(comm, lambda f: f.get("event") == "error")
            self.assertIsNotNone(r)
            self.assertEqual(r["code"], "forbidden")
            await comm.disconnect()

        asyncio.run(go())

    def test_subscribe_without_channel_id_bad_request(self):
        async def go():
            comm = await _open_ws(self.alice)
            await comm.send_json_to({"action": "subscribe_channel"})
            r = await _next_matching(comm, lambda f: f.get("event") == "error")
            self.assertIsNotNone(r)
            self.assertEqual(r["code"], "bad_request")
            await comm.disconnect()

        asyncio.run(go())

    def test_unsubscribe_acknowledges(self):
        async def go():
            comm = await _open_ws(self.alice)
            await comm.send_json_to({
                "action": "subscribe_channel",
                "channel_id": str(self.channel.id),
            })
            await _next_matching(comm, lambda f: f.get("event") == "subscribed")
            await comm.send_json_to({
                "action": "unsubscribe_channel",
                "channel_id": str(self.channel.id),
            })
            r = await _next_matching(
                comm, lambda f: f.get("event") == "unsubscribed"
            )
            self.assertIsNotNone(r)
            await comm.disconnect()

        asyncio.run(go())


class WSSendMessageTest(TransactionTestCase):
    """``send_message`` action — happy path + authz."""

    def setUp(self):
        self.alice = make_user(email="alice@send.test")
        self.workspace = make_workspace(name="SendWS", owner=self.alice)
        self.channel = make_channel(
            workspace=self.workspace, name="ch", slug="ch", admins=[self.alice],
        )

    def test_member_send_broadcasts_message_created(self):
        async def go():
            comm = await _open_ws(self.alice)
            await comm.send_json_to({
                "action": "subscribe_channel",
                "channel_id": str(self.channel.id),
            })
            await _next_matching(comm, lambda f: f.get("event") == "subscribed")
            await comm.send_json_to({
                "action": "send_message",
                "channel_id": str(self.channel.id),
                "body": "via WS",
                "client_msg_id": "ws-1",
            })
            r = await _next_matching(
                comm, lambda f: f.get("event") == "message.created"
            )
            self.assertIsNotNone(r)
            self.assertEqual(r["body"], "via WS")
            self.assertEqual(r["client_msg_id"], "ws-1")
            await comm.disconnect()

        asyncio.run(go())
        self.assertTrue(
            Message.objects.filter(channel=self.channel, body="via WS").exists()
        )

    def test_send_without_body_bad_request(self):
        async def go():
            comm = await _open_ws(self.alice)
            await comm.send_json_to({
                "action": "send_message",
                "channel_id": str(self.channel.id),
            })
            r = await _next_matching(comm, lambda f: f.get("event") == "error")
            self.assertEqual(r["code"], "bad_request")
            await comm.disconnect()

        asyncio.run(go())

    def test_non_member_send_forbidden(self):
        outsider = make_user(email="outsider@send.test")
        WorkspaceMembership.objects.create(
            workspace=self.workspace, user=outsider,
            role=WorkspaceMembership.Role.MEMBER,
        )

        async def go():
            comm = await _open_ws(outsider)
            await comm.send_json_to({
                "action": "send_message",
                "channel_id": str(self.channel.id),
                "body": "intrusion",
            })
            r = await _next_matching(comm, lambda f: f.get("event") == "error")
            self.assertEqual(r["code"], "forbidden")
            await comm.disconnect()

        asyncio.run(go())


class WSEditMessageTest(TransactionTestCase):
    """``edit_message`` — author only."""

    def setUp(self):
        self.alice = make_user(email="alice@edit.test")
        self.bob = make_user(email="bob@edit.test")
        self.workspace = make_workspace(
            name="EditWS", owner=self.alice,
            members=[(self.bob, WorkspaceMembership.Role.MEMBER)],
        )
        self.channel = make_channel(
            workspace=self.workspace, name="ch", slug="ch",
            admins=[self.alice], members=[self.bob],
        )

    def test_author_can_edit_and_broadcast_emitted(self):
        msg = make_message(channel=self.channel, author=self.alice, body="orig")

        async def go():
            comm = await _open_ws(self.alice)
            await comm.send_json_to({
                "action": "subscribe_channel",
                "channel_id": str(self.channel.id),
            })
            await _next_matching(comm, lambda f: f.get("event") == "subscribed")
            await comm.send_json_to({
                "action": "edit_message",
                "message_id": str(msg.id),
                "body": "edited",
            })
            r = await _next_matching(
                comm, lambda f: f.get("event") == "message.updated"
            )
            self.assertIsNotNone(r)
            self.assertEqual(r["body"], "edited")
            await comm.disconnect()

        asyncio.run(go())

    def test_non_author_edit_forbidden(self):
        msg = make_message(channel=self.channel, author=self.alice, body="orig")

        async def go():
            comm = await _open_ws(self.bob)  # not the author
            await comm.send_json_to({
                "action": "edit_message",
                "message_id": str(msg.id),
                "body": "hijacked",
            })
            r = await _next_matching(comm, lambda f: f.get("event") == "error")
            self.assertEqual(r["code"], "forbidden")
            await comm.disconnect()

        asyncio.run(go())


class WSTypingTest(TransactionTestCase):
    """``typing`` action — ephemeral broadcast on the typing group."""

    def setUp(self):
        self.alice = make_user(email="alice@type.test")
        self.workspace = make_workspace(name="TypeWS", owner=self.alice)
        self.channel = make_channel(
            workspace=self.workspace, name="ch", slug="ch", admins=[self.alice],
        )

    def test_typing_emits_typing_event(self):
        """
        Alice subscribes (which joins both regular + typing groups),
        fires ``typing``, and receives the ``typing`` event back —
        proves the auth path + the group_send broadcast.
        """
        async def go():
            comm = await _open_ws(self.alice)
            await comm.send_json_to({
                "action": "subscribe_channel",
                "channel_id": str(self.channel.id),
            })
            await _next_matching(comm, lambda f: f.get("event") == "subscribed")
            await comm.send_json_to({
                "action": "typing",
                "channel_id": str(self.channel.id),
            })
            r = await _next_matching(comm, lambda f: f.get("event") == "typing")
            self.assertIsNotNone(r)
            self.assertEqual(r["user_id"], str(self.alice.id))
            self.assertEqual(r["channel_id"], str(self.channel.id))
            await comm.disconnect()

        asyncio.run(go())

    def test_typing_without_channel_id_bad_request(self):
        async def go():
            comm = await _open_ws(self.alice)
            await comm.send_json_to({"action": "typing"})
            r = await _next_matching(comm, lambda f: f.get("event") == "error")
            self.assertEqual(r["code"], "bad_request")
            await comm.disconnect()

        asyncio.run(go())


class WSMarkReadTest(TransactionTestCase):
    """``mark_read`` action — advances read pointer + broadcasts ``read.advanced``."""

    def setUp(self):
        self.alice = make_user(email="alice@mr.test")
        self.workspace = make_workspace(name="MRWS", owner=self.alice)
        self.channel = make_channel(
            workspace=self.workspace, name="ch", slug="ch", admins=[self.alice],
        )

    def test_mark_read_emits_read_advanced(self):
        msg = make_message(channel=self.channel, author=self.alice)

        async def go():
            comm = await _open_ws(self.alice)
            await comm.send_json_to({
                "action": "subscribe_channel",
                "channel_id": str(self.channel.id),
            })
            await _next_matching(comm, lambda f: f.get("event") == "subscribed")
            await comm.send_json_to({
                "action": "mark_read",
                "channel_id": str(self.channel.id),
                "message_id": str(msg.id),
            })
            r = await _next_matching(
                comm, lambda f: f.get("event") == "read.advanced"
            )
            self.assertIsNotNone(r)
            self.assertEqual(r["message_id"], str(msg.id))
            self.assertEqual(r["user_id"], str(self.alice.id))
            await comm.disconnect()

        asyncio.run(go())


class WSHeartbeatTest(TransactionTestCase):
    """``heartbeat`` action — refreshes presence TTL (no broadcast)."""

    def setUp(self):
        self.alice = make_user(email="alice@hb.test")

    def test_heartbeat_does_not_raise(self):
        async def go():
            comm = await _open_ws(self.alice)
            await comm.send_json_to({"action": "heartbeat"})
            # Heartbeat is silent; we just confirm no error frame within
            # a short window.
            r = await _next_matching(
                comm, lambda f: f.get("event") == "error", timeout=0.5,
            )
            self.assertIsNone(r)
            await comm.disconnect()

        asyncio.run(go())


class WSUnknownActionTest(TransactionTestCase):
    def test_unknown_action_returns_error(self):
        user = make_user(email="unknown@ws.test")

        async def go():
            comm = await _open_ws(user)
            await comm.send_json_to({"action": "totally-fake"})
            r = await _next_matching(comm, lambda f: f.get("event") == "error")
            self.assertEqual(r["code"], "unknown_action")
            await comm.disconnect()

        asyncio.run(go())


class AgentStreamConsumerTest(TransactionTestCase):
    """``/ws/agent/{run_id}/`` connect + handshake."""

    def test_anonymous_rejected(self):
        async def go():
            comm = WebsocketCommunicator(
                application, "/ws/agent/abc123/",
            )
            connected, code = await comm.connect()
            self.assertFalse(connected)
            self.assertEqual(code, 4401)

        asyncio.run(go())

    def test_authenticated_emits_connected(self):
        user = make_user(email="agent@ws.test")

        async def go():
            comm = WebsocketCommunicator(
                application, "/ws/agent/run-xyz/",
                subprotocols=["bearer", jwt_for(user)],
            )
            connected, _ = await comm.connect()
            self.assertTrue(connected)
            r = await asyncio.wait_for(comm.receive_json_from(), timeout=1.0)
            self.assertEqual(r["event"], "connected")
            self.assertEqual(r["run_id"], "run-xyz")
            await comm.disconnect()

        asyncio.run(go())
