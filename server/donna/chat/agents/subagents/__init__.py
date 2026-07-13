"""Plan 13 §5.1 — bundled subagent definitions.

A subagent is a focused worker the parent agent can spawn for a single
sub-task. Definitions are dataclass entries: a system prompt, an allowed
tool subset (subset of the parent's registry), a model preference, and a
max-rounds cap so a misbehaving spawn can't burn unlimited budget.

The bundled defs ship in this module; filesystem-loaded per-workspace
defs (§5.1.2) are deferred to v2 — for v1 the registry is static.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SubagentDef:
    name: str
    description: str
    system_prompt: str
    allowed_tools: tuple[str, ...]
    default_model: str = "anthropic/claude-sonnet-4-5"
    max_rounds: int = 6


_PLANNER_SYSTEM = """\
You are a focused planning subagent. Given a goal, produce a numbered
plan of 3–7 concrete steps. Reference cortex entities by ID when you
have them. Output ONE markdown block — no preamble, no commentary.\
"""

_DRAFTER_SYSTEM = """\
You are a focused drafting subagent. Receive a doc spec; produce the
full markdown body. Use cortex reads for facts. Cite sources inline as
``(source: <uri>)``. Output the body only.\
"""

_SUMMARIZER_SYSTEM = """\
You are a focused summarization subagent. Given a body of text, return
a 1–3 sentence digest preserving the action item, the decision, and
any deadline. No filler.\
"""

_VERIFIER_SYSTEM = """\
You are a SKEPTIC. The parent supplies a CLAIM. Use cortex reads to try
to disprove it. Default to ``refuted=true`` if you cannot find direct
supporting evidence. Output JSON: ``{"refuted": bool, "reason": "..."}``.
Nothing else.\
"""


BUNDLED_SUBAGENT_DEFS: dict[str, SubagentDef] = {
    "planner": SubagentDef(
        name="planner",
        description="Produce a step-by-step plan for a goal.",
        system_prompt=_PLANNER_SYSTEM,
        allowed_tools=("cortex_query", "read_entity", "get_context"),
        max_rounds=4,
    ),
    "drafter": SubagentDef(
        name="drafter",
        description="Author or revise a markdown document body.",
        system_prompt=_DRAFTER_SYSTEM,
        allowed_tools=(
            "cortex_query", "read_entity",
            "update_draft_section", "finalize_draft",
        ),
        max_rounds=8,
    ),
    "summarizer": SubagentDef(
        name="summarizer",
        description="Distil a long body into 1–3 sentences.",
        system_prompt=_SUMMARIZER_SYSTEM,
        allowed_tools=("cortex_query", "read_entity"),
        default_model="anthropic/claude-haiku-4-5-20251001",
        max_rounds=2,
    ),
    "verifier": SubagentDef(
        name="verifier",
        description="Adversarial skeptic — try to refute the supplied claim.",
        system_prompt=_VERIFIER_SYSTEM,
        allowed_tools=("cortex_query", "read_entity"),
        default_model="anthropic/claude-haiku-4-5-20251001",
        max_rounds=3,
    ),
}


def resolve(name: str) -> SubagentDef | None:
    return BUNDLED_SUBAGENT_DEFS.get(name)
