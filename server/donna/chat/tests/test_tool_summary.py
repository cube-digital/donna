"""Plan 13 §1.2 — Haiku tool-summary node tests.

Verifies the summariser shapes tool messages correctly, swallows LLM
failures without raising, and returns ``None`` on empty/all-error
batches when configured to.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from django.test import SimpleTestCase

from donna.chat.agents.nodes.tool_summary import (
    _shape_for_summary,
    summarize_tool_batch,
)


class _FakeLLM:
    def __init__(self, *, content="Searched cortex; found 3 entities.", raise_exc=None):
        self.content = content
        self.raise_exc = raise_exc
        self.last_prompt = None
        self.last_system = None

    def get_answer(self, *, prompt, system_prompt, **_):
        if self.raise_exc:
            raise self.raise_exc
        self.last_prompt = prompt
        self.last_system = system_prompt
        return SimpleNamespace(content=self.content)


class ShapeForSummaryTests(SimpleTestCase):
    def test_drops_non_tool_messages(self):
        msgs = [
            {"role": "assistant", "content": "hi"},
            {"role": "tool", "tool_call_id": "1", "content": json.dumps({"x": 1})},
        ]
        shaped = _shape_for_summary(msgs)
        self.assertEqual(len(shaped), 1)

    def test_marks_error_payloads(self):
        msgs = [{
            "role": "tool", "tool_call_id": "1",
            "content": json.dumps({"error": "tool_timeout", "tool": "cortex_query"}),
        }]
        shaped = _shape_for_summary(msgs)
        self.assertEqual(shaped[0]["ok"], False)
        self.assertEqual(shaped[0]["headline"], "tool_timeout")
        self.assertEqual(shaped[0]["name"], "cortex_query")

    def test_truncates_huge_payloads(self):
        big = {"x": "a" * 5000}
        msgs = [{"role": "tool", "tool_call_id": "1", "content": json.dumps(big)}]
        shaped = _shape_for_summary(msgs)
        self.assertLessEqual(len(shaped[0]["headline"]), 280)

    def test_handles_invalid_json(self):
        msgs = [{"role": "tool", "tool_call_id": "1", "content": "not-json"}]
        shaped = _shape_for_summary(msgs)
        # Stays well-formed; doesn't raise.
        self.assertEqual(len(shaped), 1)


class SummarizeToolBatchTests(SimpleTestCase):
    def test_empty_returns_none(self):
        self.assertIsNone(summarize_tool_batch([]))

    def test_returns_first_line_stripped(self):
        llm = _FakeLLM(content='"Searched cortex; found 3 entities."\nignored second line')
        out = summarize_tool_batch(
            [{"role": "tool", "tool_call_id": "1", "content": "{}"}],
            llm=llm,
        )
        self.assertEqual(out, "Searched cortex; found 3 entities.")

    def test_llm_failure_returns_none_silently(self):
        llm = _FakeLLM(raise_exc=RuntimeError("api down"))
        out = summarize_tool_batch(
            [{"role": "tool", "tool_call_id": "1", "content": "{}"}],
            llm=llm,
        )
        self.assertIsNone(out)

    def test_empty_content_returns_none(self):
        llm = _FakeLLM(content="   ")
        out = summarize_tool_batch(
            [{"role": "tool", "tool_call_id": "1", "content": "{}"}],
            llm=llm,
        )
        self.assertIsNone(out)

    def test_system_prompt_constraints_present(self):
        llm = _FakeLLM()
        summarize_tool_batch(
            [{"role": "tool", "tool_call_id": "1", "content": json.dumps({"x": 1})}],
            llm=llm,
        )
        self.assertIn("ONE sentence", llm.last_system)
        self.assertIn("≤ 22 words", llm.last_system)
