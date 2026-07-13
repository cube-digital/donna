"""build_registry — per-turn tool registry construction.

Builds a fresh per-turn registry by SUBSETTING the frozen
``GLOBAL_REGISTRY`` (populated at chat app boot) according to channel
+ session mode. Per-turn registries are short-lived and intentionally
unfrozen; the global one is locked.

Plan 13 §2.1 — mode-gated registry:

- ``chat``     → Q&A tools only (cortex reads).
- ``drafting`` → Q&A + draft mutations. Equivalent to the legacy
                 ``draft_enabled=True`` path.
- ``planning`` → read-only rehearsal. Q&A + read_draft, no
                 mutations. The agent produces a proposed plan
                 the user approves before any write hits.

``draft_enabled`` legacy kwarg kept as a compat shim — pass it and
the resolver picks ``drafting`` mode.
"""
from __future__ import annotations

from donna.chat.models import AgentSession, Channel

from .registry import GLOBAL_REGISTRY, ToolRegistry


# Q&A tools available in every channel. ``prepare_context`` is the
# fan-out macro added 2026-06-14 — agent calls it first on new topics.
# ``ask_user_question`` is Plan 13 §1.3 — universal HIL primitive,
# available in every mode (planning relies on it heavily).
QA_TOOL_NAMES: tuple[str, ...] = (
    "cortex_query",
    "read_entity",
    "get_context",
    "prepare_context",
    "ask_user_question",
    "agent",
)

# Draft tools added in drafting mode. A2 (2026-06-20).
DRAFT_TOOL_NAMES: tuple[str, ...] = (
    "create_draft",
    "read_draft",
    "update_draft_section",
    "finalize_draft",
)

# Planning mode: read-only — Q&A + read_draft, but NO mutations.
# The drafter is allowed to look at existing drafts, just can't
# create / update / finalize until the user exits planning mode.
PLANNING_TOOL_NAMES: tuple[str, ...] = (
    *QA_TOOL_NAMES,
    "read_draft",
)


def build_registry(
    *,
    channel: Channel,
    mode: str = AgentSession.Mode.CHAT,
    draft_enabled: bool | None = None,
) -> ToolRegistry:
    """Construct a per-turn registry.

    Pass ``mode`` from ``AgentSession.mode`` (preferred). For backwards
    compatibility with callers that still pass ``draft_enabled``, that
    kwarg promotes to ``mode='drafting'``.
    """
    if draft_enabled is True:
        mode = AgentSession.Mode.DRAFTING

    if mode == AgentSession.Mode.PLANNING:
        wanted = list(PLANNING_TOOL_NAMES)
    elif mode == AgentSession.Mode.DRAFTING:
        wanted = [*QA_TOOL_NAMES, *DRAFT_TOOL_NAMES]
    else:  # CHAT (default)
        wanted = list(QA_TOOL_NAMES)
    return GLOBAL_REGISTRY.subset(wanted)


def register_qa_tools() -> None:
    """Register the cortex_read tool set on GLOBAL_REGISTRY.

    Called from ``donna.chat.apps.ChatConfig.ready()`` BEFORE freeze().
    Kept here so the catalog lives next to the factory.
    """
    from .agent_tool import AgentTool
    from .ask_user import AskUserQuestionTool
    from .cortex_read import CortexQueryTool, GetContextTool, ReadEntityTool

    if GLOBAL_REGISTRY.frozen:
        return  # idempotent: ready() may fire twice in tests
    if not GLOBAL_REGISTRY.has("cortex_query"):
        from .cortex_read import PrepareContextTool

        GLOBAL_REGISTRY.register(
            CortexQueryTool(),
            ReadEntityTool(),
            GetContextTool(),
            PrepareContextTool(),
            AskUserQuestionTool(),
            AgentTool(),
        )


def register_draft_tools() -> None:
    """Register A2 draft tools on GLOBAL_REGISTRY.

    Called from ``donna.chat.apps.ChatConfig.ready()`` after
    ``register_qa_tools`` and BEFORE ``freeze()``. Channel-level
    gating happens in ``build_registry(draft_enabled=...)``.
    """
    from .draft_tools import (
        CreateDraftTool,
        FinalizeDraftTool,
        ReadDraftTool,
        UpdateDraftSectionTool,
    )

    if GLOBAL_REGISTRY.frozen:
        return
    if not GLOBAL_REGISTRY.has("create_draft"):
        GLOBAL_REGISTRY.register(
            CreateDraftTool(),
            ReadDraftTool(),
            UpdateDraftSectionTool(),
            FinalizeDraftTool(),
        )
