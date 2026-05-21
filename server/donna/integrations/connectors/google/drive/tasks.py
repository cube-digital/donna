"""
Drive Celery tasks.

- ``fanout_drive_sync()``                — beat-triggered fanout
- ``sync_drive_connection(conn_id)``     — per-Connection poll
- ``ingest_drive_file(ws_id, token_id, file_id)`` — one file ingest

State shape (per-resource keyed)::

    {
      "streams": {
        "<file_id>":   {"file_modified_time": "...", "last_synced_at": "..."},
        "<folder_id>": {"folder_change_token": "...", "last_synced_at": "..."}
      },
      "global": {
        "drive_change_token": "...",
        "cold_start_done":    true
      }
    }

See plans/08b-google-drive-integration.md.
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

from .adapter import BINARY_MIMES, GOOGLE_EXPORT_MIMES


logger = logging.getLogger(__name__)


# ─── Per-file ingest ─────────────────────────────────────────────────────────
@shared_task(name="integrations.google.drive.ingest_file", bind=True)
def ingest_drive_file(
    self,
    workspace_id: str,
    token_id: str,
    file_id: str,
) -> dict:
    """Fetch metadata + (optional) text + bytes; upsert DeliveryPackage."""
    from donna.authentication.models import OAuthToken
    from donna.integrations.models import DeliveryPackage

    provider_cls = get_provider("drive")
    provider = provider_cls()

    try:
        token = OAuthToken.objects.get(id=token_id)
    except OAuthToken.DoesNotExist:
        logger.warning(
            "drive_ingest_token_missing",
            extra={"token_id": token_id, "file_id": file_id},
        )
        return {"skipped": "token_missing"}

    exported_text = ""
    binary_bytes: bytes | None = None

    with provider.client(token) as client:
        file_meta = client.get_file(file_id)
        mime = file_meta.get("mimeType")

        export_mime = GOOGLE_EXPORT_MIMES.get(mime)
        if export_mime:
            try:
                exported_text = client.export_file(file_id, export_mime).decode(
                    "utf-8", errors="replace"
                )
            except Exception as exc:                   # noqa: BLE001
                logger.warning(
                    "drive_export_failed",
                    extra={"file_id": file_id, "mime": mime, "error": str(exc)},
                )
        elif mime in BINARY_MIMES:
            try:
                binary_bytes = client.download_file_media(file_id)
            except Exception as exc:                   # noqa: BLE001
                logger.warning(
                    "drive_download_failed",
                    extra={"file_id": file_id, "mime": mime, "error": str(exc)},
                )

    raw = {"file": file_meta, "exported_text": exported_text}
    adapter = provider.adapter_for(raw)

    # Storage layout: metadata + (optional) text + (optional) binary.
    storage_key = f"{workspace_id}/google/drive/files/{file_id}.json"
    if default_storage.exists(storage_key):
        default_storage.delete(storage_key)
    default_storage.save(
        storage_key,
        ContentFile(json.dumps(adapter.to_json()).encode()),
    )
    if exported_text:
        text_key = f"{workspace_id}/google/drive/files/{file_id}.txt"
        if default_storage.exists(text_key):
            default_storage.delete(text_key)
        default_storage.save(text_key, ContentFile(exported_text.encode()))
    if binary_bytes is not None:
        bin_key = f"{workspace_id}/google/drive/files/{file_id}.bin"
        if default_storage.exists(bin_key):
            default_storage.delete(bin_key)
        default_storage.save(bin_key, ContentFile(binary_bytes))

    package, created = DeliveryPackage.objects.update_or_create(
        workspace_id=workspace_id,
        provider="drive",
        provider_item_id=adapter.external_id(),
        defaults={
            "provider_item_type": "drive_file",
            "title":              adapter.title(),
            "occurred_at":        adapter.occurred_at(),
            "storage_key":        storage_key,
            "metadata":           adapter.metadata(),
        },
    )

    logger.info(
        "drive_file_ingested",
        extra={
            "workspace_id":        workspace_id,
            "file_id":             file_id,
            "mime":                file_meta.get("mimeType"),
            "delivery_package_id": str(package.id),
            "created":             created,
            "has_text":            bool(exported_text),
            "has_binary":          binary_bytes is not None,
        },
    )
    return {
        "delivery_package_id": str(package.id),
        "created":             created,
    }


# ─── Per-Connection poll ─────────────────────────────────────────────────────
@shared_task(name="integrations.google.drive.sync_connection", bind=True)
def sync_drive_connection(self, connection_id: str) -> dict:
    """Poll one Drive Connection; dispatch by ``config.mode``."""
    from donna.integrations.models import Connection

    with transaction.atomic():
        conn = (
            Connection.objects
            .select_for_update()
            .select_related("token")
            .get(id=connection_id, provider_slug="drive")
        )
        if not conn.enabled:
            return {"skipped": "disabled"}

        cfg = conn.config or {}
        state = conn.state or {}

        provider_cls = get_provider("drive")
        provider = provider_cls()

        mode = cfg.get("mode")
        enqueued = 0
        with provider.client(conn.token) as client:
            if mode == "everything":
                enqueued = _sync_everything(client, conn, state)
            elif mode == "subscriptions":
                enqueued = _sync_subscriptions(client, conn, cfg)
            else:
                logger.warning(
                    "drive_sync_unknown_mode",
                    extra={"connection_id": connection_id, "mode": mode},
                )
                return {"skipped": "unknown_mode"}

        state.setdefault("global", {})["cold_start_done"] = True
        state["global"]["last_synced_at"] = datetime.now(tz=timezone.utc).isoformat()
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
        "drive_sync_connection_completed",
        extra={
            "connection_id": connection_id,
            "workspace_id":  str(conn.workspace_id),
            "mode":          mode,
            "enqueued":      enqueued,
        },
    )
    return {"enqueued": enqueued, "mode": mode}


# ─── Mode dispatchers ────────────────────────────────────────────────────────
def _sync_everything(client, conn, state: dict) -> int:
    """Walk ``changes.list`` for the whole drive."""
    g = state.setdefault("global", {})
    page_token = g.get("drive_change_token")
    if not page_token:
        page_token = client.get_changes_start_token()
        g["drive_change_token"] = page_token

    enqueued = 0
    for change in client.iter_changes(page_token, include_corpora="allDrives"):
        if change.get("removed"):
            continue
        file = change.get("file") or {}
        fid = change.get("fileId") or file.get("id")
        if not fid:
            continue
        # Skip folders; they aren't ingested as items, only their descendants.
        if file.get("mimeType") == "application/vnd.google-apps.folder":
            continue
        ingest_drive_file.delay(str(conn.workspace_id), str(conn.token_id), str(fid))
        enqueued += 1

    new_token = getattr(client, "last_change_token", None)
    if new_token:
        g["drive_change_token"] = new_token
    return enqueued


def _sync_subscriptions(client, conn, cfg: dict) -> int:
    """Walk individual file subs + recursive folder subs."""
    enqueued = 0
    for fid in cfg.get("files") or []:
        ingest_drive_file.delay(str(conn.workspace_id), str(conn.token_id), str(fid))
        enqueued += 1
    for folder in cfg.get("folders") or []:
        for fid in client.iter_folder_descendants(
            folder["id"], recursive=folder.get("recursive", True)
        ):
            ingest_drive_file.delay(
                str(conn.workspace_id), str(conn.token_id), str(fid)
            )
            enqueued += 1
    return enqueued


# ─── Beat fanout ─────────────────────────────────────────────────────────────
@shared_task(name="integrations.google.drive.fanout_sync", bind=True)
def fanout_drive_sync(self) -> dict:
    """Beat-triggered top-level task — enqueue per-Connection sync."""
    from donna.integrations.models import Connection

    conn_ids = list(
        Connection.objects
        .filter(provider_slug="drive", enabled=True)
        .values_list("id", flat=True)
    )
    for cid in conn_ids:
        sync_drive_connection.delay(str(cid))

    logger.info(
        "drive_fanout_sync_completed",
        extra={"connections": len(conn_ids)},
    )
    return {"connections": len(conn_ids)}
