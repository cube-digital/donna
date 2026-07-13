"""Plan 13 §2.3 — hook registry behavior tests."""
from __future__ import annotations

from types import SimpleNamespace

from django.test import SimpleTestCase

from donna.chat.agents.hooks import (
    HookContext,
    HookResult,
    clear,
    fire,
    installed,
    register,
)


def _ctx(event="pre_tool_use", **kw):
    base = dict(
        event=event,
        workspace=SimpleNamespace(id="ws"),
        session_id="ag",
        channel_id="ch",
        tool_name="cortex_query",
        tool_args={"q": "Acme"},
    )
    base.update(kw)
    return HookContext(**base)


class HookRegistryTests(SimpleTestCase):
    def setUp(self):
        clear()

    def tearDown(self):
        clear()

    def test_no_hooks_returns_allow(self):
        result = fire("pre_tool_use", _ctx())
        self.assertTrue(result.allow)
        self.assertIsNone(result.mutated_args)

    def test_first_deny_short_circuits(self):
        calls: list[str] = []

        def first(ctx):
            calls.append("first")
            return HookResult(allow=False, deny_reason="forbidden")

        def second(ctx):
            calls.append("second")
            return HookResult()

        register("pre_tool_use", first)
        register("pre_tool_use", second)

        result = fire("pre_tool_use", _ctx())
        self.assertFalse(result.allow)
        self.assertEqual(result.deny_reason, "forbidden")
        self.assertEqual(calls, ["first"])  # second never ran

    def test_args_mutation_propagates(self):
        def redact(ctx):
            new = dict(ctx.tool_args)
            new["q"] = "[redacted]"
            return HookResult(mutated_args=new)

        def observer(ctx):
            # Sees the redacted args, not the original.
            return HookResult(side_effects=(f"saw:{ctx.tool_args['q']}",))

        register("pre_tool_use", redact)
        register("pre_tool_use", observer)
        result = fire("pre_tool_use", _ctx())
        self.assertEqual(result.mutated_args, {"q": "[redacted]"})
        self.assertIn("saw:[redacted]", result.side_effects)

    def test_result_mutation_propagates(self):
        def rewrite(ctx):
            return HookResult(mutated_result={"clean": True})

        register("post_tool_use", rewrite)
        result = fire(
            "post_tool_use",
            _ctx(event="post_tool_use", tool_result={"raw": "data"}),
        )
        self.assertEqual(result.mutated_result, {"clean": True})

    def test_register_is_idempotent(self):
        def hook(ctx):
            return HookResult()

        register("pre_tool_use", hook)
        register("pre_tool_use", hook)
        self.assertEqual(len(tuple(installed("pre_tool_use"))), 1)

    def test_all_four_events_are_independent(self):
        for event in (
            "pre_tool_use", "post_tool_use", "session_start", "subagent_stop",
        ):
            def make(ev):
                def hook(ctx):
                    return HookResult(side_effects=(f"fired:{ev}",))
                return hook
            register(event, make(event))

        for event in (
            "pre_tool_use", "post_tool_use", "session_start", "subagent_stop",
        ):
            result = fire(event, _ctx(event=event))
            self.assertEqual(result.side_effects, (f"fired:{event}",))
