"""
Notifications app — single ``Notification`` model.

Persistent alerts surfaced in the in-app feed. Realtime delivery is
handled by ``services.NotificationService`` over Redis pubsub + SSE.

Scoped by ``(user, workspace)`` — workspace is nullable for global
events that don't belong to any tenant (e.g., "your password was
changed", "email verified successfully").
"""
from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from donna.core.db.models import TimestampsMixin

from .managers import NotificationManager


class NotificationStatus(models.TextChoices):
    INFO    = "info",    _("Info")
    WARNING = "warning", _("Warning")
    ERROR   = "error",   _("Error")
    SUCCESS = "success", _("Success")


class NotificationScope(models.TextChoices):
    """
    Where a notification was emitted — drives which SSE pubsub channel
    received it. See plans/10-realtime-layer.md.
    """
    USER              = "user",              _("User")               # personal — channel: user-{uid}-notifications
    WORKSPACE         = "workspace",         _("Workspace")          # workspace-wide — channel: workspace-{wid}-notifications
    USER_IN_WORKSPACE = "user_in_workspace", _("User in workspace")  # personal but tagged — channel: user-{uid}-workspace-{wid}-feed


class Notification(TimestampsMixin):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        db_index=True,
    )

    title = models.CharField(_("title"), max_length=255)
    message = models.TextField(_("message"))
    status = models.CharField(
        _("status"),
        max_length=50,
        choices=NotificationStatus.choices,
        default=NotificationStatus.INFO,
    )
    type = models.CharField(_("type"), max_length=50, default="info")
    seen = models.BooleanField(_("is read"), default=False)
    context = models.JSONField(_("context"), default=dict, blank=True)
    scope = models.CharField(
        _("scope"),
        max_length=32,
        choices=NotificationScope.choices,
        default=NotificationScope.USER,
        help_text=_(
            "Which SSE channel this notification was published on "
            "(see plans/10-realtime-layer.md)."
        ),
    )

    user = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="notifications",
        related_query_name="notification",
    )
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="notifications",
        related_query_name="notification",
        null=True,
        blank=True,
    )

    objects = NotificationManager()

    class Meta:
        db_table = "notifications"
        verbose_name = _("notification")
        verbose_name_plural = _("notifications")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["user", "seen"]),
            models.Index(fields=["workspace", "-created_at"]),
            models.Index(fields=["user", "workspace", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.title} → {self.user}"

    def __repr__(self):
        return f"<{self.__class__.__name__}: id={self.id} title={self.title!r}>"
