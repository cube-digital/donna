"""Plan 13 §2.1 — mode-gated registry tests.

Covers ``build_registry`` against the three ``AgentSession.Mode`` values
and verifies the legacy ``draft_enabled`` shim still promotes to drafting
so existing rows keep working through the migration.
"""
from __future__ import annotations

from types import SimpleNamespace

from django.test import SimpleTestCase

from donna.chat.agents.tools.factory import (
    DRAFT_TOOL_NAMES,
    PLANNING_TOOL_NAMES,
    QA_TOOL_NAMES,
    build_registry,
)
from donna.chat.models import AgentSession


class ModeGatedRegistryTests(SimpleTestCase):
    """Build a registry per mode; check the tool set is what we expect."""

    def setUp(self):
        # build_registry only reads ``channel`` as a passthrough — the
        # SimpleNamespace stub is enough; we never touch DB.
        self.channel = SimpleNamespace(id="ch")

    def _names(self, registry):
        return set(registry.names())

    def test_chat_mode_exposes_qa_tools_only(self):
        reg = build_registry(channel=self.channel, mode=AgentSession.Mode.CHAT)
        names = self._names(reg)
        self.assertEqual(names, set(QA_TOOL_NAMES))
        for tool in DRAFT_TOOL_NAMES:
            self.assertNotIn(tool, names)

    def test_drafting_mode_exposes_qa_plus_draft_tools(self):
        reg = build_registry(channel=self.channel, mode=AgentSession.Mode.DRAFTING)
        names = self._names(reg)
        for tool in QA_TOOL_NAMES:
            self.assertIn(tool, names)
        for tool in DRAFT_TOOL_NAMES:
            self.assertIn(tool, names)

    def test_planning_mode_is_read_only(self):
        """Planning ships QA + read_draft, but never the mutators."""
        reg = build_registry(channel=self.channel, mode=AgentSession.Mode.PLANNING)
        names = self._names(reg)
        self.assertEqual(names, set(PLANNING_TOOL_NAMES))
        for mutator in ("create_draft", "update_draft_section", "finalize_draft"):
            self.assertNotIn(mutator, names)
        self.assertIn("read_draft", names)

    def test_draft_enabled_shim_promotes_chat_to_drafting(self):
        """Legacy callers passing ``draft_enabled=True`` still get drafting."""
        reg = build_registry(
            channel=self.channel,
            mode=AgentSession.Mode.CHAT,
            draft_enabled=True,
        )
        names = self._names(reg)
        for tool in DRAFT_TOOL_NAMES:
            self.assertIn(tool, names)
