"""
AuditLog — append-only record of workspace / channel / membership events.

Written by service-layer mutations via
:meth:`donna.audit.services.AuditService.record`. There is no public
HTTP write path; the log is queried (admin, dashboards, internal
tooling) directly.
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from donna.core.db.models import TimestampsMixin
from donna.workspaces.models import Workspace


class AuditLog(TimestampsMixin):
    """One row per auditable event.

    Fields:
    - ``actor``       — User who performed the action (nullable for
                         system events).
    - ``workspace``   — Workspace the action took place in (nullable
                         for cross-workspace / pre-workspace events).
    - ``action``      — Dotted action key, e.g.
                         ``workspace.invitation.created``,
                         ``channel.member.added``,
                         ``workspace.member.role_changed``.
    - ``target_type`` — Class name of the affected object
                         (``WorkspaceInvitation``, ``Channel``, ...).
    - ``target_id``   — String PK of the target object.
    - ``context``     — Free-form JSON payload with action-specific
                         details (old/new values, peer IDs, etc.).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_entries",
    )
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_entries",
    )
    action = models.CharField(max_length=64)
    target_type = models.CharField(max_length=64, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    context = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "audit_logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["workspace", "-created_at"]),
            models.Index(fields=["actor", "-created_at"]),
            models.Index(fields=["action"]),
            models.Index(fields=["target_type", "target_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.action} by {self.actor_id} on {self.target_type}:{self.target_id}"
