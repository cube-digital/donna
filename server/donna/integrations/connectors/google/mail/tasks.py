"""
Gmail Celery tasks.

Three layers, top-down:

- ``fanout_gmail_sync()`` — top-level scheduler entry. Beat fires this on a
  fixed interval; it queries every workspace-scoped Google token and
  enqueues per-workspace sync work.
- ``sync_gmail_inbox(workspace_id)`` — per-workspace poll. v1 does a
  cold-start ``newer_than:{interval}`` query (idempotent via
  ``DeliveryPackage`` unique constraint, so duplicate fetches just upsert).
  Switches to ``history()`` incremental sync once
  ``OAuthToken.metadata['history_id']`` lands (see plan open gap).
- ``ingest_gmail_message(workspace_id, message_id)`` — one message:
  fetch full payload, run adapter, write JSON to ``default_storage``,
  upsert ``DeliveryPackage``.
"""
from __future__ import annotations

import json
import logging

from celery import shared_task
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from donna.core.integrations import get as get_provider


logger = logging.getLogger(__name__)


# Cold-start window for v1 polling. Each beat tick re-fetches the last
# ``COLD_START_WINDOW`` worth of messages; DeliveryPackage unique constraint
# absorbs duplicates. Replace with history-API incremental sync once
# OAuthToken.metadata['history_id'] is wired.
COLD_START_WINDOW = "newer_than:1h"


# ─── Per-message ingest ──────────────────────────────────────────────────────
@shared_task(name="integrations.google.mail.ingest_message", bind=True)
def ingest_gmail_message(self, workspace_id: str, message_id: str) -> dict:
    """Fetch + adapt + store one Gmail message. Idempotent on retry."""
    from donna.authentication.models import OAuthToken
    from donna.integrations.models import DeliveryPackage

    provider_cls = get_provider("gmail")
    provider = provider_cls()

    token = OAuthToken.objects.get(
        provider__slug=provider.oauth_provider_slug,
        workspace_id=workspace_id,
    )

    with provider.client(token) as client:
        message = client.get_message(message_id, fmt="full")

    raw = {"message": message}
    adapter = provider.adapter_for(raw)

    storage_key = f"{workspace_id}/google/mail/messages/{message_id}.json"

    # Idempotent storage write — same key overwrites the same blob.
    if default_storage.exists(storage_key):
        default_storage.delete(storage_key)
    default_storage.save(
        storage_key,
        ContentFile(json.dumps(adapter.to_json()).encode()),
    )

    package, created = DeliveryPackage.objects.update_or_create(
        workspace_id=workspace_id,
        provider="gmail",
        provider_item_id=adapter.external_id(),
        defaults={
            "provider_item_type": "email",
            "title":              adapter.title(),
            "occurred_at":        adapter.occurred_at(),
            "storage_key":        storage_key,
            "metadata":           adapter.metadata(),
        },
    )

    logger.info(
        "gmail_message_ingested",
        extra={
            "workspace_id":         workspace_id,
            "message_id":           message_id,
            "storage_key":          storage_key,
            "delivery_package_id":  str(package.id),
            "created":              created,
        },
    )

    return {
        "storage_key":         storage_key,
        "delivery_package_id": str(package.id),
        "created":             created,
    }


# ─── Per-workspace poll ──────────────────────────────────────────────────────
@shared_task(name="integrations.google.mail.sync_inbox", bind=True)
def sync_gmail_inbox(self, workspace_id: str) -> dict:
    """
    Poll one workspace's Gmail inbox. v1: cold-start query for the last
    ``COLD_START_WINDOW`` of messages. Enqueues per-message ingest tasks.
    """
    from donna.authentication.models import OAuthToken

    provider_cls = get_provider("gmail")
    provider = provider_cls()

    token = OAuthToken.objects.get(
        provider__slug=provider.oauth_provider_slug,
        workspace_id=workspace_id,
    )

    enqueued = 0
    with provider.client(token) as client:
        for entry in client.iter_all_messages(query=COLD_START_WINDOW):
            message_id = entry.get("id")
            if not message_id:
                continue
            ingest_gmail_message.delay(str(workspace_id), str(message_id))
            enqueued += 1

    logger.info(
        "gmail_sync_inbox_completed",
        extra={"workspace_id": workspace_id, "enqueued": enqueued},
    )
    return {"enqueued": enqueued}


# ─── Beat fanout ─────────────────────────────────────────────────────────────
@shared_task(name="integrations.google.mail.fanout_sync", bind=True)
def fanout_gmail_sync(self) -> dict:
    """
    Beat-triggered top-level task. Enqueues ``sync_gmail_inbox`` for every
    workspace that has a connected Google token.
    """
    from donna.authentication.models import OAuthToken

    workspace_ids = (
        OAuthToken.objects
        .filter(provider__slug="google", workspace__isnull=False)
        .values_list("workspace_id", flat=True)
        .distinct()
    )

    dispatched = 0
    for ws_id in workspace_ids:
        sync_gmail_inbox.delay(str(ws_id))
        dispatched += 1

    logger.info("gmail_fanout_sync_completed", extra={"workspaces": dispatched})
    return {"workspaces": dispatched}
