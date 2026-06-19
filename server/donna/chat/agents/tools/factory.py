"""build_registry — per-turn tool registry construction.

Builds a fresh per-turn registry by SUBSETTING the frozen
``GLOBAL_REGISTRY`` (populated at chat app boot) according to channel
+ draft policy. Per-turn registries are short-lived and intentionally
unfrozen; the global one is locked.

Q&A slice (now): three cortex_read tools always available.
A2 (later): draft tools added when ``draft_enabled``.
"""
from __future__ import annotations

from donna.chat.models import Channel

from .registry import GLOBAL_REGISTRY, ToolRegistry


# Q&A tools available in every channel. ``prepare_context`` is the
# fan-out macro added 2026-06-14 — agent calls it first on new topics.
QA_TOOL_NAMES: tuple[str, ...] = (
    "cortex_query",
    "read_entity",
    "get_context",
    "prepare_context",
)

# Draft tools added when draft_enabled. Populated in A2.
DRAFT_TOOL_NAMES: tuple[str, ...] = ()


def build_registry(*, channel: Channel, draft_enabled: bool = False) -> ToolRegistry:
    wanted: list[str] = list(QA_TOOL_NAMES)
    if draft_enabled:
        wanted.extend(DRAFT_TOOL_NAMES)
    return GLOBAL_REGISTRY.subset(wanted)


def register_qa_tools() -> None:
    """Register the cortex_read tool set on GLOBAL_REGISTRY.

    Called from ``donna.chat.apps.ChatConfig.ready()`` BEFORE freeze().
    Kept here so the catalog lives next to the factory.
    """
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
        )
