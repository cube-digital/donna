"""Plan 13 §6.1 — DRAFT_STATUS updater tests.

DB-free: stubs Artifact + the Haiku provider so we test the orchestration
without spinning up Postgres or hitting Anthropic.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from donna.chat.agents.magicdocs.draft_status_updater import (
    STATUS_SYSTEM,
    _build_prompt,
    _haiku_status_for,
)


class _FakeLLM:
    def __init__(self, content=None, raise_exc=None):
        self.content = content
        self.raise_exc = raise_exc
        self.last_system = None
        self.last_prompt = None

    def get_answer(self, *, prompt, system_prompt, **_):
        if self.raise_exc:
            raise self.raise_exc
        self.last_system = system_prompt
        self.last_prompt = prompt
        return SimpleNamespace(content=self.content)


class StatusPromptTests(SimpleTestCase):
    def test_prompt_includes_title_doctype_version_body(self):
        draft = SimpleNamespace(
            title="Acme MSA",
            target_doc_type="contract",
            version=3,
            body="# Acme MSA\n\nDraft body here.",
        )
        prompt = _build_prompt(draft)
        self.assertIn("Acme MSA", prompt)
        self.assertIn("contract", prompt)
        self.assertIn("v3", prompt)
        self.assertIn("Draft body here.", prompt)

    def test_prompt_truncates_huge_body(self):
        # Body excerpt is unique-content so we can grep the slice
        # boundary without colliding with the template's own characters.
        body = "Z" * 10_000
        draft = SimpleNamespace(
            title="x",
            target_doc_type="",
            version=1,
            body=body,
        )
        prompt = _build_prompt(draft)
        # 3000-char excerpt cap from _build_prompt.
        self.assertEqual(prompt.count("Z"), 3000)

    def test_system_prompt_constrains_format(self):
        for token in ("≤ 6 bullets", "Done", "In progress", "Open"):
            self.assertIn(token, STATUS_SYSTEM)


class HaikuStatusForTests(SimpleTestCase):
    def _draft(self):
        return SimpleNamespace(
            id="d-1", title="x", target_doc_type="", version=1, body="hi",
        )

    def test_returns_stripped_content(self):
        out = _haiku_status_for(self._draft(), llm=_FakeLLM(content="  - **Done**\n  "))
        self.assertEqual(out, "- **Done**")

    def test_swallows_llm_failure(self):
        self.assertIsNone(
            _haiku_status_for(self._draft(), llm=_FakeLLM(raise_exc=RuntimeError("x"))),
        )

    def test_empty_content_returns_none(self):
        self.assertIsNone(_haiku_status_for(self._draft(), llm=_FakeLLM(content="   ")))
