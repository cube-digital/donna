"""
AuditService — single entry point for recording audit events.

Used from service-layer mutations across the codebase (workspaces,
chat, future apps). Failure to record is logged but does not propagate
— audit must never fail the user-visible action.
"""
from __future__ import annotations

import logging
from typing import Any

from .models import AuditLog


logger = logging.getLogger(__name__)


class AuditService:
    @staticmethod
    def record(
        *,
        action: str,
        actor=None,
        workspace=None,
        target=None,
        context: dict[str, Any] | None = None,
    ) -> AuditLog | None:
        """
        Persist an audit entry. Returns the row, or ``None`` on failure.

        ``action``    — dotted key, e.g. ``workspace.invitation.created``.
        ``actor``     — User who performed the action (or ``None``).
        ``workspace`` — :class:`Workspace` the action took place in (or
                        ``None`` for events without workspace context).
        ``target``    — affected object (any Django model instance); its
                        ``__class__.__name__`` and PK are captured.
        ``context``   — free-form JSON payload.

        Audit writes are best-effort: any exception is logged and
        swallowed so the caller's user-visible flow isn't broken by
        audit infrastructure issues.
        """
        target_type = ""
        target_id = ""
        if target is not None:
            target_type = target.__class__.__name__
            pk = getattr(target, "pk", None)
            target_id = str(pk) if pk is not None else ""

        try:
            return AuditLog.objects.create(
                actor=actor,
                workspace=workspace,
                action=action,
                target_type=target_type,
                target_id=target_id,
                context=context or {},
            )
        except Exception as exc:                  # noqa: BLE001
            logger.error(
                "audit_record_failed",
                extra={
                    "action": action,
                    "actor_id": str(getattr(actor, "id", None)) if actor else None,
                    "workspace_id": str(getattr(workspace, "id", None)) if workspace else None,
                    "target_type": target_type,
                    "target_id": target_id,
                    "error": str(exc),
                },
            )
            return None
