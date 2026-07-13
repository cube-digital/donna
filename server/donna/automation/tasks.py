"""Plan 13 §7.1 — Schedule Celery tasks.

``schedule_tick`` runs every minute (Celery beat), selects every
enabled Schedule whose ``next_fires_at`` is past, and fans out a
``fire_schedule`` task per row. Splitting tick / fire keeps the tick
hot path cheap and lets the per-fire work retry independently.
"""
from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from donna.automation.cron import next_fire_after
from donna.automation.models import Schedule

logger = logging.getLogger(__name__)


@shared_task(name="automation.schedule_tick")
def schedule_tick() -> dict:
    now = timezone.now()
    due = (
        Schedule.objects
        .filter(enabled=True, next_fires_at__lte=now)
        .only("id")[:200]
    )
    ids = [str(s.id) for s in due]
    for sid in ids:
        fire_schedule.delay(sid)
    return {"queued": len(ids)}


@shared_task(name="automation.fire_schedule", bind=True, max_retries=2)
def fire_schedule(self, schedule_id: str) -> dict:
    try:
        schedule = (
            Schedule.objects.select_related("agent_session", "agent_session__channel")
            .get(id=schedule_id)
        )
    except Schedule.DoesNotExist:
        return {"id": schedule_id, "skipped": "missing"}

    if not schedule.enabled:
        return {"id": schedule_id, "skipped": "disabled"}

    payload = schedule.payload or {}
    body = payload.get("body") or f"[schedule:{schedule.name}]"
    # Synthetic message into the bound channel. The agent runner picks
    # it up via the normal run_agent_turn entrypoint — no new code path.
    from donna.chat.services import send_synthetic_agent_message

    try:
        send_synthetic_agent_message(
            channel=schedule.agent_session.channel,
            agent_session=schedule.agent_session,
            body=body,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("fire_schedule_failed", extra={
            "schedule_id": schedule_id, "detail": str(exc),
        })
        raise self.retry(exc=exc, countdown=30)

    now = timezone.now()
    try:
        nxt = next_fire_after(schedule.cron, now)
    except ValueError:
        nxt = None
        logger.warning("schedule_cron_unparseable", extra={
            "schedule_id": schedule_id, "cron": schedule.cron,
        })
    schedule.last_fired_at = now
    schedule.next_fires_at = nxt
    schedule.save(update_fields=["last_fired_at", "next_fires_at", "updated_at"])
    return {"id": schedule_id, "fired_at": now.isoformat()}
