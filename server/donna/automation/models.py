"""Plan 13 §7.1 — Schedule model.

One row = one cron-driven self-trigger bound to an ``AgentSession``.
The beat task (``automation.tasks.schedule_tick``) wakes every minute,
selects due rows, and dispatches synthetic messages to the bound
agents. The fire result rolls ``last_fired_at`` + ``next_fires_at`` so
the next tick skips already-fired rows cheaply.

Why a model (not just Celery beat): per-agent listing in the UI, per-
schedule audit, payload customization without a code deploy, and a
cheap ``WHERE enabled AND next_fires_at < NOW()`` index lookup.
"""
from __future__ import annotations

import uuid

from django.db import models

from donna.core.db.models import TimestampsMixin, UserAuditMixin


class Schedule(TimestampsMixin, UserAuditMixin):
    """A cron-driven message into an agent's channel.

    ``payload`` is the synthetic message body the agent will see. Any
    JSON-serialisable shape is fine; for now the body field is required
    so the runner can post it like a regular user message.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="schedules",
    )
    agent_session = models.ForeignKey(
        "chat.AgentSession",
        on_delete=models.CASCADE,
        related_name="schedules",
    )
    name = models.CharField(max_length=120)
    cron = models.CharField(
        max_length=80,
        help_text="Standard 5-field cron (m h dom mon dow).",
    )
    timezone = models.CharField(max_length=64, default="UTC")
    payload = models.JSONField(
        default=dict, blank=True,
        help_text='{"body": "the synthetic message", ...}',
    )
    enabled = models.BooleanField(default=True)
    last_fired_at = models.DateTimeField(null=True, blank=True)
    next_fires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "automation_schedule"
        indexes = [
            models.Index(fields=["enabled", "next_fires_at"]),
            models.Index(fields=["agent_session"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.cron})"
