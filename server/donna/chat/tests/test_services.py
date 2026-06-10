"""
Phase 2b + 2c service-layer tests — guest enforcement, visible_channels,
authorize_delete_message, and ``Channel.settings`` flag behavior.
"""
from __future__ import annotations

from django.test import TestCase

from donna.chat.models import Channel, ChannelMembership
from donna.chat.services import ChannelService
from donna.chat.tests.factories import make_channel, make_message
from donna.core.tests.helpers import api_client
from donna.users.tests.factories import make_user
from donna.workspaces.models import WorkspaceMembership
from donna.workspaces.tests.factories import make_workspace


class VisibleChannelsTest(TestCase):
    """``ChannelService.visible_channels`` — Slack-style "browse" gated by role."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = make_user(email="alice@vis.test")
        cls.bob = make_user(email="bob@vis.test")
        cls.guest = make_user(email="guest@vis.test")
        cls.workspace = make_workspace(
            name="VisWS", owner=cls.alice,
            members=[
                (cls.bob, WorkspaceMembership.Role.MEMBER),
                (cls.guest, WorkspaceMembership.Role.GUEST),
            ],
        )
        cls.public_ch = make_channel(
            workspace=cls.workspace, name="public", slug="public",
            visibility=Channel.Visibility.PUBLIC,
            admins=[cls.alice],
        )
        cls.private_ch = make_channel(
            workspace=cls.workspace, name="private", slug="private",
            visibility=Channel.Visibility.PRIVATE,
            admins=[cls.alice],
        )
        cls.dm = make_channel(
            workspace=cls.workspace, kind=Channel.Kind.DIRECT,
            members=[cls.alice, cls.bob],
        )

    def test_default_lists_only_memberships(self):
        # bob is a member of the DM but not the public/private channels.
        qs = ChannelService.visible_channels(
            user=self.bob, workspace=self.workspace,
        )
        ids = {c.id for c in qs}
        self.assertEqual(ids, {self.dm.id})

    def test_include_public_surfaces_public_channels_for_member(self):
        qs = ChannelService.visible_channels(
            user=self.bob, workspace=self.workspace, include_public=True,
        )
        ids = {c.id for c in qs}
        self.assertIn(self.public_ch.id, ids)
        self.assertNotIn(self.private_ch.id, ids)

    def test_include_public_does_not_surface_other_users_dms(self):
        # Set up a DM bob is NOT in.
        third = make_user(email="third@vis.test")
        WorkspaceMembership.objects.create(
            workspace=self.workspace, user=third,
            role=WorkspaceMembership.Role.MEMBER,
        )
        other_dm = make_channel(
            workspace=self.workspace, kind=Channel.Kind.DIRECT,
            members=[self.alice, third],
        )
        qs = ChannelService.visible_channels(
            user=self.bob, workspace=self.workspace, include_public=True,
        )
        ids = {c.id for c in qs}
        self.assertNotIn(other_dm.id, ids)
        # bob's own DM is still visible because he IS a member.
        self.assertIn(self.dm.id, ids)

    def test_guest_never_browses_public_channels(self):
        # Note: guest is not a member of any channel here, so the list
        # is empty. The point being asserted is that ?include_public
        # does not relax the rule for guests.
        qs = ChannelService.visible_channels(
            user=self.guest, workspace=self.workspace, include_public=True,
        )
        self.assertEqual(list(qs), [])

    def test_member_who_joined_sees_joined_channel(self):
        ChannelMembership.objects.create(
            channel=self.private_ch, user=self.bob,
        )
        qs = ChannelService.visible_channels(
            user=self.bob, workspace=self.workspace,
        )
        ids = {c.id for c in qs}
        self.assertIn(self.private_ch.id, ids)


class RefuseIfGuestTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = make_user(email="alice@rg.test")
        cls.guest = make_user(email="guest@rg.test")
        cls.workspace = make_workspace(
            name="RG", owner=cls.alice,
            members=[(cls.guest, WorkspaceMembership.Role.GUEST)],
        )

    def test_guest_is_refused(self):
        with self.assertRaises(PermissionError):
            ChannelService.refuse_if_guest(
                user=self.guest, workspace=self.workspace,
                action="frobnicate",
            )

    def test_non_guest_passes(self):
        ChannelService.refuse_if_guest(
            user=self.alice, workspace=self.workspace, action="frobnicate",
        )

    def test_user_outside_workspace_passes(self):
        # Workspace-level membership is enforced upstream; this helper
        # only blocks confirmed GUESTs, not arbitrary outsiders.
        outsider = make_user(email="outsider@rg.test")
        ChannelService.refuse_if_guest(
            user=outsider, workspace=self.workspace, action="frobnicate",
        )


class AuthorizeDeleteMessageTest(TestCase):
    """Phase 1.1 service-layer authz — used by both REST + WS."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = make_user(email="alice@auth.test")
        cls.bob = make_user(email="bob@auth.test")
        cls.charlie = make_user(email="charlie@auth.test")
        cls.workspace = make_workspace(
            name="AuthWS", owner=cls.alice,
            members=[
                (cls.bob, WorkspaceMembership.Role.MEMBER),
                (cls.charlie, WorkspaceMembership.Role.MEMBER),
            ],
        )
        cls.channel = make_channel(
            workspace=cls.workspace, name="general", slug="general",
            admins=[cls.alice], members=[cls.bob, cls.charlie],
        )

    def test_author_allowed(self):
        msg = make_message(channel=self.channel, author=self.bob)
        ChannelService.authorize_delete_message(user=self.bob, message=msg)

    def test_channel_admin_allowed(self):
        msg = make_message(channel=self.channel, author=self.bob)
        ChannelService.authorize_delete_message(user=self.alice, message=msg)

    def test_member_non_author_refused(self):
        msg = make_message(channel=self.channel, author=self.bob)
        with self.assertRaises(PermissionError):
            ChannelService.authorize_delete_message(
                user=self.charlie, message=msg,
            )


class GuestRESTGatesTest(TestCase):
    """Phase 2b — REST endpoints surface the same gates."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = make_user(email="alice@gates.test")
        cls.guest = make_user(email="guest@gates.test")
        cls.workspace = make_workspace(
            name="GatesWS", owner=cls.alice,
            members=[(cls.guest, WorkspaceMembership.Role.GUEST)],
        )
        cls.public_ch = make_channel(
            workspace=cls.workspace, name="public", slug="public",
            visibility=Channel.Visibility.PUBLIC,
            admins=[cls.alice],
        )

    def test_guest_create_channel_returns_403(self):
        c = api_client(user=self.guest, workspace=self.workspace)
        r = c.post(
            "/api/v1/chat/channels/",
            {"name": "wanted", "slug": "wanted"}, format="json",
        )
        self.assertEqual(r.status_code, 403)

    def test_guest_self_join_public_returns_403(self):
        c = api_client(user=self.guest, workspace=self.workspace)
        r = c.post(
            f"/api/v1/chat/channels/{self.public_ch.id}/members/",
            {}, format="json",
        )
        self.assertEqual(r.status_code, 403)

    def test_admin_can_add_guest_to_private_channel(self):
        """Guests can be ADDED to channels — they just can't self-join."""
        private_ch = make_channel(
            workspace=self.workspace, name="priv2", slug="priv2",
            visibility=Channel.Visibility.PRIVATE,
            admins=[self.alice],
        )
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.post(
            f"/api/v1/chat/channels/{private_ch.id}/members/",
            {"user_id": str(self.guest.id)}, format="json",
        )
        self.assertEqual(r.status_code, 201)


class ChannelSettingsTest(TestCase):
    """Phase 2c — ``Channel.settings`` flags + ``allow_member_invites`` enforcement."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = make_user(email="alice@s.test")
        cls.bob = make_user(email="bob@s.test")
        cls.charlie = make_user(email="charlie@s.test")
        cls.workspace = make_workspace(
            name="SettingsWS", owner=cls.alice,
            members=[
                (cls.bob, WorkspaceMembership.Role.MEMBER),
                (cls.charlie, WorkspaceMembership.Role.MEMBER),
            ],
        )

    def test_get_setting_returns_default_when_key_missing(self):
        ch = make_channel(workspace=self.workspace, name="a", slug="a")
        self.assertFalse(ch.get_setting("allow_member_invites"))

    def test_get_setting_returns_stored_value_when_set(self):
        ch = make_channel(
            workspace=self.workspace, name="b", slug="b",
            settings={"allow_member_invites": True},
        )
        self.assertTrue(ch.get_setting("allow_member_invites"))

    def test_get_setting_unknown_key_returns_false(self):
        ch = make_channel(workspace=self.workspace, name="c", slug="c")
        self.assertFalse(ch.get_setting("not_a_real_flag"))

    def test_non_admin_invite_blocked_by_default(self):
        ch = make_channel(
            workspace=self.workspace, name="d", slug="d",
            admins=[self.alice], members=[self.bob],
        )
        c = api_client(user=self.bob, workspace=self.workspace)
        r = c.post(
            f"/api/v1/chat/channels/{ch.id}/members/",
            {"user_id": str(self.charlie.id)}, format="json",
        )
        self.assertEqual(r.status_code, 403)

    def test_non_admin_invite_allowed_when_flag_on(self):
        ch = make_channel(
            workspace=self.workspace, name="e", slug="e",
            admins=[self.alice], members=[self.bob],
            settings={"allow_member_invites": True},
        )
        c = api_client(user=self.bob, workspace=self.workspace)
        r = c.post(
            f"/api/v1/chat/channels/{ch.id}/members/",
            {"user_id": str(self.charlie.id)}, format="json",
        )
        self.assertEqual(r.status_code, 201)

    def test_non_admin_cannot_grant_admin_role_even_when_invites_open(self):
        ch = make_channel(
            workspace=self.workspace, name="f", slug="f",
            admins=[self.alice], members=[self.bob],
            settings={"allow_member_invites": True},
        )
        c = api_client(user=self.bob, workspace=self.workspace)
        r = c.post(
            f"/api/v1/chat/channels/{ch.id}/members/",
            {"user_id": str(self.charlie.id), "role": "admin"}, format="json",
        )
        self.assertEqual(r.status_code, 403)
