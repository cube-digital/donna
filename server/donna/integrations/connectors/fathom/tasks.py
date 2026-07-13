"""
Fathom Celery tasks.

One task per provider, colocated with the connector. Registered with Celery
at module import via ``@shared_task``; the integrations app's ``apps.py``
auto-imports this file at startup so the task is always known to workers.
"""
from __future__ import annotations

import json
import logging

import httpx
from celery import shared_task
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from donna.core.integrations import get as get_provider


logger = logging.getLogger(__name__)


@shared_task(
    name="integrations.fathom.ingest_meeting",
    bind=True,
    # Fathom rate-limits the recordings API. Cap worker throughput and retry
    # 429s with exponential backoff so a history backfill drains without
    # tripping (or getting stuck behind) the limit.
    rate_limit="6/m",
    autoretry_for=(httpx.HTTPStatusError,),
    retry_backoff=15,
    retry_backoff_max=600,
    max_retries=8,
    retry_jitter=True,
)
def ingest_fathom_meeting(
    self,
    workspace_id: str,
    recording_id: str,
    meeting: dict | None = None,
) -> dict:
    """
    Fetch a Fathom recording's transcript + summary and land in storage.

    Idempotent end-to-end:
    - ``default_storage.save(...)`` overwrites the same key on retry.
    - ``DeliveryPackage.objects.update_or_create(...)`` upserts by
      ``UniqueConstraint(workspace, provider, provider_item_id)``.

    Args:
        workspace_id: UUID string of the Workspace.
        recording_id: Fathom recording id (stable identifier).
        meeting:    Optional pre-fetched meeting metadata dict (from a
            ``/meetings`` list item or an inbound webhook payload). Fathom has
            no singular ``/meetings/{id}`` endpoint, so we cannot synthesize
            this from ``recording_id`` alone — when omitted, the meeting
            block of the stored blob is empty and ``adapter.title()`` /
            ``occurred_at()`` fall back to defaults.
    """
    from donna.integrations.models import Connection, DeliveryPackage

    provider_cls = get_provider("fathom")
    provider = provider_cls()

    connection = (
        Connection.objects
        .select_related("token")
        .get(workspace_id=workspace_id, provider_slug="fathom")
    )
    token = connection.token

    # The adapter's external_id() (also called inside to_canonical) needs an
    # `id`/`meeting_id`. Webhook payloads carry it; /meetings list items carry
    # `recording_id`. Normalise so backfill items ingest cleanly.
    meeting = dict(meeting or {})
    meeting.setdefault("id", recording_id)

    # Prefer transcript/summary already present on the meeting payload — the
    # /meetings list item includes them inline, so re-fetching per recording is
    # a wasted (rate-limited → 429) round-trip. Only hit the per-recording
    # endpoints when they're absent (the webhook path passes ids only).
    transcript = meeting.get("transcript")
    summary    = meeting.get("default_summary") or meeting.get("summary")
    if transcript is None or summary is None:
        with provider.client(token) as client:
            if transcript is None:
                transcript = client.get_transcript(recording_id)
            if summary is None:
                summary = client.get_summary(recording_id)

    raw = {"meeting": meeting, "transcript": transcript, "summary": summary}
    adapter = provider.adapter_for(raw)

    # Versioned bronze key (Phase 1, 2026-06-12): the sha8 in the path
    # makes identical re-fetches collide on the same key (cheap idempotent
    # write) and distinct content land at NEW keys (old version preserved).
    # No more delete-then-save races.
    from donna.core.integrations.bronze import bronze_key

    payload_bytes = json.dumps(adapter.to_json()).encode()
    storage_key = bronze_key(
        workspace_id, "fathom", "meetings", str(recording_id), payload_bytes
    )
    if not default_storage.exists(storage_key):
        default_storage.save(storage_key, ContentFile(payload_bytes))
    # Phase 1 (2026-06-15): write .extracted.md sidecar so cortex
    # ``_body_for`` doesn't re-render markdown on every read.
    from donna.core.integrations.bronze import write_sidecar
    write_sidecar(default_storage, storage_key, adapter.to_markdown())

    # adapter.external_id() requires meeting.id; fall back to recording_id
    # when no meeting dict was provided.
    try:
        external_id = adapter.external_id()
    except ValueError:
        external_id = str(recording_id)

    # Phase 2 canonical payload (2026-06-15) — typed Pydantic shape
    # validated at the adapter; cortex reads it instead of ``metadata``.
    canonical = adapter.to_canonical()

    package, created = DeliveryPackage.objects.update_or_create(
        workspace_id=workspace_id,
        provider="fathom",
        provider_item_id=external_id,
        defaults={
            "provider_item_type": "meeting",
            "title":              adapter.title(),
            "occurred_at":        adapter.occurred_at(),
            "storage_key":        storage_key,
            "metadata":           adapter.metadata(),
            "canonical_type":     canonical.entity_type,
            "canonical_payload":  canonical.as_payload(),
        },
    )

    logger.info(
        "fathom_meeting_ingested",
        extra={
            "workspace_id":         workspace_id,
            "recording_id":         recording_id,
            "storage_key":          storage_key,
            "delivery_package_id":  str(package.id),
            "row_created":          created,
        },
    )

    # Cortex hop — best-effort. Bronze write must not be blocked by
    # downstream Cortex failures; log + continue. The cortex_entity
    # row is recreated on next ingest via the (workspace, content_hash)
    # idempotency key.
    cortex_entity_id: str | None = None
    try:
        from donna.cortex.pipeline import CortexPipeline

        cortex_entity = CortexPipeline().write(package)
        cortex_entity_id = str(cortex_entity.id)
    except Exception:  # noqa: BLE001
        logger.exception(
            "cortex_write_failed",
            extra={
                "workspace_id":        workspace_id,
                "delivery_package_id": str(package.id),
            },
        )

    return {
        "storage_key":         storage_key,
        "delivery_package_id": str(package.id),
        "cortex_entity_id":    cortex_entity_id,
        "created":             created,
    }


@shared_task(name="integrations.fathom.backfill_meetings", bind=True)
def backfill_fathom_meetings(self, workspace_id: str, limit: int | None = None) -> dict:
    """
    Backfill every existing Fathom meeting for a just-connected workspace.

    The webhook is CDC — it only delivers meetings recorded *after* connect.
    This runs once on connect (enqueued from ``FathomProvider.on_connect`` via
    ``transaction.on_commit``) and pages through ``GET /meetings``, enqueuing an
    ``ingest_fathom_meeting`` per recording so history lands too.

    User-facing progress ("importing…" / "N imported") is emitted by the
    ``post_save`` DeliveryPackage signal (``integrations.notifications``), so
    this task stays notification-agnostic and webhook ingests notify too.

    Idempotent: ``ingest_fathom_meeting`` upserts the ``DeliveryPackage`` by
    ``(workspace, provider, provider_item_id)``, so a re-run (or overlap with a
    webhook delivery) is safe.
    """
    from donna.integrations.models import Connection

    provider = get_provider("fathom")()
    connection = (
        Connection.objects
        .select_related("token")
        .get(workspace_id=workspace_id, provider_slug="fathom")
    )
    token = connection.token

    # Fathom rate-limits the recordings API (429). Each ingest makes 2 calls
    # (transcript + summary), so bursting the whole history at once trips the
    # limit. Stagger the enqueues with a per-item countdown to smooth the load.
    stagger_s = 6
    enqueued = 0
    with provider.client(token) as client:
        for meeting in client.iter_meetings():
            recording_id = (
                meeting.get("recording_id")
                or meeting.get("id")
                or meeting.get("meeting_id")
            )
            if not recording_id:
                continue
            ingest_fathom_meeting.apply_async(
                args=[str(workspace_id), str(recording_id), meeting],
                countdown=enqueued * stagger_s,
            )
            enqueued += 1
            if limit and enqueued >= limit:
                break

    logger.info(
        "fathom_backfill_enqueued",
        extra={"workspace_id": workspace_id, "count": enqueued, "stagger_s": stagger_s},
    )
    return {"enqueued": enqueued}
