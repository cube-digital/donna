"""A1 agent runtime tests.

Mostly pure-Python where possible; the dispatch-rule + lock checks
need Django + Redis. We mark the latter and skip when redis is not
reachable so the suite runs offline too.
"""
from __future__ import annotations

import json
import unittest
import uuid
from types import SimpleNamespace

from pydantic import BaseModel

from donna.chat.agents.nodes.tool_dispatcher import (
    EXTERNAL_CONTENT_TOOLS,
    ToolDispatcher,
    _has_tainted_leaf,
    _mark_tainted,
    _walk_and_taint,
)
from donna.chat.agents.tools.base import DonnaTool, ToolContext, ToolResult
from donna.chat.agents.tools.registry import (
    GLOBAL_REGISTRY,
    RegistryFrozenError,
    ToolRegistry,
)


# ── helpers ─────────────────────────────────────────────────────────


class _EchoArgs(BaseModel):
    msg: str


class _EchoTool(DonnaTool):
    name = "echo"
    description = "echo back"
    args_model = _EchoArgs

    def run(self, args: _EchoArgs, ctx: ToolContext) -> ToolResult:
        return ToolResult(payload={"echo": args.msg})


class _SlowArgs(BaseModel):
    secs: float = 1.0


class _SlowTool(DonnaTool):
    name = "slow"
    description = "sleeps"
    args_model = _SlowArgs
    timeout_s = 1  # 1s wall-clock for the test

    def run(self, args: _SlowArgs, ctx: ToolContext) -> ToolResult:
        import time
        time.sleep(args.secs)
        return ToolResult(payload={"ok": True})


def _fake_call(name: str, arguments_json: str, call_id: str = "c1"):
    return SimpleNamespace(
        id=call_id,
        function={"name": name, "arguments": arguments_json},
    )


def _ctx_stub():
    return ToolContext(
        workspace=SimpleNamespace(id=uuid.uuid4()),
        user=None,
        channel=SimpleNamespace(id=uuid.uuid4()),
        agent_session=SimpleNamespace(id=uuid.uuid4(), name="Donna", memory={}),
    )


# ── registry ────────────────────────────────────────────────────────


class ToolRegistryTests(unittest.TestCase):
    def test_duplicate_name_rejected(self) -> None:
        reg = ToolRegistry()
        reg.register(_EchoTool())
        with self.assertRaises(ValueError):
            reg.register(_EchoTool())

    def test_freeze_blocks_further_registration(self) -> None:
        reg = ToolRegistry()
        reg.register(_EchoTool())
        reg.freeze()
        with self.assertRaises(RegistryFrozenError):
            reg.register(_SlowTool())

    def test_subset_returns_unfrozen_filtered_registry(self) -> None:
        reg = ToolRegistry()
        reg.register(_EchoTool(), _SlowTool())
        reg.freeze()
        sub = reg.subset(["echo"])
        self.assertTrue(sub.has("echo"))
        self.assertFalse(sub.has("slow"))
        # Subset is NOT frozen — per-turn registries get rebuilt each turn.
        self.assertFalse(sub.frozen)

    def test_describe_all_emits_openai_schema(self) -> None:
        reg = ToolRegistry()
        reg.register(_EchoTool())
        schemas = reg.describe_all()
        self.assertEqual(len(schemas), 1)
        self.assertEqual(schemas[0]["type"], "function")
        self.assertEqual(schemas[0]["function"]["name"], "echo")

    def test_global_registry_is_frozen_post_boot(self) -> None:
        # ChatConfig.ready() freezes the global registry. The Django
        # AppConfig fires at import time during tests too.
        self.assertTrue(GLOBAL_REGISTRY.frozen)


# ── dispatcher ──────────────────────────────────────────────────────


class ToolDispatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reg = ToolRegistry()
        self.reg.register(_EchoTool(), _SlowTool())
        self.disp = ToolDispatcher()

    def test_validation_error_returns_tool_message_not_raise(self) -> None:
        # Malformed JSON for args_model → validation error path.
        call = _fake_call("echo", arguments_json="{not json}")
        state = SimpleNamespace(pending_tool_calls=[call], messages=[], run_id="r1")
        self.disp(state, _ctx_stub(), self.reg)
        self.assertEqual(len(state.messages), 1)
        content = json.loads(state.messages[0]["content"])
        self.assertEqual(content.get("error"), "args_validation_failed")

    def test_unknown_tool_returns_tool_message(self) -> None:
        call = _fake_call("ghost", arguments_json="{}")
        state = SimpleNamespace(pending_tool_calls=[call], messages=[], run_id="r2")
        self.disp(state, _ctx_stub(), self.reg)
        content = json.loads(state.messages[0]["content"])
        self.assertEqual(content.get("error"), "unknown_tool")

    def test_timeout_returns_tool_message(self) -> None:
        # _SlowTool sleeps secs; timeout_s=1. Sleep 3 → exceeds, returns
        # tool_timeout (not raise).
        call = _fake_call("slow", arguments_json=json.dumps({"secs": 3}))
        state = SimpleNamespace(pending_tool_calls=[call], messages=[], run_id="r3")
        self.disp(state, _ctx_stub(), self.reg)
        content = json.loads(state.messages[0]["content"])
        self.assertEqual(content.get("error"), "tool_timeout")

    def test_successful_run_returns_payload(self) -> None:
        call = _fake_call("echo", arguments_json=json.dumps({"msg": "hi"}))
        state = SimpleNamespace(pending_tool_calls=[call], messages=[], run_id="r4")
        self.disp(state, _ctx_stub(), self.reg)
        content = json.loads(state.messages[0]["content"])
        self.assertEqual(content, {"echo": "hi"})


# ── taint marker helpers ────────────────────────────────────────────


class TaintFlowTests(unittest.TestCase):
    def test_mark_and_walk(self) -> None:
        payload = {"title": "T", "snippets": ["a", "b"], "n": 3}
        tainted = _walk_and_taint(payload)
        self.assertTrue(_has_tainted_leaf(tainted["title"]))
        self.assertTrue(_has_tainted_leaf(tainted["snippets"]))
        self.assertFalse(_has_tainted_leaf(tainted["n"]))  # int leaves untouched

    def test_clean_payload_has_no_tainted_leaf(self) -> None:
        self.assertFalse(_has_tainted_leaf({"a": "x", "b": ["y"]}))

    def test_external_content_tools_set_includes_cortex_query(self) -> None:
        # Smoke — keep the safety net in place.
        for name in ("cortex_query", "read_entity", "get_context"):
            self.assertIn(name, EXTERNAL_CONTENT_TOOLS)


# ── lock (Redis-bound) ──────────────────────────────────────────────


class TurnLockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Skip if redis is not reachable. Lock requires the live broker.
        try:
            from donna.core.cache.redis_cache import redis_manager
            redis_manager.get_sync_client().ping()
            cls._skip = False
        except Exception:
            cls._skip = True

    def setUp(self) -> None:
        if self._skip:
            self.skipTest("redis unreachable — skipping lock tests")

    def test_second_acquire_raises_turn_busy(self) -> None:
        from donna.chat.agents.locks import TurnBusy, turn_lock

        channel_id = f"test-{uuid.uuid4()}"
        with turn_lock(channel_id, timeout=10):
            with self.assertRaises(TurnBusy):
                with turn_lock(channel_id, timeout=10):
                    pass


# ── dispatch hook (DM-always / mention rule) ────────────────────────


class DispatchRulesTests(unittest.TestCase):
    """Pure rule check on ``_mentioned`` + anti-loop."""

    def test_mention_match_case_insensitive(self) -> None:
        from donna.chat.tasks import _mentioned
        self.assertTrue(_mentioned("hey @donna what's up", "Donna"))
        self.assertTrue(_mentioned("HEY @DONNA", "Donna"))
        self.assertFalse(_mentioned("hello world", "Donna"))

    def test_anti_loop_skips_agent_authored_message(self) -> None:
        from donna.chat.tasks import maybe_dispatch_agent

        # author_agent set → must NOT dispatch (would infinite-loop).
        agent_msg = SimpleNamespace(
            author_agent_id=uuid.uuid4(),
            channel=SimpleNamespace(
                kind="direct",
                agent_sessions=SimpleNamespace(first=lambda: SimpleNamespace(name="Donna")),
            ),
            channel_id=uuid.uuid4(),
            id=uuid.uuid4(),
            body="anything",
        )
        # Should return without raising; no Celery delay called (the
        # function checks author_agent_id FIRST and returns early).
        maybe_dispatch_agent(agent_msg)


if __name__ == "__main__":
    unittest.main()
