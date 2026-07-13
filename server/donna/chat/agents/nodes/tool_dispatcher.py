"""Tool dispatcher — execute each pending tool_call and append a tool message.

For each call: lookup → validate args (Pydantic) → **taint check** →
emit announce → run() with per-tool timeout → **taint-stamp the result
if from external content** → append as ``{role: tool, tool_call_id,
content}``. Validation/taint/timeout errors come back as tool messages
so the model can self-correct next round.

Announces go to the run-stream group ONLY — never into state.messages.
Two consecutive assistant turns in the message list breaks LiteLLM /
Anthropic format expectations (docupal trap).

**Taint flow (openfang pattern, 2026-06-14):** tools listed in
``EXTERNAL_CONTENT_TOOLS`` source data from outside trust boundaries
(emails, cortex bodies, webhooks). Their string output values get
marked tainted. Downstream tools that declare ``taint_safe=False``
get rejected if any tainted value flows into their args. Q&A read
tools are taint_safe=True (they READ content but never ACT on it
unsanitized); drafting tools opt into taint_safe=True explicitly and
own internal sanitization. Enforcement is wired now so the policy is
in place when A2 lands tools that would otherwise be exposed.
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from pydantic import ValidationError

from donna.chat.agents.hooks import HookContext, fire as fire_hook
from donna.chat.agents.state.builder import AgentState
from donna.chat.agents.nodes.tool_summary import summarize_tool_batch
from donna.chat.agents.tools.base import ToolContext, ToolResult
from donna.chat.agents.tools.registry import ToolRegistry
from donna.chat.services import agent_run_group


# Tools whose payload string leaves are marked tainted before
# downstream tools see them. Update when adding tools that pull data
# from outside trust boundaries.
EXTERNAL_CONTENT_TOOLS: set[str] = {
    "cortex_query",
    "read_entity",
    "get_context",
    "prepare_context",  # A2/A3
    "read_draft",       # A2
}


# Thin str subclass smuggling a flag — NewType("Tainted", str) is
# erased at runtime, so we attach the marker on a real subclass.
class _TaintedStr(str):
    _donna_tainted = True


def _is_tainted(value) -> bool:
    return isinstance(value, str) and getattr(value, "_donna_tainted", False)


def _mark_tainted(value: str) -> str:
    return _TaintedStr(value) if isinstance(value, str) else value


def _walk_and_taint(obj):
    """Recursively mark every string leaf in a payload as tainted."""
    if isinstance(obj, str):
        return _mark_tainted(obj)
    if isinstance(obj, list):
        return [_walk_and_taint(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _walk_and_taint(v) for k, v in obj.items()}
    return obj


def _has_tainted_leaf(obj) -> bool:
    """Return True if any string leaf in ``obj`` carries the taint flag."""
    if isinstance(obj, str):
        return _is_tainted(obj)
    if isinstance(obj, list):
        return any(_has_tainted_leaf(x) for x in obj)
    if isinstance(obj, dict):
        return any(_has_tainted_leaf(v) for v in obj.values())
    return False


# Cross-round taint persistence (2026-06-15) — minimum substring
# length to track. Below this we'd flood the set with stop-words.
_TAINTED_MIN_LEN = 12


def _collect_strings(obj, sink: set, min_len: int = _TAINTED_MIN_LEN) -> None:
    """Walk payload, harvest string leaves longer than ``min_len`` into ``sink``."""
    if isinstance(obj, str):
        if len(obj) >= min_len:
            sink.add(obj)
        return
    if isinstance(obj, list):
        for x in obj:
            _collect_strings(x, sink, min_len)
        return
    if isinstance(obj, dict):
        for v in obj.values():
            _collect_strings(v, sink, min_len)


def _args_carry_tainted(args_payload, tainted_strings: set) -> str | None:
    """Return the field name that contains a tainted substring, or None.

    Cross-round check: even if the LLM stripped the type marker by
    round-tripping the string, substring containment catches it.
    """
    if not tainted_strings:
        return None
    if isinstance(args_payload, dict):
        for field_name, value in args_payload.items():
            if _value_contains_tainted(value, tainted_strings):
                return field_name
    return None


def _value_contains_tainted(value, tainted_strings: set) -> bool:
    if isinstance(value, str):
        if value in tainted_strings:
            return True
        for t in tainted_strings:
            if len(t) >= _TAINTED_MIN_LEN and t in value:
                return True
        return False
    if isinstance(value, list):
        return any(_value_contains_tainted(v, tainted_strings) for v in value)
    if isinstance(value, dict):
        return any(_value_contains_tainted(v, tainted_strings) for v in value.values())
    return False


logger = logging.getLogger(__name__)


class ToolDispatcher:
    def __call__(
        self,
        state: AgentState,
        ctx: ToolContext,
        registry: ToolRegistry,
    ) -> AgentState:
        batch_tool_msgs: list[dict] = []
        for call in state.pending_tool_calls:
            tool_msg = self._dispatch_one(call, registry, ctx, state)
            state.messages.append(tool_msg)
            batch_tool_msgs.append(tool_msg)
        state.pending_tool_calls = []
        # Plan 13 §1.2 — Haiku one-line summary of the batch, broadcast
        # to the run group for the frontend chip. Best-effort.
        if batch_tool_msgs:
            _broadcast_tool_summary(state.run_id, batch_tool_msgs)
        return state

    def _dispatch_one(self, call, registry: ToolRegistry, ctx: ToolContext, state: AgentState) -> dict:
        run_id = state.run_id
        name = call.function.get("name") if isinstance(call.function, dict) else getattr(call.function, "name", "")
        arguments = call.function.get("arguments") if isinstance(call.function, dict) else getattr(call.function, "arguments", "{}")
        call_id = call.id

        if not registry.has(name):
            return _tool_message(call_id, {"error": "unknown_tool", "name": name})

        tool = registry.get(name)
        try:
            args = tool.args_model.model_validate_json(
                arguments if isinstance(arguments, str) else json.dumps(arguments)
            )
        except ValidationError as exc:
            return _tool_message(call_id, {
                "error": "args_validation_failed",
                "tool": name,
                "detail": exc.errors(),
            })

        if not tool.taint_safe:
            args_payload = args.model_dump()
            # In-pass marker check (covers payloads still inside this
            # dispatcher invocation — type marker intact).
            for field_name, value in args_payload.items():
                if _has_tainted_leaf(value):
                    return _tool_message(call_id, {
                        "error": "tainted_input_rejected",
                        "tool": name,
                        "field": field_name,
                        "hint": (
                            "This value came from external content "
                            "(cortex/email/webhook). Extract or summarize "
                            "into structured fields first, then call "
                            "this tool with the sanitized values."
                        ),
                    })
            # Cross-round substring check (2026-06-15) — survives the
            # LLM round-trip that strips the type marker.
            cross_round_field = _args_carry_tainted(args_payload, state.tainted_strings)
            if cross_round_field is not None:
                return _tool_message(call_id, {
                    "error": "tainted_input_rejected",
                    "tool": name,
                    "field": cross_round_field,
                    "hint": (
                        "Value matched content previously returned by an "
                        "external-source tool. Sanitize / extract fields "
                        "rather than passing the raw text through."
                    ),
                })

        _broadcast_announce(run_id, name, tool.announce(args))

        # Plan 13 §2.3 — pre_tool_use hook fire. Deny short-circuits;
        # mutated args are reflected on the in-pass dict, NOT round-tripped
        # back through the Pydantic model (the model already validated).
        args_payload_for_hook = args.model_dump()
        hook_ctx = HookContext(
            event="pre_tool_use",
            workspace=getattr(ctx, "workspace", None),
            session_id=str(getattr(getattr(ctx, "agent_session", None), "id", "")),
            channel_id=str(getattr(getattr(ctx, "channel", None), "id", "")) or None,
            tool_name=name,
            tool_args=args_payload_for_hook,
        )
        pre_result = fire_hook("pre_tool_use", hook_ctx)
        if not pre_result.allow:
            return _tool_message(call_id, {
                "error": "denied_by_hook",
                "tool": name,
                "reason": pre_result.deny_reason or "policy denial",
            })

        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(tool.run, args, ctx)
            try:
                result: ToolResult = fut.result(timeout=tool.timeout_s)
            except FutTimeout:
                logger.warning("tool_timeout", extra={"tool": name, "timeout_s": tool.timeout_s})
                return _tool_message(call_id, {
                    "error": "tool_timeout",
                    "tool": name,
                    "timeout_s": tool.timeout_s,
                    "hint": "Try a narrower query or break the request into smaller steps.",
                })
            except Exception as exc:  # noqa: BLE001
                logger.exception("tool_run_failed", extra={"tool": name})
                return _tool_message(call_id, {
                    "error": "tool_run_failed",
                    "tool": name,
                    "detail": str(exc),
                })

        if result.error:
            err_payload = {"error": result.error, "tool": name}
            # Hooks still observe the failure (audit log). Mutations on
            # the error result are intentionally ignored.
            hook_ctx.tool_result = err_payload
            hook_ctx.event = "post_tool_use"
            fire_hook("post_tool_use", hook_ctx)
            return _tool_message(call_id, err_payload)

        payload = result.payload
        if name in EXTERNAL_CONTENT_TOOLS:
            payload = _walk_and_taint(payload)
            # Persist tainted strings on state for cross-round checks.
            _collect_strings(payload, state.tainted_strings)

        # Plan 13 §2.3 — post_tool_use hook fire. Hooks can rewrite the
        # payload (PII redaction, normalization). Mutations apply once,
        # at the boundary.
        hook_ctx.tool_result = payload if isinstance(payload, dict) else {"_payload": payload}
        hook_ctx.event = "post_tool_use"
        post_result = fire_hook("post_tool_use", hook_ctx)
        if post_result.mutated_result is not None:
            payload = post_result.mutated_result
        return _tool_message(call_id, payload)


def _tool_message(tool_call_id: str, content) -> dict:
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": json.dumps(content, default=str),
    }


def _broadcast_announce(run_id: str, tool_name: str, announce: str) -> None:
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(
            agent_run_group(run_id),
            {
                "type": "agent.status",
                "payload": {"tool": tool_name, "announce": announce},
            },
        )
    except Exception:  # noqa: BLE001 — announce is best-effort
        logger.warning("agent_announce_broadcast_failed", extra={"tool": tool_name})


def _broadcast_tool_summary(run_id: str, tool_messages: list[dict]) -> None:
    """Plan 13 §1.2 — broadcast a one-line Haiku summary of the batch."""
    summary = summarize_tool_batch(tool_messages)
    if not summary:
        return
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(
            agent_run_group(run_id),
            {
                "type": "agent.tool_summary",
                "payload": {"summary": summary, "tool_count": len(tool_messages)},
            },
        )
    except Exception:  # noqa: BLE001 — summary is best-effort
        logger.warning("tool_summary_broadcast_failed")
