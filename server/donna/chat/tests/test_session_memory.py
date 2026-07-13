"""Plan 13 §4.1 + §4.4 — extractor + shard tests.

Extractor tests stub the LLM to avoid a real Anthropic call. Shard tests
verify the query shape — actual DB-backed integration relies on a live
Postgres and lives in ``test_memory_sharding`` (run separately).
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from donna.chat.agents.memory.extract import (
    EXTRACTOR_SYSTEM,
    _parse_notes,
    extract_session_memory,
)
from donna.chat.agents.memory.shard import render_memory_for_prompt


class _FakeLLM:
    def __init__(self, content="{}", raise_exc=None):
        self.content = content
        self.raise_exc = raise_exc

    def get_answer(self, *, prompt, system_prompt, **_):
        if self.raise_exc:
            raise self.raise_exc
        return SimpleNamespace(content=self.content)


class _Bulk:
    """Records bulk_create calls so we can assert on the shape without DB."""

    def __init__(self):
        self.last_batch = None

    def bulk_create(self, rows):
        self.last_batch = rows
        return rows


class _FakeRow(SimpleNamespace):
    """Stand-in for ``SessionMemory(...)`` — bypasses the FK descriptor
    that requires a real AgentSession instance. Captures kwargs verbatim
    so test assertions can read them back as attributes."""

    pass


class _StubScope:
    """Iterable enum stand-in mirroring ``SessionMemory.Scope.values``."""

    _values = ("user", "channel", "peer", "project", "org", "self")

    def __iter__(self):
        return iter(SimpleNamespace(value=v) for v in self._values)


class _StubModel:
    """Callable model substitute used to test ``extract_session_memory``
    without spinning up Postgres. Holds a ``_Bulk`` recorder under
    ``.objects`` so the production code's call site needs no change."""

    Scope = _StubScope()

    def __init__(self):
        self.objects = _Bulk()

    def __call__(self, **kwargs):
        return _FakeRow(**kwargs)


class ParseNotesTests(SimpleTestCase):
    def test_valid_notes_pass_through(self):
        out = _parse_notes({"notes": [
            {"scope": "user", "body": "user prefers terse replies"},
            {"scope": "project", "scope_ref": "p-1", "body": "Acme is on Q3"},
        ]})
        self.assertEqual(len(out), 2)

    def test_rejects_missing_body(self):
        out = _parse_notes({"notes": [{"scope": "user"}, {"body": "ok"}]})
        self.assertEqual(len(out), 1)

    def test_rejects_non_dict(self):
        self.assertEqual(_parse_notes(None), [])
        self.assertEqual(_parse_notes({}), [])
        self.assertEqual(_parse_notes({"notes": "not a list"}), [])


class ExtractSessionMemoryTests(SimpleTestCase):
    def test_llm_failure_returns_empty_list(self):
        stub = _StubModel()
        with patch("donna.chat.agents.memory.extract.SessionMemory", stub):
            out = extract_session_memory(
                session=SimpleNamespace(id="ag"),
                turn_id="t-1",
                transcript=[{"role": "user", "content": "hi"}],
                llm=_FakeLLM(raise_exc=RuntimeError("boom")),
            )
        self.assertEqual(out, [])
        self.assertIsNone(stub.objects.last_batch)

    def test_bad_json_returns_empty_list(self):
        stub = _StubModel()
        with patch("donna.chat.agents.memory.extract.SessionMemory", stub):
            out = extract_session_memory(
                session=SimpleNamespace(id="ag"),
                turn_id="t-1",
                transcript=[{"role": "user", "content": "hi"}],
                llm=_FakeLLM(content="not json"),
            )
        self.assertEqual(out, [])

    def test_strips_fenced_json(self):
        payload = {"notes": [{"scope": "self", "body": "use bullet points"}]}
        stub = _StubModel()
        fenced = "```json\n" + json.dumps(payload) + "\n```"
        with patch("donna.chat.agents.memory.extract.SessionMemory", stub):
            out = extract_session_memory(
                session=SimpleNamespace(id="ag"),
                turn_id="t-1",
                transcript=[{"role": "user", "content": "hi"}],
                llm=_FakeLLM(content=fenced),
            )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].scope, "self")

    def test_invalid_scope_defaults_to_user(self):
        payload = {"notes": [{"scope": "bogus", "body": "x"}]}
        stub = _StubModel()
        with patch("donna.chat.agents.memory.extract.SessionMemory", stub):
            out = extract_session_memory(
                session=SimpleNamespace(id="ag"),
                turn_id="t-1",
                transcript=[{"role": "user", "content": "hi"}],
                llm=_FakeLLM(content=json.dumps(payload)),
            )
        self.assertEqual(out[0].scope, "user")

    def test_confidence_clamped(self):
        payload = {"notes": [
            {"scope": "user", "body": "a", "confidence": 5.0},
            {"scope": "user", "body": "b", "confidence": -1.0},
            {"scope": "user", "body": "c", "confidence": "nope"},
        ]}
        stub = _StubModel()
        with patch("donna.chat.agents.memory.extract.SessionMemory", stub):
            out = extract_session_memory(
                session=SimpleNamespace(id="ag"),
                turn_id="t-1",
                transcript=[{"role": "user", "content": "hi"}],
                llm=_FakeLLM(content=json.dumps(payload)),
            )
        self.assertEqual(out[0].confidence, 1.0)
        self.assertEqual(out[1].confidence, 0.0)
        self.assertEqual(out[2].confidence, 0.7)

    def test_system_prompt_carries_constraints(self):
        # Cheap regression — the schema description must keep the
        # scope enumeration intact, or extractor output drifts.
        for token in ("user", "channel", "peer", "project", "org", "self"):
            self.assertIn(token, EXTRACTOR_SYSTEM)


class RenderMemoryForPromptTests(SimpleTestCase):
    def test_empty_returns_empty(self):
        self.assertEqual(render_memory_for_prompt([]), "")

    def test_groups_by_scope_and_scope_ref(self):
        rows = [
            SimpleNamespace(scope="user", scope_ref="u-1", body="prefers terse"),
            SimpleNamespace(scope="user", scope_ref="u-1", body="bullets ok"),
            SimpleNamespace(scope="project", scope_ref="p-acme", body="Q3 launch"),
        ]
        out = render_memory_for_prompt(rows)
        self.assertIn("== SCOPED MEMORY ==", out)
        self.assertIn("[user:u-1]", out)
        self.assertIn("[project:p-acme]", out)
        # All three bodies present.
        for txt in ("prefers terse", "bullets ok", "Q3 launch"):
            self.assertIn(txt, out)
