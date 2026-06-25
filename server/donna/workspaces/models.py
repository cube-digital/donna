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

    # Primary email domain of the workspace owner. Used by the cortex
    # org-relationship classifier to detect ``relationship=self`` when
    # an org with the same domain is spawned. Bootstrapped at onboarding
    # (or inferred from owner's email). See docs/important-docs/00m.
    primary_domain = models.CharField(max_length=255, blank=True, default="")

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


class WorkspaceInvitation(TimestampsMixin):
    """Email-based workspace invite.

    Token signed with Django's signing module + per-row id; revoking is a
    soft update (status=revoked) so accept attempts after revocation see
    a clean error instead of "no such invite".
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        REVOKED = "revoked", "Revoked"
        EXPIRED = "expired", "Expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="invitations",
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sent_invitations",
    )
    email = models.EmailField()
    role = models.CharField(
        max_length=32,
        choices=WorkspaceMembership.Role.choices,
        default=WorkspaceMembership.Role.MEMBER,
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="accepted_invitations",
    )

    class Meta:
        db_table = "workspace_invitations"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "email"],
                condition=models.Q(status="pending"),
                name="uq_pending_invitation_per_email_workspace",
            ),
        ]
        indexes = [
            models.Index(fields=["email", "status"]),
            models.Index(fields=["expires_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"invite({self.email} → {self.workspace_id} as {self.role})"
