"""
Fathom Celery tasks.

One task per provider, colocated with the connector. Registered with Celery
at module import via ``@shared_task``; the integrations app's ``apps.py``
auto-imports this file at startup so the task is always known to workers.
"""
from __future__ import annotations

import json
import logging

from celery import shared_task
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from donna.core.integrations import get as get_provider


logger = logging.getLogger(__name__)


@shared_task(name="integrations.fathom.ingest_meeting", bind=True)
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

    with provider.client(token) as client:
        transcript = client.get_transcript(recording_id)
        summary    = client.get_summary(recording_id)

    raw = {"meeting": meeting or {}, "transcript": transcript, "summary": summary}
    adapter = provider.adapter_for(raw)

    storage_key = f"{workspace_id}/fathom/meetings/{recording_id}.json"

    # Idempotent storage write — same key on retry overwrites the same blob.
    if default_storage.exists(storage_key):
        default_storage.delete(storage_key)
    default_storage.save(
        storage_key,
        ContentFile(json.dumps(adapter.to_json()).encode()),
    )

    # adapter.external_id() requires meeting.id; fall back to recording_id
    # when no meeting dict was provided.
    try:
        external_id = adapter.external_id()
    except ValueError:
        external_id = str(recording_id)

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

    return {
        "storage_key":         storage_key,
        "delivery_package_id": str(package.id),
        "created":             created,
    }
