"""Plan 14 backend coverage — pins, mentions, reactions, threading.

Focused on the service layer + model invariants. WS broadcasts are
exercised through ChannelService methods (channel layer is the no-op
in-memory one in tests), so we assert on DB state + return values.

Helpers mirror ``test_agents_a2._make_ws_and_channel`` to keep fixtures
cheap (no factory-boy dep).
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from donna.chat.mentions import parse as parse_mentions
from donna.chat.models import (
    AgentSession,
    Channel,
    ChannelMembership,
    ChannelPin,
    Message,
    MessageReaction,
)
from donna.chat.services import ChannelService
from donna.workspaces.models import Workspace, WorkspaceMembership


User = get_user_model()


def _make_user(email: str, handle: str | None = None) -> User:
    return User.objects.create_user(email=email, password="x", handle=handle)


def _make_ws(slug: str, owner: User) -> Workspace:
    ws = Workspace.objects.create(name="T", slug=slug, created_by=owner, modified_by=owner)
    WorkspaceMembership.objects.create(
        workspace=ws, user=owner, role=WorkspaceMembership.Role.OWNER,
    )
    return ws


def _make_channel(ws: Workspace, owner: User, *, name="general") -> Channel:
    ch = Channel.objects.create(
        workspace=ws, kind=Channel.Kind.CHANNEL, name=name, slug=name,
        visibility=Channel.Visibility.PUBLIC,
        created_by=owner, modified_by=owner,
    )
    ChannelMembership.objects.create(channel=ch, user=owner, role=ChannelMembership.Role.ADMIN)
    return ch


# ── Pins ────────────────────────────────────────────────────────────────


class ChannelPinTests(TestCase):
    def test_pin_creates_row(self):
        u = _make_user("a@x")
        ws = _make_ws("p1", u)
        ch = _make_channel(ws, u)

        pin = ChannelService.pin_channel(user=u, channel=ch)

        self.assertEqual(ChannelPin.objects.filter(user=u, channel=ch).count(), 1)
        self.assertEqual(pin.user, u)

    def test_pin_idempotent(self):
        u = _make_user("a@x")
        ws = _make_ws("p2", u)
        ch = _make_channel(ws, u)

        ChannelService.pin_channel(user=u, channel=ch)
        ChannelService.pin_channel(user=u, channel=ch)

        self.assertEqual(ChannelPin.objects.filter(user=u, channel=ch).count(), 1)

    def test_unpin_removes(self):
        u = _make_user("a@x")
        ws = _make_ws("p3", u)
        ch = _make_channel(ws, u)
        ChannelService.pin_channel(user=u, channel=ch)

        removed = ChannelService.unpin_channel(user=u, channel=ch)

        self.assertTrue(removed)
        self.assertFalse(ChannelPin.objects.filter(user=u, channel=ch).exists())

    def test_unpin_idempotent_when_absent(self):
        u = _make_user("a@x")
        ws = _make_ws("p4", u)
        ch = _make_channel(ws, u)

        removed = ChannelService.unpin_channel(user=u, channel=ch)

        self.assertFalse(removed)


# ── Mentions ────────────────────────────────────────────────────────────


class MentionsParserTests(TestCase):
    def test_resolves_user_handle(self):
        owner = _make_user("o@x")
        ws = _make_ws("m1", owner)
        ch = _make_channel(ws, owner)
        alice = _make_user("alice@x", handle="alice")
        WorkspaceMembership.objects.create(workspace=ws, user=alice)

        users, flags = parse_mentions("hey @alice ready?", ch)

        self.assertEqual([u.id for u in users], [alice.id])
        self.assertFalse(flags["donna"])
        self.assertFalse(flags["channel"])
        self.assertFalse(flags["everyone"])

    def test_special_flags(self):
        owner = _make_user("o@x")
        ws = _make_ws("m2", owner)
        ch = _make_channel(ws, owner)

        users, flags = parse_mentions("@donna please @everyone help @channel", ch)

        self.assertEqual(users, [])
        self.assertTrue(flags["donna"])
        self.assertTrue(flags["channel"])
        self.assertTrue(flags["everyone"])

    def test_does_not_match_email_substring(self):
        owner = _make_user("o@x")
        ws = _make_ws("m3", owner)
        ch = _make_channel(ws, owner)
        alice = _make_user("alice@x", handle="alice")
        WorkspaceMembership.objects.create(workspace=ws, user=alice)

        users, flags = parse_mentions("send to alice@example.com", ch)

        self.assertEqual(users, [])
        self.assertFalse(any(flags.values()))

    def test_handle_cross_workspace_isolated(self):
        owner_a = _make_user("oa@x")
        owner_b = _make_user("ob@x")
        ws_a = _make_ws("mwa", owner_a)
        ws_b = _make_ws("mwb", owner_b)
        ch_a = _make_channel(ws_a, owner_a)
        bob = _make_user("bob@x", handle="bob")
        WorkspaceMembership.objects.create(workspace=ws_b, user=bob)

        users, _ = parse_mentions("hi @bob", ch_a)

        self.assertEqual(users, [], "handle must not resolve across workspaces")


class SendMessageMentionsTests(TestCase):
    def test_send_message_persists_mentions(self):
        owner = _make_user("o@x")
        ws = _make_ws("sm1", owner)
        ch = _make_channel(ws, owner)
        alice = _make_user("alice@x", handle="alice")
        WorkspaceMembership.objects.create(workspace=ws, user=alice)
        ChannelMembership.objects.create(channel=ch, user=alice)

        msg = ChannelService.send_message(
            channel=ch, sender_user=owner,
            body="hey @alice + @donna take a look",
        )

        msg.refresh_from_db()
        self.assertEqual([u.id for u in msg.mentions.all()], [alice.id])
        self.assertTrue(msg.mention_flags.get("donna"))
        self.assertFalse(msg.mention_flags.get("everyone"))

    def test_donna_mention_records_to_agent_memory(self):
        owner = _make_user("o@x")
        ws = _make_ws("sm2", owner)
        ch = _make_channel(ws, owner)
        session = AgentSession.objects.create(channel=ch, name="Donna")

        # ``_record_agent_mention`` runs via ``transaction.on_commit`` so it
        # only fires when the outer transaction commits. TestCase wraps each
        # test in a rolled-back transaction; capture-and-execute the hooks
        # manually to exercise the side effect.
        with self.captureOnCommitCallbacks(execute=True):
            ChannelService.send_message(
                channel=ch, sender_user=owner,
                body="@donna can you help?",
            )

        session.refresh_from_db()
        mentions = (session.memory or {}).get("mentions", [])
        self.assertEqual(len(mentions), 1)
        self.assertIn("body_preview", mentions[0])
        self.assertIn("can you help?", mentions[0]["body_preview"])


# ── Reactions ───────────────────────────────────────────────────────────


class ReactionsTests(TestCase):
    def _setup_msg(self, label="r"):
        owner = _make_user(f"{label}@x")
        ws = _make_ws(f"rx-{label}", owner)
        ch = _make_channel(ws, owner)
        msg = ChannelService.send_message(channel=ch, sender_user=owner, body="hi")
        return owner, ch, msg

    def test_add_reaction(self):
        u, _, msg = self._setup_msg("a")

        r = ChannelService.add_reaction(user=u, message=msg, emoji="thumbsup")

        self.assertEqual(r.emoji, "thumbsup")
        self.assertEqual(MessageReaction.objects.filter(message=msg).count(), 1)

    def test_add_reaction_idempotent(self):
        u, _, msg = self._setup_msg("b")

        ChannelService.add_reaction(user=u, message=msg, emoji="heart")
        ChannelService.add_reaction(user=u, message=msg, emoji="heart")

        self.assertEqual(MessageReaction.objects.filter(message=msg, emoji="heart").count(), 1)

    def test_remove_reaction(self):
        u, _, msg = self._setup_msg("c")
        ChannelService.add_reaction(user=u, message=msg, emoji="fire")

        removed = ChannelService.remove_reaction(user=u, message=msg, emoji="fire")

        self.assertTrue(removed)
        self.assertFalse(MessageReaction.objects.filter(message=msg).exists())

    def test_reject_unknown_emoji(self):
        u, _, msg = self._setup_msg("d")

        with self.assertRaises(ValueError):
            ChannelService.add_reaction(user=u, message=msg, emoji="not_a_real_emoji_code_xyz")


# ── Threading ───────────────────────────────────────────────────────────


class ThreadingTests(TestCase):
    def test_reply_sets_parent_fk(self):
        owner = _make_user("o@x")
        ws = _make_ws("th1", owner)
        ch = _make_channel(ws, owner)

        top = ChannelService.send_message(channel=ch, sender_user=owner, body="top")
        reply = ChannelService.send_message(
            channel=ch, sender_user=owner, body="reply", parent=top,
        )

        self.assertEqual(reply.parent_id, top.id)
        self.assertEqual(top.replies.count(), 1)

    def test_replies_default_to_top_level(self):
        owner = _make_user("o@x")
        ws = _make_ws("th2", owner)
        ch = _make_channel(ws, owner)

        m = ChannelService.send_message(channel=ch, sender_user=owner, body="hi")

        self.assertIsNone(m.parent_id)
        self.assertEqual(Message.objects.filter(parent__isnull=True).count(), 1)
