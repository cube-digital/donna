"""
Channels consumers for the realtime chat / agent layer.

- ``ChatConsumer`` — one per user. Handles all chat / DM / presence /
  workspace events. Multiplexes subscriptions to many groups via
  ``subscribe_channel`` / ``unsubscribe_channel`` actions.
- ``AgentStreamConsumer`` — one per agent run. Subscribes to the
  ``agent-run-{run_id}-tokens`` group and forwards token chunks pushed
  by the agent worker.

See plans/10-realtime-layer.md for the wire protocol.
"""
from __future__ import annotations

import logging
from typing import Any

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings

from donna.core.cache import redis_manager

from .services import (
    ChannelService,
    agent_run_group,
    channel_group,
    channel_typing_group,
    presence_group,
    workspace_events_group,
)


logger = logging.getLogger(__name__)


def _presence_key(user_id) -> str:
    return f"presence:user:{user_id}"


# ─── Sync ORM helpers (wrapped via database_sync_to_async) ───────────────────
@database_sync_to_async
def _user_workspace_ids(user_id) -> list:
    from donna.workspaces.models import WorkspaceMembership
    return list(
        WorkspaceMembership.objects.filter(user_id=user_id)
        .values_list("workspace_id", flat=True)
    )


@database_sync_to_async
def _can_access_channel(user_id, channel_id) -> bool:
    from .models import ChannelMembership
    return ChannelMembership.objects.filter(
        user_id=user_id, channel_id=channel_id
    ).exists()


@database_sync_to_async
def _fetch_channel(channel_id):
    from .models import Channel
    try:
        return Channel.objects.get(id=channel_id)
    except Channel.DoesNotExist:
        return None


@database_sync_to_async
def _fetch_message(message_id):
    from .models import Message
    try:
        return Message.objects.select_related("channel").get(id=message_id)
    except Message.DoesNotExist:
        return None


@database_sync_to_async
def _fetch_user(user_id):
    from donna.users.models import User
    try:
        return User.objects.get(id=user_id)
    except User.DoesNotExist:
        return None


# ─── ChatConsumer ────────────────────────────────────────────────────────────
class ChatConsumer(AsyncJsonWebsocketConsumer):
    """
    One WS per signed-in user. Subscribes to:

      - ``presence-user-{uid}``           (always)
      - ``workspace-{wid}-events``         for every workspace membership

    Channel/DM subscriptions are opt-in via ``subscribe_channel`` from
    the frontend (typically when the user opens a conversation in UI).
    """

    async def connect(self):
        user = self.scope.get("user")
        if user is None or not getattr(user, "is_authenticated", False):
            await self.close(code=4401)
            return

        self.user = user
        self._subscribed_groups: set[str] = set()
        self._authz_cache: dict[str, bool] = {}     # channel_id -> bool

        # Accept the matching subprotocol if the client sent one.
        subprotocol = self.scope.get("jwt_subprotocol")
        await self.accept(subprotocol=subprotocol)

        # Always-on subscriptions.
        await self._group_add(presence_group(user.id))
        for wid in await _user_workspace_ids(user.id):
            await self._group_add(workspace_events_group(wid))

        # Presence marker — TTL-refreshed by heartbeat.
        ttl = getattr(settings, "DONNA_PRESENCE_TTL_SECONDS", 30)
        redis_manager.set_ex(_presence_key(user.id), "1", ttl)

        await self.channel_layer.group_send(
            presence_group(user.id),
            {"type": "chat.presence", "payload": {"user_id": str(user.id), "online": True}},
        )

        await self.send_json({"event": "connected", "user_id": str(user.id)})

    async def disconnect(self, code):
        user = getattr(self, "user", None)
        if user is None:
            return

        # Best-effort: leave all joined groups.
        for grp in list(getattr(self, "_subscribed_groups", [])):
            try:
                await self.channel_layer.group_discard(grp, self.channel_name)
            except Exception as exc:  # noqa: BLE001
                logger.warning("group_discard_failed", extra={"group": grp, "error": str(exc)})

        # Drop presence key + announce.
        try:
            redis_manager.delete(_presence_key(user.id))
        except Exception:  # noqa: BLE001
            pass
        try:
            await self.channel_layer.group_send(
                presence_group(user.id),
                {"type": "chat.presence", "payload": {"user_id": str(user.id), "online": False}},
            )
        except Exception:  # noqa: BLE001
            pass

    # ── Inbound (client → server) ───────────────────────────────────────────
    async def receive_json(self, content: dict[str, Any], **kwargs):
        action = content.get("action")
        try:
            handler = getattr(self, f"_action_{action}", None)
            if handler is None:
                await self._send_error("unknown_action", f"action {action!r} unsupported")
                return
            await handler(content)
        except PermissionError as exc:
            await self._send_error("forbidden", str(exc))
        except ValueError as exc:
            await self._send_error("bad_request", str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("ws_action_unhandled", extra={"action": action, "error": str(exc)})
            await self._send_error("server_error", "internal error")

    # ── Action handlers ─────────────────────────────────────────────────────
    async def _action_subscribe_channel(self, content):
        cid = content.get("channel_id")
        if not cid:
            raise ValueError("channel_id required")
        if not await self._authorize_channel(cid):
            raise PermissionError(f"no membership in channel {cid}")
        await self._group_add(channel_group(cid))
        await self._group_add(channel_typing_group(cid))
        await self.send_json({"event": "subscribed", "channel_id": str(cid)})

    async def _action_unsubscribe_channel(self, content):
        cid = content.get("channel_id")
        if not cid:
            raise ValueError("channel_id required")
        await self._group_discard(channel_group(cid))
        await self._group_discard(channel_typing_group(cid))
        await self.send_json({"event": "unsubscribed", "channel_id": str(cid)})

    async def _action_send_message(self, content):
        cid = content.get("channel_id")
        body = content.get("body")
        client_msg_id = content.get("client_msg_id")
        if not cid or not body:
            raise ValueError("channel_id and body required")
        if not await self._authorize_channel(cid):
            raise PermissionError(f"no membership in channel {cid}")
        channel = await _fetch_channel(cid)
        if channel is None:
            raise ValueError("channel not found")
        await database_sync_to_async(ChannelService.send_message)(
            channel=channel, sender_user=self.user, body=body, client_msg_id=client_msg_id
        )

    async def _action_edit_message(self, content):
        mid = content.get("message_id")
        body = content.get("body")
        if not mid or body is None:
            raise ValueError("message_id and body required")
        message = await _fetch_message(mid)
        if message is None:
            raise ValueError("message not found")
        if message.author_user_id != self.user.id:
            raise PermissionError("only the author can edit a message")
        await database_sync_to_async(ChannelService.edit_message)(
            message=message, body=body
        )

    async def _action_delete_message(self, content):
        mid = content.get("message_id")
        if not mid:
            raise ValueError("message_id required")
        message = await _fetch_message(mid)
        if message is None:
            raise ValueError("message not found")
        # Authorization is shared with REST via ChannelService — author
        # OR a channel admin may delete. Wrapped because the admin lookup
        # is a sync ORM query.
        await database_sync_to_async(ChannelService.authorize_delete_message)(
            user=self.user, message=message
        )
        await database_sync_to_async(ChannelService.delete_message)(message=message)

    async def _action_typing(self, content):
        cid = content.get("channel_id")
        if not cid:
            raise ValueError("channel_id required")
        if not await self._authorize_channel(cid):
            raise PermissionError(f"no membership in channel {cid}")
        ChannelService.emit_typing(channel_id=cid, user_id=self.user.id)

    async def _action_mark_read(self, content):
        cid = content.get("channel_id")
        mid = content.get("message_id")
        if not cid or not mid:
            raise ValueError("channel_id and message_id required")
        if not await self._authorize_channel(cid):
            raise PermissionError(f"no membership in channel {cid}")
        channel = await _fetch_channel(cid)
        message = await _fetch_message(mid)
        if channel is None or message is None:
            raise ValueError("channel or message not found")
        await database_sync_to_async(ChannelService.advance_read_pointer)(
            user=self.user, channel=channel, message=message
        )

    async def _action_open_dm(self, content):
        peer_id = content.get("peer_user_id")
        # workspace_id disambiguates when caller + peer share multiple
        # workspaces. Optional in this rollout — when omitted,
        # ChannelService.get_or_create_dm logs a warning and falls back
        # to "first overlapping workspace". Clients should send it.
        workspace_id = content.get("workspace_id")
        if not peer_id:
            raise ValueError("peer_user_id required")
        peer = await _fetch_user(peer_id)
        if peer is None:
            raise ValueError("peer not found")
        channel = await database_sync_to_async(ChannelService.get_or_create_dm)(
            self.user, peer, workspace_id=workspace_id
        )
        # Auto-subscribe caller's WS to the DM.
        await self._group_add(channel_group(channel.id))
        await self._group_add(channel_typing_group(channel.id))
        await self.send_json(
            {"event": "dm.opened", "channel_id": str(channel.id), "peer_user_id": str(peer.id)}
        )

    async def _action_heartbeat(self, content):
        ttl = getattr(settings, "DONNA_PRESENCE_TTL_SECONDS", 30)
        redis_manager.set_ex(_presence_key(self.user.id), "1", ttl)

    # ── Outbound (group_send → client) ──────────────────────────────────────
    async def chat_message_created(self, event):
        await self.send_json({"event": "message.created", **event["payload"]})

    async def chat_message_updated(self, event):
        await self.send_json({"event": "message.updated", **event["payload"]})

    async def chat_message_deleted(self, event):
        await self.send_json({"event": "message.deleted", **event["payload"]})

    async def chat_typing(self, event):
        await self.send_json({"event": "typing", **event["payload"]})

    async def chat_presence(self, event):
        await self.send_json({"event": "presence", **event["payload"]})

    async def chat_channel_created(self, event):
        await self.send_json({"event": "channel.created", **event["payload"]})

    async def chat_channel_updated(self, event):
        await self.send_json({"event": "channel.updated", **event["payload"]})

    async def chat_channel_deleted(self, event):
        await self.send_json({"event": "channel.deleted", **event["payload"]})

    async def chat_channel_member_added(self, event):
        await self.send_json({"event": "channel.member.added", **event["payload"]})

    async def chat_channel_member_removed(self, event):
        await self.send_json({"event": "channel.member.removed", **event["payload"]})

    async def chat_channel_added_to_you(self, event):
        # Fired on presence-user-{uid} when the user is invited to a
        # channel. Carries the full channel payload so the client can
        # surface the new channel in the sidebar without an extra fetch.
        await self.send_json({"event": "channel.added.to_you", **event["payload"]})

    async def chat_channel_removed_from_you(self, event):
        # Counterpart to channel.added.to_you — fired on the kicked /
        # leaving user's presence group so their sidebar drops the row.
        await self.send_json({"event": "channel.removed.from_you", **event["payload"]})

    async def chat_read_advanced(self, event):
        await self.send_json({"event": "read.advanced", **event["payload"]})

    async def chat_dm_opened(self, event):
        await self.send_json({"event": "dm.opened", **event["payload"]})

    # ── Internals ───────────────────────────────────────────────────────────
    async def _group_add(self, group: str) -> None:
        await self.channel_layer.group_add(group, self.channel_name)
        self._subscribed_groups.add(group)

    async def _group_discard(self, group: str) -> None:
        await self.channel_layer.group_discard(group, self.channel_name)
        self._subscribed_groups.discard(group)

    async def _authorize_channel(self, channel_id) -> bool:
        cache_key = str(channel_id)
        if cache_key in self._authz_cache:
            return self._authz_cache[cache_key]
        ok = await _can_access_channel(self.user.id, channel_id)
        self._authz_cache[cache_key] = ok
        return ok

    async def _send_error(self, code: str, detail: str) -> None:
        await self.send_json({"event": "error", "code": code, "detail": detail})


# ─── AgentStreamConsumer ─────────────────────────────────────────────────────
class AgentStreamConsumer(AsyncJsonWebsocketConsumer):
    """
    Token streaming for one agent run. The agent worker publishes to
    ``agent-run-{run_id}-tokens`` via ``channel_layer.group_send``;
    this consumer forwards to the connected user.
    """

    async def connect(self):
        user = self.scope.get("user")
        if user is None or not getattr(user, "is_authenticated", False):
            await self.close(code=4401)
            return

        run_id = self.scope["url_route"]["kwargs"]["run_id"]
        # v1: no per-run ownership table exists yet. Allow any authed user;
        # tighten in agent module when AgentRun lands.
        self.user = user
        self.run_id = run_id
        self.group_name = agent_run_group(run_id)

        subprotocol = self.scope.get("jwt_subprotocol")
        await self.accept(subprotocol=subprotocol)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.send_json({"event": "connected", "run_id": run_id})

    async def disconnect(self, code):
        if hasattr(self, "group_name"):
            try:
                await self.channel_layer.group_discard(self.group_name, self.channel_name)
            except Exception as exc:  # noqa: BLE001
                logger.warning("agent_group_discard_failed", extra={"error": str(exc)})

    async def agent_token(self, event):
        await self.send_json({"event": "agent.token", **event.get("payload", {})})

    async def agent_status(self, event):
        await self.send_json({"event": "agent.status", **event.get("payload", {})})
