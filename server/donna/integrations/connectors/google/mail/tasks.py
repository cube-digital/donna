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

import base64
import json
import logging
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Iterator

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

# Attachment extract allowlist — v1 mirrors the Drive ingest task
# (PDFs only). Add docx/xlsx/pptx once the OCR ladder grows strategies
# for them; until then non-PDF attachments are stored raw without a
# markdown sidecar (still indexed by filename via DP metadata).
_ATTACHMENT_EXTRACT_SUFFIXES = {".pdf"}

# Skip tiny inline images (signatures, tracking pixels). Anything under
# this threshold is almost certainly chrome, not content.
_INLINE_SKIP_MIN_BYTES = 5 * 1024


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

    # Versioned bronze key (Phase 1, 2026-06-12) — see fathom/tasks.py
    # for the rationale. Identical re-fetches collide on sha8; new
    # content lands at a new key; old version stays addressable.
    from donna.core.integrations.bronze import bronze_key

    payload_bytes = json.dumps(adapter.to_json()).encode()
    storage_key = bronze_key(
        workspace_id, "google", "mail/messages", str(message_id), payload_bytes
    )
    if not default_storage.exists(storage_key):
        default_storage.save(storage_key, ContentFile(payload_bytes))
    from donna.core.integrations.bronze import write_sidecar
    write_sidecar(default_storage, storage_key, adapter.to_markdown())

    canonical = adapter.to_canonical()

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
            "canonical_type":     canonical.entity_type,
            "canonical_payload":  canonical.as_payload(),
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

    # Attachments — extracted to their own DPs (canonical_type="doc")
    # so they're searchable independently and share OCR with the Drive
    # connector via the shared ``extract_to_sidecar`` util.
    attachments_ingested = 0
    try:
        with provider.client(conn.token) as att_client:
            attachments_ingested = _ingest_attachments(
                att_client, workspace_id, message, package,
            )
    except Exception:  # noqa: BLE001
        logger.exception(
            "gmail_attachments_failed",
            extra={
                "workspace_id":        workspace_id,
                "delivery_package_id": str(package.id),
            },
        )

    return {
        "storage_key":         storage_key,
        "delivery_package_id": str(package.id),
        "cortex_entity_id":    cortex_entity_id,
        "attachments":         attachments_ingested,
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


# ─── Attachment ingestion (2026-06-19, E3) ──────────────────────────────────
def _b64url_decode(data: str | None) -> bytes:
    """Gmail returns URL-safe base64 with stripped padding."""
    if not data:
        return b""
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _iter_attachment_parts(payload: dict) -> Iterator[dict]:
    """Walk MIME tree, yield leaf parts that look like real attachments.

    A part qualifies if it carries a ``filename`` (so not just a body
    fragment) and either inline ``body.data`` or a ``body.attachmentId``
    pointer for ``messages.attachments.get``.
    """
    if not payload:
        return
    parts = payload.get("parts") or []
    if not parts:
        body = payload.get("body") or {}
        filename = payload.get("filename") or ""
        if filename and (body.get("data") or body.get("attachmentId")):
            yield payload
        return
    for part in parts:
        yield from _iter_attachment_parts(part)


def _ingest_attachments(client, workspace_id: str, message: dict, parent: object) -> int:
    """Walk attachments, ingest each as its own doc DP.

    Stores binary at content-addressed bronze key, runs the shared
    ``extract_to_sidecar`` (PDF only in v1), emits a DeliveryPackage
    with ``canonical_type="doc"`` and metadata linking back to the
    parent email message + DP.

    Returns the count of attachment DPs upserted (filtered by allowlist
    + tiny-blob threshold).
    """
    from donna.core.integrations.binary_extract import extract_to_sidecar
    from donna.core.integrations.bronze import bronze_key
    from donna.integrations.models import DeliveryPackage

    payload = message.get("payload") or {}
    msg_id = message.get("id")
    if not msg_id:
        return 0

    count = 0
    for part in _iter_attachment_parts(payload):
        filename = part.get("filename") or ""
        mime_type = part.get("mimeType") or "application/octet-stream"
        suffix = (PurePosixPath(filename).suffix or "").lower()
        if suffix not in _ATTACHMENT_EXTRACT_SUFFIXES:
            continue

        body = part.get("body") or {}
        att_id = body.get("attachmentId")
        part_id = part.get("partId") or "0"

        if att_id:
            try:
                att = client.get_attachment(msg_id, att_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "gmail_attachment_fetch_failed",
                    extra={
                        "message_id":   msg_id,
                        "attachment_id": att_id,
                        "error":        str(exc),
                    },
                )
                continue
            raw = _b64url_decode(att.get("data"))
        else:
            raw = _b64url_decode(body.get("data"))

        if not raw or len(raw) < _INLINE_SKIP_MIN_BYTES:
            continue

        item_id = f"{msg_id}:{att_id or part_id}"
        att_bronze = bronze_key(
            workspace_id, "google", "mail/attachments", item_id, raw,
        )
        if not default_storage.exists(att_bronze):
            default_storage.save(att_bronze, ContentFile(raw))

        extract_to_sidecar(att_bronze, suffix=suffix)

        # Minimal canonical doc payload. The cortex pipeline's tier-A
        # heuristic doc-type classifier upgrades ``doc_type`` from
        # "other" when filename / mime / body match a known pattern.
        canonical_payload = {
            "entity_type": "doc",
            "external_id": item_id,
            "title":       filename,
            "occurred_at": (
                parent.occurred_at.isoformat()
                if parent.occurred_at
                else datetime.now(tz=timezone.utc).isoformat()
            ),
            "extensions": {
                "doc_type": "other",
                "mime":     mime_type,
                "filename": filename,
            },
        }

        att_package, _created = DeliveryPackage.objects.update_or_create(
            workspace_id=workspace_id,
            provider="gmail",
            provider_item_id=item_id,
            defaults={
                "provider_item_type": "email_attachment",
                "title":              filename,
                "occurred_at":        parent.occurred_at,
                "storage_key":        att_bronze,
                "metadata": {
                    "parent_message_id":  msg_id,
                    "parent_package_id":  str(parent.id),
                    "attachment_id":      att_id,
                    "part_id":            part_id,
                    "filename":           filename,
                    "mime_type":          mime_type,
                    "size":               len(raw),
                },
                "canonical_type":     "doc",
                "canonical_payload":  canonical_payload,
            },
        )

        # Cortex hop for attachment — best-effort, mirrors message path.
        try:
            from donna.cortex.pipeline import CortexPipeline

            CortexPipeline().write(att_package)
        except Exception:  # noqa: BLE001
            logger.exception(
                "cortex_write_attachment_failed",
                extra={
                    "workspace_id":        workspace_id,
                    "delivery_package_id": str(att_package.id),
                    "parent_message_id":   msg_id,
                },
            )

        count += 1
        logger.info(
            "gmail_attachment_ingested",
            extra={
                "workspace_id":        workspace_id,
                "parent_message_id":   msg_id,
                "attachment_filename": filename,
                "size_bytes":          len(raw),
                "bronze_key":          att_bronze,
            },
        )

    return count
