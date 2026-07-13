"""Plan 13 §4.2 — AutoDream daily consolidation.

Runs once a day (Celery beat) per workspace. Groups unconsolidated
``SessionMemory`` rows by ``(scope, scope_ref)``, runs a Sonnet pass
that distills each group into a coherent paragraph, and writes the
result as a ``CortexEntity`` so downstream cortex queries surface it
naturally. The source rows are marked ``consolidated_at = now`` so the
next pass doesn't re-merge them.

Best-effort: any group whose consolidation fails stays unconsolidated
and gets retried tomorrow. We never raise from the worker — a failed
group is a missed insight, not a failed system.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Iterable

from celery import shared_task
from django.utils import timezone

from donna.chat.models import AgentSession, SessionMemory
from donna.core.llm.factory import LLMFactory

logger = logging.getLogger(__name__)

SONNET_MODEL = "anthropic/claude-sonnet-4-5"

CONSOLIDATOR_SYSTEM = """\
You merge a list of short factual notes about the same relationship
(person / channel / project / org / 'self' = the agent itself) into
ONE coherent paragraph the agent should remember next time.

Rules:
- Output prose, not bullets. ≤ 250 words.
- Resolve contradictions in favor of the LATER note (notes are listed
  in chronological order). If notes disagree, prefer the most recent
  one and drop the older claim.
- Drop trivia (one-time questions, transient state). Keep durable
  facts: preferences, commitments, recurring constraints, decisions.
- DO NOT add a preamble ("Here is the merged paragraph…"). Output the
  paragraph only.
- DO NOT invent facts beyond what's in the notes.\
"""


def _group_by_scope(rows: Iterable[SessionMemory]) -> dict[tuple[str, str], list[SessionMemory]]:
    groups: dict[tuple[str, str], list[SessionMemory]] = defaultdict(list)
    for r in rows:
        groups[(r.scope, r.scope_ref or "")].append(r)
    return groups


def _consolidate_group(rows: list[SessionMemory], llm=None) -> str | None:
    """Run the Sonnet merge on one (scope, scope_ref) group."""
    if not rows:
        return None
    rows.sort(key=lambda r: r.created_at)
    rendered = "\n".join(f"- ({r.confidence:.2f}) {r.body}" for r in rows)
    prompt = (
        f"Scope: {rows[0].scope}\n"
        f"Scope ref: {rows[0].scope_ref or '(none)'}\n\n"
        f"Notes (chronological):\n{rendered}\n\n"
        f"Merge them per the rules. Output the paragraph only."
    )
    provider = llm or LLMFactory.create(model=SONNET_MODEL)
    try:
        resp = provider.get_answer(
            prompt=prompt,
            system_prompt=CONSOLIDATOR_SYSTEM,
            temperature=0.2,
            max_tokens=500,
        )
    except Exception:  # noqa: BLE001
        logger.warning("auto_dream_consolidate_failed", extra={
            "scope": rows[0].scope, "scope_ref": rows[0].scope_ref,
            "rows": len(rows),
        })
        return None
    content = getattr(resp, "content", None) or getattr(resp, "text", None)
    if not isinstance(content, str):
        return None
    return content.strip() or None


def _write_to_cortex(
    *, service, scope: str, scope_ref: str, body: str, source_session_ids: list,
) -> None:
    """Persist the consolidated paragraph as a cortex entity."""
    title = f"AutoDream: {scope}" + (f" — {scope_ref}" if scope_ref else "")
    footer = (
        "\n\n---\n"
        f"Source: donna://auto-dream/{scope}/{scope_ref}\n"
        f"Sessions: {', '.join(str(s) for s in source_session_ids[:8])}\n"
    )
    service.create_entity(
        type="person" if scope in ("user", "peer") else "concept",
        author="self",
        source="donna://auto-dream",
        title=title,
        body_md=body + footer,
    )


def run_autodream_for_workspace(*, workspace, llm=None) -> dict:
    """Process every unconsolidated SessionMemory row for ``workspace``.

    Returns a stats dict: ``{groups, written, skipped}``.
    """
    from donna.cortex.services import CortexService

    rows = list(
        SessionMemory.objects
        .select_related("session", "session__channel")
        .filter(
            session__channel__workspace=workspace,
            consolidated_at__isnull=True,
        )
    )
    if not rows:
        return {"groups": 0, "written": 0, "skipped": 0}

    groups = _group_by_scope(rows)
    written = 0
    skipped = 0
    service = CortexService(current_user=None, company=workspace)
    now = timezone.now()

    for (scope, scope_ref), group_rows in groups.items():
        body = _consolidate_group(group_rows, llm=llm)
        if not body:
            skipped += 1
            continue
        try:
            _write_to_cortex(
                service=service,
                scope=scope,
                scope_ref=scope_ref,
                body=body,
                source_session_ids=list({r.session_id for r in group_rows}),
            )
        except Exception:  # noqa: BLE001
            logger.warning("auto_dream_cortex_write_failed", extra={
                "scope": scope, "scope_ref": scope_ref,
            })
            skipped += 1
            continue
        # Mark these rows consolidated so tomorrow's pass skips them.
        SessionMemory.objects.filter(
            id__in=[r.id for r in group_rows],
        ).update(consolidated_at=now)
        written += 1
    return {"groups": len(groups), "written": written, "skipped": skipped}


@shared_task(name="chat.autodream")
def autodream() -> dict:
    """Beat-driven entrypoint — runs AutoDream for every workspace that
    has unconsolidated session memory pending."""
    from donna.workspaces.models import Workspace

    pending_workspace_ids = (
        SessionMemory.objects
        .filter(consolidated_at__isnull=True)
        .values_list("session__channel__workspace_id", flat=True)
        .distinct()
    )
    totals = {"workspaces": 0, "groups": 0, "written": 0, "skipped": 0}
    for ws_id in pending_workspace_ids:
        ws = Workspace.objects.filter(id=ws_id).first()
        if ws is None:
            continue
        stats = run_autodream_for_workspace(workspace=ws)
        totals["workspaces"] += 1
        totals["groups"] += stats["groups"]
        totals["written"] += stats["written"]
        totals["skipped"] += stats["skipped"]
    return totals
