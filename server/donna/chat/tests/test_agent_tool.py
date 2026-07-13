"""Plan 13 §5.1 — AgentTool spawn tests."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from donna.chat.agents.tools.agent_tool import (
    AgentTool,
    AgentToolArgs,
    run_subagent_sync,
)
from donna.chat.agents.tools.base import ToolContext


class _FakeLLMProvider:
    def __init__(self, content="planned 3 steps"):
        self.content = content
        self.last_system = None

    def get_answer(self, *, prompt, system_prompt, **_):
        self.last_system = system_prompt
        return SimpleNamespace(content=self.content)


class _FakeFactory:
    def __init__(self, provider):
        self.provider = provider

    def create(self, model):
        return self.provider


def _ctx():
    return ToolContext(
        workspace=SimpleNamespace(id="ws"),
        user=SimpleNamespace(id="u"),
        channel=SimpleNamespace(id="ch"),
        agent_session=SimpleNamespace(id="ag"),
    )


class AgentToolValidationTests(SimpleTestCase):
    def test_unknown_subagent_returns_error(self):
        tool = AgentTool()
        out = tool.run(
            AgentToolArgs(subagent_type="not-a-real-one", prompt="x"),
            _ctx(),
        )
        self.assertIsNotNone(out.error)
        self.assertIn("Unknown subagent_type", out.error)

    def test_mailbox_mode_rejected(self):
        tool = AgentTool()
        out = tool.run(
            AgentToolArgs(subagent_type="planner", prompt="x", name="planner-1"),
            _ctx(),
        )
        self.assertIsNotNone(out.error)
        self.assertIn("mailbox", out.error.lower())

    def test_known_subagents_listed_in_description(self):
        """Description must enumerate available subagents so the LLM
        chooses sensibly. Regression guard against silent removals."""
        tool = AgentTool()
        schema = tool.describe()
        prop = schema["function"]["parameters"]["properties"]["subagent_type"]
        for name in ("planner", "drafter", "summarizer", "verifier"):
            self.assertIn(name, prop["description"])


class SubagentSyncTests(SimpleTestCase):
    def test_sync_returns_text(self):
        from donna.chat.agents.subagents import resolve

        provider = _FakeLLMProvider(content="step 1...\nstep 2...")
        factory = _FakeFactory(provider)
        out = run_subagent_sync(
            defn=resolve("planner"),
            prompt="Plan a launch",
            parent_ctx=_ctx(),
            llm_factory=factory,
        )
        self.assertEqual(out["text"], "step 1...\nstep 2...")
        self.assertEqual(out["rounds"], 1)
        self.assertNotIn("error", out)

    def test_sync_swallows_llm_failure(self):
        from donna.chat.agents.subagents import resolve

        class _Boom:
            def create(self, model):
                class _P:
                    def get_answer(self, **__):
                        raise RuntimeError("api down")
                return _P()

        out = run_subagent_sync(
            defn=resolve("planner"),
            prompt="x",
            parent_ctx=_ctx(),
            llm_factory=_Boom(),
        )
        self.assertIn("error", out)
        self.assertEqual(out["text"], "")

    def test_sync_uses_def_system_prompt(self):
        from donna.chat.agents.subagents import resolve

        provider = _FakeLLMProvider()
        factory = _FakeFactory(provider)
        run_subagent_sync(
            defn=resolve("verifier"),
            prompt="claim",
            parent_ctx=_ctx(),
            llm_factory=factory,
        )
        self.assertIn("SKEPTIC", provider.last_system)
