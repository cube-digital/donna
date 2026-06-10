"""
Chat model-level tests — DB constraints, ``get_setting`` semantics,
slug uniqueness, message-author XOR, DM visibility CHECK.
"""
from __future__ import annotations

from django.db import IntegrityError
from django.test import TestCase

from donna.chat.models import Channel, ChannelMembership, Message
from donna.chat.tests.factories import make_channel
from donna.users.tests.factories import make_user
from donna.workspaces.tests.factories import make_workspace


class ChannelConstraintsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = make_user(email="alice@const.test")
        cls.workspace = make_workspace(name="ConstWS", owner=cls.alice)
        cls.other_workspace = make_workspace(name="OtherWS", owner=cls.alice)

    def test_slug_unique_per_workspace_for_named_channels(self):
        Channel.objects.create(
            workspace=self.workspace, kind=Channel.Kind.CHANNEL,
            name="dup", slug="dup",
        )
        with self.assertRaises(IntegrityError):
            Channel.objects.create(
                workspace=self.workspace, kind=Channel.Kind.CHANNEL,
                name="dup", slug="dup",
            )

    def test_same_slug_in_different_workspaces_is_ok(self):
        Channel.objects.create(
            workspace=self.workspace, kind=Channel.Kind.CHANNEL,
            name="dup", slug="dup",
        )
        Channel.objects.create(
            workspace=self.other_workspace, kind=Channel.Kind.CHANNEL,
            name="dup", slug="dup",
        )

    def test_dm_slug_constraint_does_not_apply_to_direct(self):
        # Two DMs in the same workspace with empty slugs — partial unique
        # index excludes blank slugs.
        Channel.objects.create(
            workspace=self.workspace, kind=Channel.Kind.DIRECT,
            visibility=Channel.Visibility.PRIVATE, name="", slug="",
        )
        Channel.objects.create(
            workspace=self.workspace, kind=Channel.Kind.DIRECT,
            visibility=Channel.Visibility.PRIVATE, name="", slug="",
        )

    def test_dm_must_be_private_check_constraint(self):
        # The CHECK constraint forbids direct channels with visibility=public.
        with self.assertRaises(IntegrityError):
            Channel.objects.create(
                workspace=self.workspace, kind=Channel.Kind.DIRECT,
                visibility=Channel.Visibility.PUBLIC, name="", slug="",
            )


class ChannelGetSettingTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.workspace = make_workspace(name="GSWS")

    def test_default_when_unset(self):
        ch = make_channel(workspace=self.workspace, name="a", slug="a")
        self.assertFalse(ch.get_setting("allow_member_invites"))
        self.assertFalse(ch.get_setting("allow_member_pins"))
        self.assertFalse(ch.get_setting("read_only"))

    def test_override_returned_when_set(self):
        ch = make_channel(
            workspace=self.workspace, name="b", slug="b",
            settings={"allow_member_pins": True, "read_only": True},
        )
        self.assertTrue(ch.get_setting("allow_member_pins"))
        self.assertTrue(ch.get_setting("read_only"))
        # Unset keys still hit defaults.
        self.assertFalse(ch.get_setting("allow_member_invites"))

    def test_unknown_key_returns_false(self):
        ch = make_channel(workspace=self.workspace, name="c", slug="c")
        self.assertFalse(ch.get_setting("flag-that-doesnt-exist"))


class MessageAuthorXORTest(TestCase):
    """``Message.message_has_exactly_one_author`` CHECK constraint."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = make_user(email="alice@xor.test")
        cls.workspace = make_workspace(name="XorWS", owner=cls.alice)
        cls.channel = make_channel(
            workspace=cls.workspace, name="ch", slug="ch", admins=[cls.alice],
        )

    def test_with_both_authors_null_fails(self):
        with self.assertRaises(IntegrityError):
            Message.objects.create(
                channel=self.channel, body="orphan",
                author_user=None, author_agent=None,
            )


class ChannelMembershipUniqueTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = make_user(email="alice@uq.test")
        cls.workspace = make_workspace(name="UqWS", owner=cls.alice)
        cls.channel = make_channel(
            workspace=cls.workspace, name="ch", slug="ch", admins=[cls.alice],
        )

    def test_duplicate_membership_rejected(self):
        with self.assertRaises(IntegrityError):
            ChannelMembership.objects.create(
                channel=self.channel, user=self.alice,
                role=ChannelMembership.Role.MEMBER,
            )
