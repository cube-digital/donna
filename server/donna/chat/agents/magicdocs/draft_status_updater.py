"""Plan 13 §6.1 — DRAFT_STATUS sibling artifact updater.

When ``UpdateDraftSectionTool.run`` bumps a draft's version, it fires
``update_draft_status_doc.delay(draft.id)``. The task:

1. Loads (or creates) the sibling status Artifact for this draft. The
   pointer lives at ``draft.metadata['status_artifact_id']`` — first
   call creates the sibling and stamps the pointer.
2. Runs a Haiku call that produces a SHORT status note (≤ 6 bullet
   points) summarizing "where the draft is right now."
3. Replaces the sibling artifact's body in-place. The version isn't
   bumped — this is a status board, not a versioned draft.

Best-effort: any failure (LLM down, transaction conflict) leaves the
sibling untouched. A missed update means the team sees a slightly
stale status; the next edit will catch up.
"""
from __future__ import annotations

import logging

from celery import shared_task
from django.db import transaction

from donna.chat.models import Artifact
from donna.core.llm.factory import LLMFactory

logger = logging.getLogger(__name__)

HAIKU_MODEL = "anthropic/claude-haiku-4-5-20251001"

STATUS_SYSTEM = """\
You produce a SHORT status note for an in-flight markdown draft so a
teammate skimming the channel knows what's done + what's open without
reading the full body. Constraints:

- ≤ 6 bullets, ≤ 20 words each.
- Three sections in order: **Done** / **In progress** / **Open
  questions**. Omit a section if it's empty.
- Plain text bullets ("- foo"), not numbered.
- Don't restate the draft body. Don't add headings beyond the three
  section labels.\
"""


def _build_prompt(draft: Artifact) -> str:
    body_excerpt = (draft.body or "").strip()[:3000]
    return (
        f"Draft title: {draft.title}\n"
        f"Target doc type: {draft.target_doc_type or '(unspecified)'}\n"
        f"Version: v{draft.version}\n\n"
        f"Draft body so far:\n---\n{body_excerpt}\n---\n\n"
        f"Write the status note per the rules."
    )


def _get_or_create_sibling(draft: Artifact) -> Artifact:
    """Return the status sibling, creating + linking on first call."""
    metadata = dict(draft.metadata or {})
    sibling_id = metadata.get("status_artifact_id")
    if sibling_id:
        sibling = Artifact.objects.filter(id=sibling_id).first()
        if sibling is not None:
            return sibling
        # Pointer was set but the target is gone — recreate.
    sibling = Artifact.objects.create(
        channel=draft.channel,
        title=f"{draft.title} — status",
        body="(initial status pending)",
        status=Artifact.Status.DRAFTING,
        version=0,
        metadata={"kind": "draft_status", "parent_artifact_id": str(draft.id)},
    )
    metadata["status_artifact_id"] = str(sibling.id)
    draft.metadata = metadata
    draft.save(update_fields=["metadata", "updated_at"])
    return sibling


def _haiku_status_for(draft: Artifact, llm=None) -> str | None:
    provider = llm or LLMFactory.create(model=HAIKU_MODEL)
    try:
        resp = provider.get_answer(
            prompt=_build_prompt(draft),
            system_prompt=STATUS_SYSTEM,
            temperature=0.3,
            max_tokens=350,
        )
    except Exception:  # noqa: BLE001
        logger.warning("draft_status_haiku_failed", extra={"draft_id": str(draft.id)})
        return None
    content = getattr(resp, "content", None) or getattr(resp, "text", None)
    if not isinstance(content, str):
        return None
    return content.strip() or None


@shared_task(name="chat.update_draft_status_doc")
def update_draft_status_doc(draft_id: str) -> dict:
    """Refresh the sibling status artifact for ``draft_id``."""
    try:
        draft = Artifact.objects.get(id=draft_id)
    except Artifact.DoesNotExist:
        return {"draft_id": draft_id, "skipped": "missing_draft"}

    if draft.status != Artifact.Status.DRAFTING:
        # Finalized / abandoned drafts don't get a moving status board.
        return {"draft_id": draft_id, "skipped": "not_drafting"}

    with transaction.atomic():
        sibling = _get_or_create_sibling(draft)
    body = _haiku_status_for(draft)
    if not body:
        return {"draft_id": draft_id, "sibling_id": str(sibling.id), "updated": False}
    sibling.body = body
    sibling.save(update_fields=["body", "updated_at"])
    return {"draft_id": draft_id, "sibling_id": str(sibling.id), "updated": True}
