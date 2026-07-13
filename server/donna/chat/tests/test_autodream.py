"""Plan 13 §4.2 — AutoDream consolidator tests.

Validates grouping + consolidator failure handling without touching DB
or the Sonnet provider. Full end-to-end coverage lives in the integration
suite once Postgres is up.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from django.test import SimpleTestCase

from donna.chat.agents.memory.autodream import (
    CONSOLIDATOR_SYSTEM,
    _consolidate_group,
    _group_by_scope,
)


def _row(scope, scope_ref, body, ts=None, confidence=0.7):
    return SimpleNamespace(
        scope=scope, scope_ref=scope_ref, body=body,
        confidence=confidence,
        created_at=ts or datetime.now(tz=timezone.utc),
        session_id="ag",
        id="r",
    )


class _FakeLLM:
    def __init__(self, content=None, raise_exc=None):
        self.content = content
        self.raise_exc = raise_exc
        self.last_prompt = None

    def get_answer(self, *, prompt, system_prompt, **_):
        if self.raise_exc:
            raise self.raise_exc
        self.last_prompt = prompt
        return SimpleNamespace(content=self.content)


class GroupByScopeTests(SimpleTestCase):
    def test_groups_by_scope_and_scope_ref(self):
        rows = [
            _row("user", "u1", "a"),
            _row("user", "u1", "b"),
            _row("user", "u2", "c"),
            _row("project", "p1", "d"),
        ]
        groups = _group_by_scope(rows)
        self.assertEqual(len(groups), 3)
        self.assertEqual(len(groups[("user", "u1")]), 2)
        self.assertEqual(len(groups[("user", "u2")]), 1)
        self.assertEqual(len(groups[("project", "p1")]), 1)

    def test_empty_scope_ref_groups_separately_from_populated(self):
        groups = _group_by_scope([
            _row("self", "", "x"),
            _row("self", "", "y"),
        ])
        self.assertEqual(list(groups.keys()), [("self", "")])


class ConsolidateGroupTests(SimpleTestCase):
    def test_returns_none_on_empty(self):
        self.assertIsNone(_consolidate_group([], llm=_FakeLLM(content="ignored")))

    def test_returns_none_on_llm_failure(self):
        rows = [_row("user", "u1", "fact")]
        out = _consolidate_group(rows, llm=_FakeLLM(raise_exc=RuntimeError("boom")))
        self.assertIsNone(out)

    def test_returns_stripped_content(self):
        rows = [_row("user", "u1", "fact")]
        out = _consolidate_group(rows, llm=_FakeLLM(content="  Merged paragraph.  "))
        self.assertEqual(out, "Merged paragraph.")

    def test_orders_notes_chronologically_in_prompt(self):
        now = datetime.now(tz=timezone.utc)
        rows = [
            _row("user", "u1", "later note", ts=now),
            _row("user", "u1", "earlier note", ts=now - timedelta(hours=2)),
        ]
        llm = _FakeLLM(content="x")
        _consolidate_group(rows, llm=llm)
        i_earlier = llm.last_prompt.find("earlier note")
        i_later = llm.last_prompt.find("later note")
        self.assertLess(i_earlier, i_later, "later note should appear AFTER earlier")

    def test_system_prompt_constraints_present(self):
        for token in ("LATER", "≤ 250 words", "Drop trivia"):
            self.assertIn(token, CONSOLIDATOR_SYSTEM)
