"""Connect-time ingest notifications — signal-driven, connector-agnostic.

A single ``post_save(DeliveryPackage)`` receiver drives two user-facing beats
for the source → bronze → cortex pipeline, with **no per-connector code** (and
so webhook CDC ingests notify too, not just backfills):

- **started** — an ``info`` alert on the first item of a batch ("Importing your
  Fathom meetings…").
- **rollup**  — a ``success`` summary once the ingest stream settles ("Imported
  26 meetings into memory — cortex updated"). Cortex is built inline per item
  (``CortexPipeline().write`` inside each ingest task), so the rollup truthfully
  covers both ingest and cortex.

The rollup is **debounced**: async fan-out has no natural "last item" event, so
each ingested item bumps a Redis counter and (re)schedules
``emit_ingest_rollup_if_settled`` with a countdown. Only the last item — whose
captured sequence still matches the live counter when its task fires — emits;
the rest no-op. Connector-agnostic, one generic task, no chord.

Message text is a **dynamic form**: ``PROVIDER_LABELS`` / ``KIND_PLURAL`` maps
turn ``(provider, item_type)`` into human copy, with derived fallbacks.

Wired in ``IntegrationsConfig.ready()`` (connects the signal + registers the task).
"""
from __future__ import annotations

import logging

from celery import shared_task

from donna.core.cache import redis_manager

logger = logging.getLogger(__name__)

#: Seconds of ingest silence before the rollup is considered settled. Must
#: exceed the inter-item gap of a live batch (Fathom staggers 6s/item; Gmail is
#: near-instant) so the summary fires once, after the stream ends.
DEBOUNCE_SECONDS = 30

#: Dynamic message form — provider + item-type → human copy. Unknown keys fall
#: back to derived defaults, so a new connector needs no entry here to work.
PROVIDER_LABELS = {"gmail": "Gmail", "fathom": "Fathom", "drive": "Google Drive"}
KIND_PLURAL = {
    "email": "emails",
    "meeting": "meetings",
    "file": "files",
    "document": "documents",
    "message": "messages",
}


def _label(provider: str) -> str:
    return PROVIDER_LABELS.get(provider, provider.replace("_", " ").title())


def _kind(item_type: str) -> str:
    return KIND_PLURAL.get(item_type, f"{item_type}s")


def _count_key(workspace_id: str, provider: str, item_type: str) -> str:
    return f"ingest:count:{workspace_id}:{provider}:{item_type}"


def _resolve_user_id(workspace_id: str, provider: str):
    """The connecting user — owner/audit for the WORKSPACE-scoped alert."""
    from donna.integrations.models import Connection

    conn = (
        Connection.objects
        .filter(workspace_id=workspace_id, provider_slug=provider)
        .order_by("created_at")
        .only("user_id")
        .first()
    )
    return str(conn.user_id) if conn and conn.user_id else None


def _emit(
    *,
    workspace_id: str,
    provider: str,
    title: str,
    message: str,
    notification_type: str,
    event: str,
    extra: dict | None = None,
) -> None:
    from donna.notifications.models import NotificationScope
    from donna.notifications.services import NotificationService
    from donna.users.models import User
    from donna.workspaces.models import Workspace

    user_id = _resolve_user_id(workspace_id, provider)
    if not user_id:
        logger.warning(
            "ingest_notify_skipped_no_user",
            extra={"workspace_id": workspace_id, "provider": provider, "event": event},
        )
        return
    try:
        user = User.objects.get(id=user_id)
        workspace = Workspace.objects.get(id=workspace_id)
    except (User.DoesNotExist, Workspace.DoesNotExist):
        logger.warning(
            "ingest_notify_skipped_missing_row",
            extra={"workspace_id": workspace_id, "provider": provider, "event": event},
        )
        return

    NotificationService.create_alert(
        user=user,
        title=title,
        message=message,
        notification_type=notification_type,
        data={"event": event, "provider": provider, **(extra or {})},
        workspace=workspace,
        scope=NotificationScope.WORKSPACE,
    )


def on_delivery_package_ingested(sender, instance, created, **kwargs) -> None:
    """``post_save(DeliveryPackage)`` — emit 'started' + schedule the rollup.

    Notification failures must never break ingest, so all Redis/DB work here is
    defensive. Connected in ``IntegrationsConfig.ready()``.
    """
    if not created:
        return
    workspace_id = str(instance.workspace_id)
    provider = instance.provider
    item_type = instance.provider_item_type
    try:
        client = redis_manager.get_sync_client()
        key = _count_key(workspace_id, provider, item_type)
        seq = client.incr(key)
        client.expire(key, 3600)
    except Exception:  # noqa: BLE001 — never let notifications break ingest
        logger.warning("ingest_notify_counter_failed", exc_info=True)
        return

    if seq == 1:
        _emit(
            workspace_id=workspace_id,
            provider=provider,
            title=f"Importing {_label(provider)}",
            message=f"Importing your {_label(provider)} {_kind(item_type)} into memory…",
            notification_type="info",
            event="ingest_started",
            extra={"item_type": item_type},
        )

    emit_ingest_rollup_if_settled.apply_async(
        (workspace_id, provider, item_type, seq),
        countdown=DEBOUNCE_SECONDS,
    )


@shared_task(name="integrations.notify_ingest_rollup_if_settled")
def emit_ingest_rollup_if_settled(workspace_id, provider, item_type, seq_at_schedule):
    """Debounce tail — emit the rollup only if no new item landed in the window.

    Each ingested item reschedules this; only the last one (captured seq still
    matches the live counter) emits, the rest no-op. Count is read live off the
    counter, so it's accurate regardless of individual ingest outcomes.
    """
    try:
        client = redis_manager.get_sync_client()
        key = _count_key(workspace_id, provider, item_type)
        current = int(client.get(key) or 0)
    except Exception:  # noqa: BLE001
        logger.warning("ingest_rollup_counter_failed", exc_info=True)
        return {"settled": False, "error": True}

    if current != seq_at_schedule:
        # A newer item arrived after this task was scheduled — its own
        # (later) task carries the rollup. This one is stale; no-op.
        return {"settled": False, "current": current, "scheduled_at": seq_at_schedule}

    _emit(
        workspace_id=workspace_id,
        provider=provider,
        title=f"{_label(provider)} imported",
        message=(
            f"Imported {current} {_kind(item_type)} into memory — cortex updated."
            if current
            else f"No new {_label(provider)} {_kind(item_type)} to import."
        ),
        notification_type="success",
        event="ingest_rollup",
        extra={"item_type": item_type, "count": current},
    )
    try:
        client.delete(key)  # close the batch so the next connect re-emits 'started'
    except Exception:  # noqa: BLE001
        pass
    return {"settled": True, "count": current}
