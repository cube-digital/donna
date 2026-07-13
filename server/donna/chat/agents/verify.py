"""Plan 13 §5.4 — adversarial verify helper.

Fan out N skeptic subagents (``subagent_type="verifier"``) against a
factual claim and majority-vote whether the claim is refuted. Used by
drafting + outbound-message tools to gate "you said Alice agreed to X"
claims before they hit the channel.

The verifier subagent's job is to TRY TO REFUTE — its prompt defaults
to ``refuted=true`` when it cannot find supporting evidence. Two of
three refutations is enough to flag the claim as unsafe.

Per-tool budget: keep N ≤ 3, ≤ 1 verify pass per outbound message.
"""
from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from donna.chat.agents.subagents import resolve as resolve_subagent
from donna.chat.agents.tools.agent_tool import run_subagent_sync
from donna.chat.agents.tools.base import ToolContext

logger = logging.getLogger(__name__)

Verdict = Literal["stands", "refuted"]


_VERIFIER_PROMPT_TPL = """\
Claim to refute (try to disprove using cortex reads):

> {claim}

Output JSON only: {{"refuted": bool, "reason": "..."}}.
If you cannot find direct supporting evidence, return refuted=true.
"""


def _extract_json(text: str) -> dict | None:
    """Best-effort JSON extraction — the verifier prompt asks for clean
    JSON, but Haiku occasionally wraps it in prose or fences."""
    if not isinstance(text, str):
        return None
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").lstrip("json").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*?\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
    return None


def _one_vote(claim: str, ctx: ToolContext, llm_factory=None) -> dict:
    """Run a single verifier subagent and parse its JSON vote."""
    defn = resolve_subagent("verifier")
    if defn is None:
        return {"refuted": True, "reason": "verifier subagent missing"}
    out = run_subagent_sync(
        defn=defn,
        prompt=_VERIFIER_PROMPT_TPL.format(claim=claim),
        parent_ctx=ctx,
        llm_factory=llm_factory,
    )
    if out.get("error"):
        # Treat verify failure as a refusal — don't pretend a claim is
        # safe just because the verifier crashed.
        return {"refuted": True, "reason": f"verifier error: {out['error']}"}
    parsed = _extract_json(out.get("text") or "")
    if not isinstance(parsed, dict):
        return {"refuted": True, "reason": "verifier returned non-JSON"}
    return {
        "refuted": bool(parsed.get("refuted", True)),
        "reason": str(parsed.get("reason", ""))[:280],
    }


def verify_finding(
    *,
    claim: str,
    ctx: ToolContext,
    n: int = 3,
    llm_factory=None,
) -> tuple[Verdict, list[dict]]:
    """Run ``n`` adversarial verifiers in parallel against ``claim``.

    Returns ``("refuted", votes)`` when a strict majority of votes
    refute the claim; otherwise ``("stands", votes)``. ``n`` is clamped
    to ``[1, 5]`` to keep cost bounded.
    """
    n = max(1, min(int(n), 5))
    with ThreadPoolExecutor(max_workers=n) as ex:
        votes = list(ex.map(lambda _: _one_vote(claim, ctx, llm_factory), range(n)))
    refuted = sum(1 for v in votes if v.get("refuted"))
    needed = n // 2 + 1
    verdict: Verdict = "refuted" if refuted >= needed else "stands"
    logger.info(
        "verify_finding",
        extra={"n": n, "refuted": refuted, "verdict": verdict},
    )
    return verdict, votes
