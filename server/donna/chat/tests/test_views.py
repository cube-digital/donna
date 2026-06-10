"""
Phase 1 integration — REST surface for channels, messages, members, DMs.

Each test class focuses on one sub-phase from the plan
(server/plans/04-roadmap.md → "Phase 1 Channels & DMs Hardening"):

  1.1  AdminDeleteMessage         — author / channel-admin authz parity (REST)
  1.2  ChannelInviteFlow          — admin-add / self-join / kick / leave + dual broadcast
  1.3  GroupDM                    — exact-set-match semantics, idempotency
  1.4  DMWorkspaceDisambiguation  — workspace_id picks the right DM, fallback warns
  1.5  BrowsePublicChannels       — ?include_public surfaces public, hides private
"""
from __future__ import annotations

from django.test import TestCase

from donna.chat.models import Channel, ChannelMembership, Message
from donna.chat.tests.factories import make_channel, make_message
from donna.core.tests.helpers import api_client, envelope
from donna.users.tests.factories import make_user
from donna.workspaces.models import WorkspaceMembership
from donna.workspaces.tests.factories import make_workspace


def _seed(cls):
    cls.alice = make_user(email="alice@chat.test")
    cls.bob = make_user(email="bob@chat.test")
    cls.charlie = make_user(email="charlie@chat.test")
    cls.workspace = make_workspace(
        name="ChatWS", owner=cls.alice,
        members=[
            (cls.bob, WorkspaceMembership.Role.MEMBER),
            (cls.charlie, WorkspaceMembership.Role.MEMBER),
        ],
    )


# ── 1.1 Admin delete others' messages ───────────────────────────────────────
class AdminDeleteMessageTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        _seed(cls)
        cls.channel = make_channel(
            workspace=cls.workspace, name="general", slug="general",
            admins=[cls.alice], members=[cls.bob, cls.charlie],
        )

    def _post_msg(self, author, body="hi"):
        return make_message(channel=self.channel, author=author, body=body)

    def test_author_can_delete_own_message(self):
        msg = self._post_msg(self.bob)
        c = api_client(user=self.bob, workspace=self.workspace)
        r = c.delete(f"/api/v1/chat/messages/{msg.id}/")
        self.assertEqual(r.status_code, 204)
        self.assertFalse(Message.objects.filter(id=msg.id).exists())

    def test_channel_admin_can_delete_others_message(self):
        msg = self._post_msg(self.bob)
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.delete(f"/api/v1/chat/messages/{msg.id}/")
        self.assertEqual(r.status_code, 204)
        self.assertFalse(Message.objects.filter(id=msg.id).exists())

    def test_non_admin_non_author_cannot_delete(self):
        msg = self._post_msg(self.bob)
        c = api_client(user=self.charlie, workspace=self.workspace)
        r = c.delete(f"/api/v1/chat/messages/{msg.id}/")
        self.assertEqual(r.status_code, 403)
        self.assertTrue(Message.objects.filter(id=msg.id).exists())


# ── 1.2 Channel invite flow ─────────────────────────────────────────────────
class ChannelInviteFlowTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        _seed(cls)
        cls.private = make_channel(
            workspace=cls.workspace, name="secret", slug="secret",
            visibility=Channel.Visibility.PRIVATE,
            admins=[cls.alice],
        )
        cls.public = make_channel(
            workspace=cls.workspace, name="general", slug="general",
            visibility=Channel.Visibility.PUBLIC,
            admins=[cls.alice],
        )

    def test_admin_invite_creates_membership(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.post(
            f"/api/v1/chat/channels/{self.private.id}/members/",
            {"user_id": str(self.bob.id)}, format="json",
        )
        self.assertEqual(r.status_code, 201)
        self.assertTrue(
            ChannelMembership.objects.filter(
                channel=self.private, user=self.bob
            ).exists()
        )

    def test_non_admin_invite_rejected(self):
        # Make bob a member but NOT admin
        ChannelMembership.objects.create(
            channel=self.private, user=self.bob,
            role=ChannelMembership.Role.MEMBER,
        )
        c = api_client(user=self.bob, workspace=self.workspace)
        r = c.post(
            f"/api/v1/chat/channels/{self.private.id}/members/",
            {"user_id": str(self.charlie.id)}, format="json",
        )
        self.assertEqual(r.status_code, 403)

    def test_cannot_invite_user_outside_workspace(self):
        outsider = make_user(email="outside@chat.test")
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.post(
            f"/api/v1/chat/channels/{self.private.id}/members/",
            {"user_id": str(outsider.id)}, format="json",
        )
        self.assertEqual(r.status_code, 403)

    def test_self_join_public_channel(self):
        c = api_client(user=self.bob, workspace=self.workspace)
        r = c.post(
            f"/api/v1/chat/channels/{self.public.id}/members/",
            {}, format="json",
        )
        self.assertEqual(r.status_code, 201)

    def test_self_join_private_channel_rejected(self):
        c = api_client(user=self.bob, workspace=self.workspace)
        r = c.post(
            f"/api/v1/chat/channels/{self.private.id}/members/",
            {}, format="json",
        )
        self.assertEqual(r.status_code, 403)

    def test_list_members_requires_membership(self):
        # bob is not yet a member of secret → 403
        c = api_client(user=self.bob, workspace=self.workspace)
        r = c.get(f"/api/v1/chat/channels/{self.private.id}/members/")
        self.assertEqual(r.status_code, 403)

    def test_self_leave_returns_204(self):
        ChannelMembership.objects.create(
            channel=self.private, user=self.bob,
            role=ChannelMembership.Role.MEMBER,
        )
        c = api_client(user=self.bob, workspace=self.workspace)
        r = c.delete(
            f"/api/v1/chat/channels/{self.private.id}/members/{self.bob.id}/"
        )
        self.assertEqual(r.status_code, 204)
        self.assertFalse(
            ChannelMembership.objects.filter(
                channel=self.private, user=self.bob
            ).exists()
        )

    def test_admin_kick_returns_204(self):
        ChannelMembership.objects.create(
            channel=self.private, user=self.bob,
            role=ChannelMembership.Role.MEMBER,
        )
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.delete(
            f"/api/v1/chat/channels/{self.private.id}/members/{self.bob.id}/"
        )
        self.assertEqual(r.status_code, 204)

    def test_non_admin_cannot_kick_others(self):
        ChannelMembership.objects.create(
            channel=self.private, user=self.bob,
            role=ChannelMembership.Role.MEMBER,
        )
        ChannelMembership.objects.create(
            channel=self.private, user=self.charlie,
            role=ChannelMembership.Role.MEMBER,
        )
        c = api_client(user=self.bob, workspace=self.workspace)
        r = c.delete(
            f"/api/v1/chat/channels/{self.private.id}/members/{self.charlie.id}/"
        )
        self.assertEqual(r.status_code, 403)


# ── 1.3 Group DM ────────────────────────────────────────────────────────────
class GroupDMTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        _seed(cls)

    def test_creates_direct_channel_with_all_members(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.post(
            "/api/v1/chat/dms/group/",
            {"peer_user_ids": [str(self.bob.id), str(self.charlie.id)]},
            format="json",
        )
        self.assertEqual(r.status_code, 201)
        body = envelope(r)
        self.assertEqual(body["kind"], Channel.Kind.DIRECT)
        self.assertEqual(body["visibility"], Channel.Visibility.PRIVATE)

        channel = Channel.objects.get(id=body["id"])
        member_ids = set(channel.memberships.values_list("user_id", flat=True))
        self.assertEqual(
            member_ids, {self.alice.id, self.bob.id, self.charlie.id}
        )

    def test_idempotent_for_same_member_set(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r1 = c.post(
            "/api/v1/chat/dms/group/",
            {"peer_user_ids": [str(self.bob.id), str(self.charlie.id)]},
            format="json",
        )
        r2 = c.post(
            "/api/v1/chat/dms/group/",
            {"peer_user_ids": [str(self.charlie.id), str(self.bob.id)]},
            format="json",
        )
        self.assertEqual(envelope(r1)["id"], envelope(r2)["id"])

    def test_subset_is_not_a_match(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r3 = c.post(
            "/api/v1/chat/dms/group/",
            {"peer_user_ids": [str(self.bob.id), str(self.charlie.id)]},
            format="json",
        )
        r2 = c.post(
            "/api/v1/chat/dms/group/",
            {"peer_user_ids": [str(self.bob.id)]},
            format="json",
        )
        self.assertNotEqual(envelope(r3)["id"], envelope(r2)["id"])

    def test_member_outside_workspace_rejected(self):
        outsider = make_user(email="outside@gdm.test")
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.post(
            "/api/v1/chat/dms/group/",
            {"peer_user_ids": [str(self.bob.id), str(outsider.id)]},
            format="json",
        )
        self.assertEqual(r.status_code, 403)


# ── 1.4 DM workspace disambiguation ─────────────────────────────────────────
class DMWorkspaceDisambiguationTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = make_user(email="alice@dm.test")
        cls.bob = make_user(email="bob@dm.test")
        cls.ws_a = make_workspace(
            name="Alpha", owner=cls.alice,
            members=[(cls.bob, WorkspaceMembership.Role.MEMBER)],
        )
        cls.ws_b = make_workspace(
            name="Beta", owner=cls.alice,
            members=[(cls.bob, WorkspaceMembership.Role.MEMBER)],
        )

    def test_dms_in_different_workspaces_are_distinct_channels(self):
        c_a = api_client(user=self.alice, workspace=self.ws_a)
        c_b = api_client(user=self.alice, workspace=self.ws_b)
        r_a = c_a.post(
            "/api/v1/chat/dms/", {"peer_user_id": str(self.bob.id)},
            format="json",
        )
        r_b = c_b.post(
            "/api/v1/chat/dms/", {"peer_user_id": str(self.bob.id)},
            format="json",
        )
        self.assertEqual(r_a.status_code, 200)
        self.assertEqual(r_b.status_code, 200)
        self.assertNotEqual(envelope(r_a)["id"], envelope(r_b)["id"])
        # And each is scoped to its workspace.
        self.assertEqual(envelope(r_a)["workspace"], str(self.ws_a.id))
        self.assertEqual(envelope(r_b)["workspace"], str(self.ws_b.id))


# ── 1.5 Browse public channels ──────────────────────────────────────────────
class BrowsePublicChannelsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        _seed(cls)
        cls.public = make_channel(
            workspace=cls.workspace, name="general", slug="general",
            visibility=Channel.Visibility.PUBLIC,
            admins=[cls.alice],
        )
        cls.private = make_channel(
            workspace=cls.workspace, name="secret", slug="secret",
            visibility=Channel.Visibility.PRIVATE,
            admins=[cls.alice],
        )

    def test_default_list_returns_only_memberships(self):
        # bob isn't a member of either
        c = api_client(user=self.bob, workspace=self.workspace)
        r = c.get("/api/v1/chat/channels/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(envelope(r), [])

    def test_include_public_surfaces_only_public_channels(self):
        c = api_client(user=self.bob, workspace=self.workspace)
        r = c.get("/api/v1/chat/channels/?include_public=true")
        self.assertEqual(r.status_code, 200)
        ids = [ch["id"] for ch in envelope(r)]
        self.assertIn(str(self.public.id), ids)
        self.assertNotIn(str(self.private.id), ids)

    def test_non_member_can_GET_public_channel_detail(self):
        c = api_client(user=self.bob, workspace=self.workspace)
        r = c.get(f"/api/v1/chat/channels/{self.public.id}/")
        self.assertEqual(r.status_code, 200)

    def test_non_member_gets_404_on_private_channel_detail(self):
        c = api_client(user=self.bob, workspace=self.workspace)
        r = c.get(f"/api/v1/chat/channels/{self.private.id}/")
        self.assertEqual(r.status_code, 404)


# ── Edge cases on tested endpoints ──────────────────────────────────────────
class ChannelEdgeCasesTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        _seed(cls)
        cls.channel = make_channel(
            workspace=cls.workspace, name="general", slug="general",
            admins=[cls.alice], members=[cls.bob],
        )

    def test_create_channel_with_duplicate_slug_returns_400(self):
        """
        Slug uniqueness within a workspace is enforced at both the
        serializer (``validate_slug``) and the DB level
        (``uq_channel_workspace_slug``). The serializer check turns
        the duplicate into a clean 400 with a field error.
        """
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.post(
            "/api/v1/chat/channels/",
            {"name": "general", "slug": "general"}, format="json",
        )
        self.assertEqual(r.status_code, 400)
        # Field-scoped error (DRF default) — under StandardJSONRenderer
        # the error envelope places this under data.slug.
        body = r.json()
        self.assertIn("slug", str(body))

    def test_create_channel_with_unique_slug_succeeds(self):
        """Sanity guard — the validator doesn't false-positive on new slugs."""
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.post(
            "/api/v1/chat/channels/",
            {"name": "new-room", "slug": "new-room"}, format="json",
        )
        self.assertEqual(r.status_code, 201)

    def test_non_admin_patch_channel_403(self):
        c = api_client(user=self.bob, workspace=self.workspace)
        r = c.patch(
            f"/api/v1/chat/channels/{self.channel.id}/",
            {"topic": "hijacked"}, format="json",
        )
        self.assertEqual(r.status_code, 403)

    def test_non_admin_delete_channel_403(self):
        c = api_client(user=self.bob, workspace=self.workspace)
        r = c.delete(f"/api/v1/chat/channels/{self.channel.id}/")
        self.assertEqual(r.status_code, 403)

    def test_admin_delete_channel_204(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.delete(f"/api/v1/chat/channels/{self.channel.id}/")
        self.assertEqual(r.status_code, 204)
        self.assertFalse(Channel.objects.filter(id=self.channel.id).exists())


class MessageEdgeCasesTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        _seed(cls)
        cls.channel = make_channel(
            workspace=cls.workspace, name="msg-edge", slug="msg-edge",
            admins=[cls.alice], members=[cls.bob],
        )

    def test_non_author_edit_403(self):
        msg = make_message(channel=self.channel, author=self.bob)
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.patch(
            f"/api/v1/chat/messages/{msg.id}/",
            {"body": "hijack"}, format="json",
        )
        self.assertEqual(r.status_code, 403)

    def test_message_list_pagination_before(self):
        # Seed 5 messages then list with limit=2 + before=<oldest of recent batch>.
        for i in range(5):
            make_message(channel=self.channel, author=self.alice, body=f"m{i}")
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.get(
            f"/api/v1/chat/channels/{self.channel.id}/messages/?limit=2"
        )
        self.assertEqual(r.status_code, 200)
        data = envelope(r)
        self.assertEqual(len(data), 2)

    def test_non_member_cannot_send(self):
        # charlie is in the workspace but not the channel.
        c = api_client(user=self.charlie, workspace=self.workspace)
        r = c.post(
            f"/api/v1/chat/channels/{self.channel.id}/messages/",
            {"body": "hi"}, format="json",
        )
        self.assertEqual(r.status_code, 403)

    def test_non_member_cannot_list(self):
        c = api_client(user=self.charlie, workspace=self.workspace)
        r = c.get(f"/api/v1/chat/channels/{self.channel.id}/messages/")
        self.assertEqual(r.status_code, 403)


class DMEdgeCasesTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = make_user(email="alice@dme.test")
        cls.bob = make_user(email="bob@dme.test")
        cls.outsider = make_user(email="outsider@dme.test")
        cls.workspace = make_workspace(
            name="DmeWS", owner=cls.alice,
            members=[(cls.bob, WorkspaceMembership.Role.MEMBER)],
        )

    def test_dm_with_self_400(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.post(
            "/api/v1/chat/dms/",
            {"peer_user_id": str(self.alice.id)}, format="json",
        )
        self.assertEqual(r.status_code, 400)

    def test_dm_with_outsider_403(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.post(
            "/api/v1/chat/dms/",
            {"peer_user_id": str(self.outsider.id)}, format="json",
        )
        self.assertEqual(r.status_code, 403)

    def test_dm_with_nonexistent_user_404(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.post(
            "/api/v1/chat/dms/",
            {"peer_user_id": "00000000-0000-0000-0000-000000000000"},
            format="json",
        )
        self.assertEqual(r.status_code, 404)

    def test_dm_idempotent_within_same_workspace(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r1 = c.post(
            "/api/v1/chat/dms/",
            {"peer_user_id": str(self.bob.id)}, format="json",
        )
        r2 = c.post(
            "/api/v1/chat/dms/",
            {"peer_user_id": str(self.bob.id)}, format="json",
        )
        self.assertEqual(envelope(r1)["id"], envelope(r2)["id"])


class ReadStateEdgeCasesTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        _seed(cls)
        cls.channel_a = make_channel(
            workspace=cls.workspace, name="rsa", slug="rsa",
            admins=[cls.alice],
        )
        cls.channel_b = make_channel(
            workspace=cls.workspace, name="rsb", slug="rsb",
            admins=[cls.alice],
        )

    def test_advance_with_message_from_different_channel_404(self):
        # message in channel_b — try to advance read state in channel_a.
        msg = make_message(channel=self.channel_b, author=self.alice)
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.post(
            f"/api/v1/chat/channels/{self.channel_a.id}/read-state/",
            {"message_id": str(msg.id)}, format="json",
        )
        self.assertEqual(r.status_code, 404)

    def test_advance_pointer_does_not_regress(self):
        """
        ``ChannelService.advance_read_pointer`` is forward-only:
        attempting to "advance" to an older message is a no-op, so
        the unread count stays at 0 once we've already read past it.
        """
        m_older = make_message(
            channel=self.channel_a, author=self.alice, body="older",
        )
        m_newer = make_message(
            channel=self.channel_a, author=self.alice, body="newer",
        )
        c = api_client(user=self.alice, workspace=self.workspace)
        c.post(
            f"/api/v1/chat/channels/{self.channel_a.id}/read-state/",
            {"message_id": str(m_newer.id)}, format="json",
        )
        c.post(
            f"/api/v1/chat/channels/{self.channel_a.id}/read-state/",
            {"message_id": str(m_older.id)}, format="json",
        )
        r = c.get(f"/api/v1/chat/channels/{self.channel_a.id}/read-state/")
        # Pointer stays at m_newer, so unread count is 0.
        self.assertEqual(envelope(r)["unread_count"], 0)

    def test_unread_count_grows_with_new_messages(self):
        m1 = make_message(channel=self.channel_a, author=self.alice)
        c = api_client(user=self.alice, workspace=self.workspace)
        c.post(
            f"/api/v1/chat/channels/{self.channel_a.id}/read-state/",
            {"message_id": str(m1.id)}, format="json",
        )
        make_message(channel=self.channel_a, author=self.alice, body="newer")
        make_message(channel=self.channel_a, author=self.alice, body="newer2")
        r = c.get(f"/api/v1/chat/channels/{self.channel_a.id}/read-state/")
        self.assertEqual(envelope(r)["unread_count"], 2)
