"""
Gmail Celery tasks.

Three layers, top-down:

- ``fanout_gmail_sync()`` — top-level scheduler entry. Beat fires this on
  a fixed interval; it iterates every enabled Gmail ``Connection`` and
  enqueues per-binding sync work.
- ``sync_gmail_connection(connection_id)`` — per-binding poll. Reads
  ``Connection.config`` to choose mode (``everything`` / ``time_window``
  / ``subscriptions``), builds a Gmail search query, enqueues
  per-message ingest tasks. Tracks watermarks in ``Connection.state``.
- ``ingest_gmail_message(workspace_id, message_id)`` — one message:
  fetch full payload, run adapter, write JSON to ``default_storage``,
  upsert ``DeliveryPackage``.

State shape kept per-stream from day one (Airbyte LEGACY → STREAM
migration lesson). See plans/08a-gmail-integration.md.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from celery import shared_task
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction

from donna.core.integrations import get as get_provider


logger = logging.getLogger(__name__)


# Recurring poll window per beat tick once cold-start has run. The Gmail
# DeliveryPackage unique constraint absorbs duplicates if our 1-hour
# window overlaps with the previous tick (which it will).
_RECENT_WINDOW = "newer_than:1h"


# ─── Per-message ingest ──────────────────────────────────────────────────────
@shared_task(name="integrations.google.mail.ingest_message", bind=True)
def ingest_gmail_message(self, workspace_id: str, message_id: str) -> dict:
    """Fetch + adapt + store one Gmail message. Idempotent on retry."""
    from donna.integrations.models import Connection, DeliveryPackage

    provider_cls = get_provider("gmail")
    provider = provider_cls()

    # Find any enabled Gmail Connection in this workspace to borrow its
    # token. (Multiple users may have paired Gmail; ingest fans out per
    # connection upstream, so this path is reached with a known message
    # ID + the workspace it belongs to.)
    conn = (
        Connection.objects
        .select_related("token")
        .filter(workspace_id=workspace_id, provider_slug="gmail", enabled=True)
        .first()
    )
    if conn is None:
        logger.warning(
            "gmail_ingest_no_connection",
            extra={"workspace_id": workspace_id, "message_id": message_id},
        )
        return {"skipped": "no_connection"}

    with provider.client(conn.token) as client:
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
            # ``created`` collides with LogRecord's built-in field name.
            "row_created":          created,
        },
    )

    return {
        "storage_key":         storage_key,
        "delivery_package_id": str(package.id),
        "created":             created,
    }


# ─── Per-Connection poll ─────────────────────────────────────────────────────
@shared_task(name="integrations.google.mail.sync_connection", bind=True)
def sync_gmail_connection(self, connection_id: str) -> dict:
    """
    Poll one Gmail Connection. Reads ``config`` to pick mode + filters,
    builds Gmail search query, enqueues ingest tasks per matching message.
    Updates ``state`` watermarks atomically.
    """
    from donna.integrations.models import Connection

    with transaction.atomic():
        conn = (
            Connection.objects
            .select_for_update()
            .select_related("token")
            .get(id=connection_id, provider_slug="gmail")
        )

        if not conn.enabled:
            return {"skipped": "disabled"}

        cfg = conn.config or {}
        state = conn.state or {}

        query = _build_query(cfg, state)
        if query is None:
            logger.info(
                "gmail_sync_no_query",
                extra={"connection_id": connection_id, "mode": cfg.get("mode")},
            )
            return {"skipped": "no_query"}

        provider_cls = get_provider("gmail")
        provider = provider_cls()

        enqueued = 0
        with provider.client(conn.token) as client:
            for entry in client.iter_all_messages(query=query):
                mid = entry.get("id")
                if not mid:
                    continue
                ingest_gmail_message.delay(str(conn.workspace_id), str(mid))
                enqueued += 1

        _update_state_after_sync(state)
        conn.state = state
        conn.last_synced_at = datetime.now(tz=timezone.utc)
        conn.last_error_at = None
        conn.last_error_msg = ""
        conn.save(
            update_fields=[
                "state",
                "last_synced_at",
                "last_error_at",
                "last_error_msg",
                "updated_at",
            ]
        )

    logger.info(
        "gmail_sync_connection_completed",
        extra={
            "connection_id": connection_id,
            "workspace_id":  str(conn.workspace_id),
            "mode":          cfg.get("mode"),
            "enqueued":      enqueued,
        },
    )
    return {"enqueued": enqueued, "mode": cfg.get("mode")}


# ─── Beat fanout ─────────────────────────────────────────────────────────────
@shared_task(name="integrations.google.mail.fanout_sync", bind=True)
def fanout_gmail_sync(self) -> dict:
    """
    Beat-triggered top-level task. Enqueues ``sync_gmail_connection`` for
    every enabled Gmail Connection.
    """
    from donna.integrations.models import Connection

    conn_ids = list(
        Connection.objects
        .filter(provider_slug="gmail", enabled=True)
        .values_list("id", flat=True)
    )

    for cid in conn_ids:
        sync_gmail_connection.delay(str(cid))

    logger.info(
        "gmail_fanout_sync_completed",
        extra={"connections": len(conn_ids)},
    )
    return {"connections": len(conn_ids)}


# ─── Helpers ────────────────────────────────────────────────────────────────
def _build_query(cfg: dict, state: dict) -> str | None:
    """
    Translate ``Connection.config`` + ``state`` into a Gmail search
    query. Returns ``None`` when there's nothing to fetch
    (e.g. ``mode=subscriptions`` with no filters).
    """
    mode = cfg.get("mode")
    cold_done = (state.get("global") or {}).get("cold_start_done", False)

    if mode == "everything":
        return _RECENT_WINDOW if cold_done else ""

    if mode == "time_window":
        days = int(cfg.get("time_window_days") or 30)
        return _RECENT_WINDOW if cold_done else f"newer_than:{days}d"

    if mode == "subscriptions":
        parts: list[str] = []
        for label_id in cfg.get("labels") or []:
            parts.append(f"label:{label_id}")
        for q in cfg.get("queries") or []:
            parts.append(f"({q})")
        for d in cfg.get("domains") or []:
            parts.append(f"from:*@{d}")
        if not parts:
            return None
        base = " OR ".join(parts)
        return f"({base}) {_RECENT_WINDOW}" if cold_done else f"({base})"

    return None


def _update_state_after_sync(state: dict) -> None:
    """
    Bump the per-stream watermarks. v1 only flips ``cold_start_done`` on
    ``global`` once the first backfill query has run. Future History API
    integration will write per-label ``last_history_id`` here too.
    """
    g = state.setdefault("global", {})
    g["cold_start_done"] = True
    g["last_synced_at"] = datetime.now(tz=timezone.utc).isoformat()
