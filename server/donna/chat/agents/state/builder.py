"""AgentState — per-turn LiteLLM-flat message window built from chat history.

When the channel has few messages, the whole history is fed verbatim.
When it grows past ``COMPACTION_TRIGGER``, the older slice gets
**branch-aware Haiku compaction** (openclaw pattern, 2026-06-14):
bucketed by ``(author, thread_root)``, one digest paragraph per
bucket, cached on ``AgentSession.memory["branch_digest"]`` keyed by
the highest message id summarized. The recent tail is always kept
verbatim — humans glancing at a chat re-read the last N msgs, not the
whole thread.

Plain English: long chats don't blow the context window AND don't
forget who said what. Old discussion gets compressed; recent stays
raw; the compression cost is paid once and cached.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from donna.chat.models import AgentSession, Channel, Message


logger = logging.getLogger(__name__)


HISTORY_WINDOW = 30                # verbatim tail when no compaction triggers
COMPACTION_TRIGGER = 60            # total fetched → kick branch compaction
KEEP_VERBATIM_RECENT = 15          # tail always kept raw when compacting


@dataclass
class AgentState:
    messages: list[dict]
    pending_tool_calls: list[Any] = field(default_factory=list)
    rounds: int = 0
    final_text: str | None = None
    run_id: str = field(default_factory=lambda: uuid4().hex)
    # Cross-round taint tracking (Phase A1, 2026-06-15). Strings
    # observed in EXTERNAL_CONTENT_TOOLS payloads land here; the
    # dispatcher checks args of taint_safe=False tools against this
    # set on every subsequent round so the taint flow survives the
    # LLM round-trip that strips the type marker.
    tainted_strings: set = field(default_factory=set)


def build_state(channel: Channel, session: AgentSession) -> AgentState:
    """Build AgentState — verbatim window or branch-compacted + tail."""
    rows = list(
        Message.objects
        .filter(channel=channel)
        .select_related("author_user", "author_agent")
        .order_by("-created_at")[: max(HISTORY_WINDOW, COMPACTION_TRIGGER)]
    )
    rows.reverse()  # chronological

    messages: list[dict] = []
    summary = (session.memory or {}).get("summary")
    if summary:
        messages.append({
            "role": "system",
            "content": f"== ROLLING MEMORY ==\n{summary}",
        })

    if len(rows) <= HISTORY_WINDOW:
        messages.extend(_to_litellm(m) for m in rows)
    else:
        # Branch-aware compaction path.
        split_at = len(rows) - KEEP_VERBATIM_RECENT
        older, recent = rows[:split_at], rows[split_at:]
        digest_msg = _branch_digest_message(older, channel, session)
        if digest_msg is not None:
            messages.append(digest_msg)
        messages.extend(_to_litellm(m) for m in recent)

    return AgentState(messages=messages)


# ── compaction internals ───────────────────────────────────────────


def _branch_digest_message(
    older: list[Message],
    channel: Channel,
    session: AgentSession,
) -> dict | None:
    """One synthetic system message compacting old turns.

    Cache key: id of the most recent old-tier message. Same key →
    return cached. New old-tier messages → recompute.
    """
    if not older:
        return None

    high_id = str(older[-1].id)
    cached = (session.memory or {}).get("branch_digest") or {}
    if cached.get("up_to_id") == high_id and cached.get("text"):
        return {"role": "system", "content": cached["text"]}

    # Bucket by (author_label, thread_root). Without a parent link
    # model, thread_root = the message id itself — every message stands
    # alone. Refine when parent edges exist.
    buckets: dict[tuple[str, str], list[Message]] = {}
    for m in older:
        author = _user_label(m, session)
        thread_root = str(m.id)  # no parent edges yet
        buckets.setdefault((author, thread_root), []).append(m)

    chunks: list[str] = []
    for (author, thread), msgs in buckets.items():
        first_ts = msgs[0].created_at.date().isoformat() if msgs[0].created_at else ""
        joined = "\n".join(f"- {m.body[:200]}" for m in msgs)
        chunks.append(f"### {author} (thread {thread[:8]}, {first_ts}, {len(msgs)} msgs)\n{joined}")

    text = _haiku_compact("\n\n".join(chunks))
    if text is None:
        # Compaction failed → fall back to a plain truncation note so
        # the LLM at least knows older history was dropped.
        text = (
            "== EARLIER CONVERSATION (truncated — compaction unavailable) ==\n"
            f"{len(older)} earlier messages from {len(buckets)} threads dropped to fit context."
        )

    payload = {"up_to_id": high_id, "text": text}
    memory = dict(session.memory or {})
    memory["branch_digest"] = payload
    session.memory = memory
    session.save(update_fields=["memory", "updated_at"])
    return {"role": "system", "content": text}


def _haiku_compact(bulk: str) -> str | None:
    """Ask Haiku for a branch-bucketed digest. None on failure."""
    try:
        from donna.core.llm.factory import LLMFactory
    except Exception:  # noqa: BLE001
        return None
    try:
        llm = LLMFactory.create(model="anthropic/claude-haiku-4-5-20251001")
        resp = llm.chat(
            messages=[{"role": "user", "content": bulk[:30000]}],
            system_prompt=(
                "Compact the chat history below, which is bucketed by author "
                "and thread. Keep decisions, named entities, and unresolved "
                "questions verbatim; drop chitchat and pleasantries. Output "
                "one short paragraph per bucket — plain prose, no markdown "
                "headers, no bullet points."
            ),
            temperature=0.2,
        )
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        return "== EARLIER CONVERSATION (compacted, branch-aware) ==\n" + content
    except Exception:  # noqa: BLE001
        logger.warning("branch_compaction_llm_failed", exc_info=True)
        return None


def _to_litellm(m: Message) -> dict:
    if m.author_agent_id is not None:
        return {"role": "assistant", "content": m.body}
    label = _user_label(m, None)
    return {"role": "user", "content": f"{label}: {m.body}"}


def _user_label(message: Message, session: AgentSession | None) -> str:
    if message.author_agent_id is not None:
        return f"Donna({session.name})" if session else "Donna"
    user = message.author_user
    if user is None:
        return "user"
    name = getattr(user, "display_name", None) or getattr(user, "name", None)
    if name:
        return str(name)
    email = getattr(user, "email", "") or ""
    return email.split("@", 1)[0] if email else "user"
