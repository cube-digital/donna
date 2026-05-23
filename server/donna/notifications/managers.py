"""Custom manager methods for the Notification model."""
from __future__ import annotations

from django.db import models


class NotificationManager(models.Manager):
    """Convenience query methods used by the API + service layer."""

    def for_user(self, user, limit: int = 50):
        return self.filter(user=user).order_by("-created_at")[:limit]

    def for_workspace(self, workspace, limit: int = 50):
        return self.filter(workspace=workspace).order_by("-created_at")[:limit]

    def unread_for_user(self, user):
        return self.filter(user=user, seen=False).order_by("-created_at")

    def by_type(self, user, notification_type: str):
        return self.filter(user=user, type=notification_type).order_by("-created_at")

    def mark_as_read(self, user, notification_ids: list) -> int:
        return self.filter(user=user, id__in=notification_ids).update(seen=True)

    def mark_all_read(self, user) -> int:
        return self.filter(user=user, seen=False).update(seen=True)

    def set_seen(self, user, seen: bool, notification_ids: list | None = None) -> int:
        """
        Flip ``seen`` for ``user``'s rows. ``notification_ids`` empty/None
        applies to ALL of the user's rows currently not matching ``seen``.
        Returns the count of rows actually changed (no-op rows excluded).
        """
        qs = self.filter(user=user)
        if notification_ids:
            qs = qs.filter(id__in=notification_ids)
        return qs.exclude(seen=seen).update(seen=seen)
