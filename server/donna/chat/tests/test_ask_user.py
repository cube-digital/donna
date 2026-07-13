"""Plan 13 §1.3 + §1.5 — AskUserQuestion tool tests.

DB-free: stubs ``Message.objects.create`` via a recorder so the test
exercises the tool logic without a Postgres dependency. Integration
test against the live model lives in ``test_hil_multistep`` (DB).
"""
from __future__ import annotations

from types import SimpleNamespace
from datetime import timedelta
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from donna.chat.agents.tools.ask_user import (
    AskUserQuestionArgs,
    AskUserQuestionTool,
    DEFAULT_TTL,
    QuestionOption,
)
from donna.chat.agents.tools.base import ToolContext


class _Captured:
    """Minimal Message-row stub the tool's create() returns."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.id = "msg-1"
        self.expires_at = kwargs.get("expires_at", timezone.now())


class _Recorder:
    """Replaces ``Message.objects`` for the duration of a test."""

    def __init__(self):
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Captured(**kwargs)


def _ctx():
    return ToolContext(
        workspace=SimpleNamespace(id="ws"),
        user=SimpleNamespace(id="u"),
        channel=SimpleNamespace(id="ch"),
        agent_session=SimpleNamespace(id="ag"),
    )


class AskUserQuestionToolTests(SimpleTestCase):
    def test_creates_question_kind_message_and_returns_id(self):
        rec = _Recorder()
        with patch("donna.chat.models.Message.objects", rec):
            tool = AskUserQuestionTool()
            args = AskUserQuestionArgs(
                prompt="Send to Alice now or wait for review?",
                options=[
                    QuestionOption(label="Send now", value="now"),
                    QuestionOption(label="Wait", value="wait"),
                ],
            )
            result = tool.run(args, _ctx())
            self.assertIsNone(result.error)
            self.assertEqual(result.payload["status"], "awaiting_user")
            self.assertIn("question_id", result.payload)

        self.assertEqual(len(rec.calls), 1)
        call = rec.calls[0]
        self.assertEqual(call["kind"], "question")
        self.assertEqual(call["body"], "Send to Alice now or wait for review?")
        self.assertEqual(len(call["question_options"]), 2)
        self.assertEqual(call["question_options"][0]["value"], "now")

    def test_default_ttl_applied(self):
        rec = _Recorder()
        with patch("donna.chat.models.Message.objects", rec):
            tool = AskUserQuestionTool()
            args = AskUserQuestionArgs(prompt="ok?", options=[])
            before = timezone.now()
            tool.run(args, _ctx())
            after = timezone.now()
        expiry = rec.calls[0]["expires_at"]
        self.assertGreaterEqual(expiry, before + DEFAULT_TTL - timedelta(seconds=2))
        self.assertLessEqual(expiry, after + DEFAULT_TTL + timedelta(seconds=2))

    def test_custom_expires_in_minutes_overrides(self):
        rec = _Recorder()
        with patch("donna.chat.models.Message.objects", rec):
            tool = AskUserQuestionTool()
            args = AskUserQuestionArgs(
                prompt="ok?", options=[], expires_in_minutes=30,
            )
            before = timezone.now()
            tool.run(args, _ctx())
        expiry = rec.calls[0]["expires_at"]
        delta = expiry - before
        self.assertGreaterEqual(delta, timedelta(minutes=29, seconds=58))
        self.assertLessEqual(delta, timedelta(minutes=30, seconds=2))

    def test_announce_is_user_visible(self):
        tool = AskUserQuestionTool()
        args = AskUserQuestionArgs(prompt="x?", options=[])
        # announce() drives the WS chip; should mention waiting for the
        # user explicitly (not just "Running…").
        self.assertIn("answer", tool.announce(args).lower())
