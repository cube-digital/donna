"""Plan 13 §4.4 — relationship-sharded memory loader.

Given a session + turn context, return the curated slice of
``SessionMemory`` rows the system prompt should include. Filters by:

- ``session`` (always include the agent's own learnings about itself
  and the active user — scopes ``self`` / ``user``).
- ``channel`` (current channel's accumulated notes).
- Any ``project`` / ``org`` / ``peer`` whose ``scope_ref`` matches an
  id present in the active context (current user id, channel id, and
  the participants we know about).

Cap at ``TOP_K`` rows ordered by ``-confidence, -created_at`` to keep
the system prompt small.
"""
from __future__ import annotations

from typing import Iterable

from django.db.models import Q

from donna.chat.models import SessionMemory

TOP_K = 30


def load_scoped_memory_for_session(
    *,
    session,
    channel_id: str | None = None,
    user_id: str | None = None,
    project_ids: Iterable[str] = (),
    org_ids: Iterable[str] = (),
    peer_ids: Iterable[str] = (),
    top_k: int = TOP_K,
) -> list[SessionMemory]:
    """Return the relevant SessionMemory rows for this turn."""
    q = (
        Q(session=session, scope__in=["self", "user"])
        | Q(scope="channel", scope_ref=str(channel_id) if channel_id else "")
    )
    if user_id:
        q |= Q(scope="user", scope_ref=str(user_id))
    if project_ids:
        q |= Q(scope="project", scope_ref__in=[str(p) for p in project_ids])
    if org_ids:
        q |= Q(scope="org", scope_ref__in=[str(o) for o in org_ids])
    if peer_ids:
        q |= Q(scope="peer", scope_ref__in=[str(p) for p in peer_ids])

    return list(
        SessionMemory.objects
        .filter(q)
        .order_by("-confidence", "-created_at")[:top_k]
    )


def render_memory_for_prompt(rows: Iterable[SessionMemory]) -> str:
    """Compact-render a memory slice for inclusion in the system prompt."""
    grouped: dict[str, list[str]] = {}
    for r in rows:
        key = f"{r.scope}:{r.scope_ref}" if r.scope_ref else r.scope
        grouped.setdefault(key, []).append(f"- {r.body}")
    if not grouped:
        return ""
    parts = ["== SCOPED MEMORY =="]
    for key in sorted(grouped):
        parts.append(f"[{key}]")
        parts.extend(grouped[key])
    return "\n".join(parts)
