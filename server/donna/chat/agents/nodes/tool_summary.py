"""Plan 13 §1.2 — Haiku tool-use summaries.

After the dispatcher runs a batch of tool calls, fire a Haiku call that
distills "what just happened" into a single chat-friendly line. The
frontend renders the summary as a chip under the message, so users
reading the channel don't have to expand raw tool result JSON to know
what the agent did this round.

Best-effort: any failure (LLM down, parse error, empty batch) returns
``None`` and the dispatcher continues without a summary. Tool execution
is never blocked by summarization.
"""
from __future__ import annotations

import json
import logging
from typing import Iterable, Sequence

from donna.core.llm.factory import LLMFactory

logger = logging.getLogger(__name__)

HAIKU_MODEL = "anthropic/claude-haiku-4-5-20251001"

SUMMARY_SYSTEM = """\
You distill the tool calls an AI agent just ran into ONE sentence
(≤ 22 words) describing what the agent did and the headline result.

Rules:
- Write in present tense, third person ("Searched cortex for the Acme
  contract; found 3 matching entities.").
- Mention the headline number when one is present (count of results,
  rows updated, version bumped to N).
- No model commentary, no apology, no "the agent" / "Donna" prefix.
- If the batch is a single read with no obvious payload, summarise the
  query ("Looked up Bruno's open invoices.").
- If every tool returned an error, surface that ("Tool calls failed —
  retrying.") rather than detail.\
"""


def _shape_for_summary(tool_messages: Sequence[dict]) -> list[dict]:
    """Trim tool messages to the fields the summariser actually needs.

    Drops huge cortex payloads to keep the Haiku prompt small. Each entry
    becomes ``{name, ok, headline}`` where ``headline`` is the first
    ~280 chars of the JSON-decoded content, or the error string if any.
    """
    out: list[dict] = []
    for msg in tool_messages:
        if msg.get("role") != "tool":
            continue
        raw = msg.get("content") or "{}"
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            payload = {"_raw": raw[:280]}
        err = payload.get("error") if isinstance(payload, dict) else None
        headline = (
            err
            if err
            else json.dumps(payload, default=str)[:280]
        )
        out.append({
            "name": (payload.get("tool") if isinstance(payload, dict) else None)
                    or msg.get("name")
                    or "tool",
            "ok": err is None,
            "headline": headline,
        })
    return out


def summarize_tool_batch(tool_messages: Iterable[dict], llm=None) -> str | None:
    """Return a one-line summary of a tool batch, or ``None`` on failure.

    ``llm`` is an injection seam for tests; callers normally pass nothing
    and let the function spin up a Haiku provider.
    """
    shaped = _shape_for_summary(list(tool_messages))
    if not shaped:
        return None
    prompt = (
        "Tool batch (JSON):\n"
        + json.dumps(shaped, default=str)
        + "\n\nWrite ONE summary sentence per the rules. Output the "
        "sentence only, no quotes, no prefix."
    )
    provider = llm or LLMFactory.create(model=HAIKU_MODEL)
    try:
        resp = provider.get_answer(
            prompt=prompt,
            system_prompt=SUMMARY_SYSTEM,
            temperature=0.3,
            max_tokens=80,
        )
    except Exception:  # noqa: BLE001 — best-effort
        logger.warning("tool_summary_llm_failed", extra={"batch_size": len(shaped)})
        return None
    content = getattr(resp, "content", None) or getattr(resp, "text", None)
    if not isinstance(content, str):
        return None
    stripped = content.strip()
    if not stripped:
        return None
    sentence = stripped.splitlines()[0].strip().strip('"')
    return sentence or None
