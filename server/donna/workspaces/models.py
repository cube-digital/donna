from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from donna.core.db.models import TimestampsMixin, UserAuditMixin


class Workspace(TimestampsMixin, UserAuditMixin):
    """A tenant root. Multi-tenant container; users join via WorkspaceMembership."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=80, unique=True)

    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="WorkspaceMembership",
        related_name="workspaces",
    )

    class Meta:
        db_table = "workspaces"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class WorkspaceMembership(TimestampsMixin):
    """Join: User × Workspace, with role."""

    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        MEMBER = "member", "Member"
        GUEST = "guest", "Guest"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workspace_memberships",
    )
    role = models.CharField(
        max_length=16,
        choices=Role.choices,
        default=Role.MEMBER,
    )

    class Meta:
        db_table = "workspace_memberships"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "user"],
                name="uq_workspace_membership_workspace_user",
            ),
        ]
        ordering = ["workspace_id", "role"]

    def __str__(self) -> str:
        return f"{self.user_id}@{self.workspace_id} ({self.role})"
