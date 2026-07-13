"""Plan 13 §4.1 — per-turn Haiku memory extraction.

After each turn, ``extract_session_memory(session, turn_id, transcript)``
is fired (post-turn hook from ``chat.tasks.run_agent_turn``). The
extractor asks Haiku for ZERO OR MORE compact note entries, each tagged
with a ``scope`` discriminator (§4.4). Output entries write directly to
``SessionMemory``.

The extractor is best-effort: any LLM failure is swallowed (logged) and
the turn completes normally. Memory is supposed to compound; missing a
single turn is a transient miss, not a regression.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Iterable

from donna.chat.models import SessionMemory
from donna.core.llm.factory import LLMFactory

logger = logging.getLogger(__name__)

HAIKU_MODEL = "anthropic/claude-haiku-4-5-20251001"

EXTRACTOR_SYSTEM = """\
You read the most recent turn of an AI agent's conversation and extract
short notes the agent should remember LATER. Output JSON:

  {"notes": [{"scope": "<user|channel|peer|project|org|self>",
              "scope_ref": "<id-or-handle, may be empty>",
              "body": "<one-line note ≤ 200 chars>",
              "confidence": <0.0-1.0>}]}

Rules:
- Only extract notes that will be USEFUL across sessions (preferences,
  commitments, recurring facts about a person/project/org).
- DO NOT extract ephemeral facts ("user said hi", "user asked a
  question"). DO NOT restate the user's message.
- Prefer ``scope_ref`` populated when you mention a person / project /
  org — use whatever identifier appears in the transcript.
- ``self`` scope is for facts the agent should know about its OWN
  behavior ("user prefers terse answers", "user asked me to stop
  numbering lists").
- Return ``{"notes": []}`` if the turn had nothing memorable.\
"""


def _build_prompt(transcript: Iterable[dict]) -> str:
    """Compact-render the turn for the Haiku prompt — last 8 messages."""
    last = list(transcript)[-8:]
    rendered = []
    for m in last:
        role = m.get("role", "?")
        content = m.get("content")
        if isinstance(content, list):  # tool_call content shape
            content = " | ".join(str(c)[:200] for c in content)
        rendered.append(f"[{role}] {str(content)[:280]}")
    return "TRANSCRIPT (last 8 messages):\n" + "\n".join(rendered)


def _parse_notes(raw: Any) -> list[dict]:
    if isinstance(raw, dict):
        notes = raw.get("notes")
        if isinstance(notes, list):
            return [n for n in notes if isinstance(n, dict) and n.get("body")]
    return []


def extract_session_memory(
    *,
    session,
    turn_id: str,
    transcript: Iterable[dict],
    llm=None,
) -> list[SessionMemory]:
    """Run the extractor and persist notes.

    ``llm`` is an injection seam for tests; production callers pass
    nothing and let the function build a Haiku provider.
    """
    prompt = _build_prompt(transcript)
    provider = llm or LLMFactory.create(model=HAIKU_MODEL)
    try:
        resp = provider.get_answer(
            prompt=prompt,
            system_prompt=EXTRACTOR_SYSTEM,
            temperature=0.2,
            max_tokens=400,
        )
    except Exception:  # noqa: BLE001 — best-effort
        logger.warning("session_memory_extract_llm_failed", extra={"turn_id": turn_id})
        return []

    content = getattr(resp, "content", None) or getattr(resp, "text", None)
    if not isinstance(content, str):
        return []
    text = content.strip()
    # Strip ```json fences if present — Haiku occasionally wraps output.
    if text.startswith("```"):
        text = text.strip("`").lstrip("json").strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("session_memory_extract_bad_json", extra={"turn_id": turn_id})
        return []

    notes = _parse_notes(payload)
    if not notes:
        return []

    valid_scopes = {s.value for s in SessionMemory.Scope}
    rows: list[SessionMemory] = []
    for n in notes:
        scope = n.get("scope") or "user"
        if scope not in valid_scopes:
            scope = "user"
        try:
            confidence = float(n.get("confidence", 0.7))
        except (TypeError, ValueError):
            confidence = 0.7
        rows.append(SessionMemory(
            session=session,
            turn_id=turn_id,
            scope=scope,
            scope_ref=str(n.get("scope_ref") or "")[:80],
            body=str(n["body"])[:1000],
            confidence=max(0.0, min(1.0, confidence)),
        ))
    if rows:
        SessionMemory.objects.bulk_create(rows)
    return rows
