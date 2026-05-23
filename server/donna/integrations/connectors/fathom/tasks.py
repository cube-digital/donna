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
def ingest_fathom_meeting(self, workspace_id: str, meeting_id: str) -> dict:
    """
    Fetch a Fathom meeting + transcript and land them in storage.

    Idempotent end-to-end:
    - ``default_storage.save(...)`` overwrites the same key on retry.
    - ``DeliveryPackage.objects.update_or_create(...)`` upserts by
      ``UniqueConstraint(workspace, provider, provider_item_id)``.

    Args:
        workspace_id: UUID string of the Workspace the meeting belongs to.
            Resolved by the webhook view via ``provider.resolve_workspace``.
        meeting_id: Fathom's stable meeting identifier from the webhook payload.

    Returns:
        Dict with ``storage_key`` and ``delivery_package_id`` for caller/logs.
    """
    # Imports inside the task so Django apps are ready at execution time.
    from donna.integrations.models import DeliveryPackage, OAuthToken

    provider_cls = get_provider("fathom")
    provider = provider_cls()

    token = OAuthToken.objects.get(
        provider__slug=provider.oauth_provider_slug,
        workspace_id=workspace_id,
    )

    with provider.client(token) as client:
        meeting = client.get_meeting(meeting_id)
        transcript = client.get_transcript(meeting_id)

    raw = {"meeting": meeting, "transcript": transcript}
    adapter = provider.adapter_for(raw)

    storage_key = f"{workspace_id}/fathom/meetings/{meeting_id}.json"

    # Idempotent storage write — same key on retry overwrites the same blob.
    if default_storage.exists(storage_key):
        default_storage.delete(storage_key)
    default_storage.save(
        storage_key,
        ContentFile(json.dumps(adapter.to_json()).encode()),
    )

    package, created = DeliveryPackage.objects.update_or_create(
        workspace_id=workspace_id,
        provider="fathom",
        provider_item_id=adapter.external_id(),
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
            "meeting_id":           meeting_id,
            "storage_key":          storage_key,
            "delivery_package_id":  str(package.id),
            # ``created`` collides with LogRecord's built-in field name.
            "row_created":          created,
        },
    )

    return {
        "storage_key":         storage_key,
        "delivery_package_id": str(package.id),
        "created":             created,
    }
