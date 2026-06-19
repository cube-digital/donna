"""build_state branch-aware compaction tests.

DB-bound (uses real Channel + AgentSession + Message). The compaction
LLM call is stubbed by monkey-patching ``_haiku_compact`` so tests
don't hit Anthropic.
"""
from __future__ import annotations

from datetime import datetime, timezone

from django.contrib.auth import get_user_model
from django.test import TestCase

from donna.chat.agents.state import builder as builder_mod
from donna.chat.agents.state.builder import (
    COMPACTION_TRIGGER,
    HISTORY_WINDOW,
    KEEP_VERBATIM_RECENT,
    build_state,
)
from donna.chat.models import AgentSession, Channel, ChannelMembership, Message
from donna.workspaces.models import Workspace, WorkspaceMembership


User = get_user_model()


class BuildStateCompactionTests(TestCase):
    def setUp(self) -> None:
        self.workspace = Workspace.objects.create(name="W", slug="w-build-state")
        self.user = User.objects.create(email="u@example.com")
        WorkspaceMembership.objects.create(workspace=self.workspace, user=self.user)
        self.dm = Channel.objects.create(
            kind=Channel.Kind.DIRECT,
            visibility=Channel.Visibility.PRIVATE,
            workspace=self.workspace,
        )
        ChannelMembership.objects.create(channel=self.dm, user=self.user)
        self.session = AgentSession.objects.create(channel=self.dm, name="Donna")

    def _send(self, body: str) -> Message:
        return Message.objects.create(
            channel=self.dm, author_user=self.user, body=body,
        )

    def test_short_history_no_compaction(self) -> None:
        for i in range(5):
            self._send(f"msg {i}")
        state = build_state(self.dm, self.session)
        # No system "EARLIER CONVERSATION" message because history is short.
        contents = [m.get("content", "") for m in state.messages]
        self.assertFalse(any("EARLIER CONVERSATION" in c for c in contents))
        # 5 user msgs in chronological order.
        user_msgs = [m for m in state.messages if m["role"] == "user"]
        self.assertEqual(len(user_msgs), 5)

    def test_long_history_triggers_compaction(self) -> None:
        # Stub Haiku to avoid the LLM call.
        builder_mod._haiku_compact = lambda bulk: "== EARLIER CONVERSATION (compacted) ==\nfake digest"

        for i in range(COMPACTION_TRIGGER + 10):
            self._send(f"msg {i}")

        state = build_state(self.dm, self.session)
        # The compacted digest should appear as a system message at the top
        # (after any rolling summary; we set none here).
        system_msgs = [m for m in state.messages if m["role"] == "system"]
        self.assertTrue(any("EARLIER CONVERSATION" in m["content"] for m in system_msgs))

        # Recent tail (KEEP_VERBATIM_RECENT) must be present verbatim.
        user_msgs = [m for m in state.messages if m["role"] == "user"]
        self.assertGreaterEqual(len(user_msgs), KEEP_VERBATIM_RECENT)

    def test_compaction_cached_on_second_call(self) -> None:
        # First call writes digest to session.memory; second call returns
        # the cached text without invoking the stub again.
        calls = {"n": 0}

        def _stub(bulk: str) -> str:
            calls["n"] += 1
            return "== EARLIER CONVERSATION (compacted) ==\ncached digest"

        builder_mod._haiku_compact = _stub

        for i in range(COMPACTION_TRIGGER + 10):
            self._send(f"msg {i}")

        build_state(self.dm, self.session)
        first_calls = calls["n"]
        # Reload session so we pick up the memory write from build_state.
        self.session.refresh_from_db()

        build_state(self.dm, self.session)
        # Second call hits the cache — no extra _haiku_compact invocation.
        self.assertEqual(calls["n"], first_calls)

    def test_recent_window_only_when_under_window(self) -> None:
        for i in range(HISTORY_WINDOW - 5):
            self._send(f"msg {i}")
        state = build_state(self.dm, self.session)
        # Should be no compaction, just the verbatim chronological list.
        contents = [m.get("content", "") for m in state.messages]
        self.assertFalse(any("EARLIER CONVERSATION" in c for c in contents))
