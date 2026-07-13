"""Plan 13 §2.3 — hook registry.

Workspace-global extension points fired by the agent loop. Hooks are
pure-Python callables registered at startup (via ``apps.ready()``) or
loaded from per-workspace rows (future). The dispatcher fires
``pre_tool_use`` / ``post_tool_use``; the runner fires
``session_start``; the AgentTool fires ``subagent_stop`` (Plan 13 §5).

Hooks can:
- DENY a tool call (``pre_tool_use`` → ``HookResult(allow=False)``).
- REWRITE arguments before execution.
- REWRITE the result after execution (PII redaction, normalization).
- Record SIDE EFFECTS that flow into the audit log.

First deny wins. Mutations accumulate across hooks; later hooks see the
upstream rewrites in their ``ctx``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal

HookEvent = Literal[
    "pre_tool_use",
    "post_tool_use",
    "session_start",
    "subagent_stop",
]

# All valid event names — kept in sync with the Literal above so callers
# can iterate without importing typing.get_args().
ALL_EVENTS: tuple[HookEvent, ...] = (
    "pre_tool_use",
    "post_tool_use",
    "session_start",
    "subagent_stop",
)


@dataclass
class HookContext:
    """What every hook receives. Mutable so hooks can mutate ``tool_args``
    / ``tool_result`` for downstream hooks in the same fire."""

    event: HookEvent
    workspace: Any
    session_id: str
    channel_id: str | None
    tool_name: str | None = None         # pre_tool_use, post_tool_use
    tool_args: dict | None = None
    tool_result: dict | None = None      # post_tool_use only
    subagent_id: str | None = None       # subagent_stop only
    subagent_transcript: list | None = None
    # Free-form bag for hooks that need to communicate side data into
    # downstream pipeline stages without bloating the dataclass.
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class HookResult:
    """Returned by every hook. Defaults to allow + no mutation."""

    allow: bool = True
    deny_reason: str | None = None
    mutated_args: dict | None = None      # pre_tool_use
    mutated_result: dict | None = None    # post_tool_use
    # Informational entries surfaced in the audit log even when the hook
    # otherwise allows + does not mutate.
    side_effects: tuple[str, ...] = ()


# Per-event registry. Lists preserve registration order, which is the
# fire order. The hook dispatcher in ``fire()`` short-circuits on the
# first deny.
_REGISTRY: dict[HookEvent, list[Callable[[HookContext], HookResult]]] = {
    e: [] for e in ALL_EVENTS
}


def register(event: HookEvent, hook: Callable[[HookContext], HookResult]) -> None:
    """Register a hook for ``event``. Idempotent: re-registering the same
    callable is a no-op (apps.ready() can fire twice in tests)."""
    if hook in _REGISTRY[event]:
        return
    _REGISTRY[event].append(hook)


def fire(event: HookEvent, ctx: HookContext) -> HookResult:
    """Fire every hook for ``event`` in registration order.

    Mutations propagate: each hook sees the prior hooks' rewrites on
    ``ctx``. The aggregated ``HookResult`` carries the final state so the
    dispatcher can apply mutations once at the boundary.
    """
    final = HookResult()
    accumulated_side_effects: list[str] = []
    for hook in _REGISTRY[event]:
        r = hook(ctx)
        if not r.allow:
            return HookResult(
                allow=False,
                deny_reason=r.deny_reason,
                side_effects=tuple(accumulated_side_effects) + tuple(r.side_effects),
            )
        if r.mutated_args is not None:
            ctx.tool_args = r.mutated_args
            final = HookResult(
                allow=True,
                mutated_args=r.mutated_args,
                mutated_result=final.mutated_result,
                side_effects=final.side_effects,
            )
        if r.mutated_result is not None:
            ctx.tool_result = r.mutated_result
            final = HookResult(
                allow=True,
                mutated_args=final.mutated_args,
                mutated_result=r.mutated_result,
                side_effects=final.side_effects,
            )
        accumulated_side_effects.extend(r.side_effects)
    return HookResult(
        allow=True,
        mutated_args=final.mutated_args,
        mutated_result=final.mutated_result,
        side_effects=tuple(accumulated_side_effects),
    )


def installed(event: HookEvent) -> Iterable[Callable[[HookContext], HookResult]]:
    """Return the registered hooks for ``event`` — read-only view."""
    return tuple(_REGISTRY[event])


def clear() -> None:
    """Test helper — wipe every event's registry. Never call in prod."""
    for e in ALL_EVENTS:
        _REGISTRY[e].clear()
