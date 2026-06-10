from __future__ import annotations

import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

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


def _default_invitation_token() -> str:
    """secrets.token_urlsafe(32) ≈ 43 chars of URL-safe base64."""
    return secrets.token_urlsafe(32)


def _default_invitation_expiry():
    """Module-level (not a lambda) so Django migrations can serialize it."""
    return timezone.now() + timedelta(days=7)


class WorkspaceInvitation(TimestampsMixin):
    """
    Pending invitation to join a Workspace.

    Two flavours share this row:

    - **Invite by email** — ``email`` is set at creation time and an
      email is sent to that address with the accept link. The token
      is bearer-style: anyone holding it can accept after signing in.
    - **Invite by link** — ``email`` is blank; the token is shared
      out-of-band (Slack message, copy-paste).

    Tokens are validated by ``token`` lookup, not URL signing. They
    expire 7 days after creation (see ``_default_invitation_expiry``)
    and transition from ``PENDING`` to ``ACCEPTED`` / ``REVOKED`` /
    ``EXPIRED`` on the corresponding action.
    """

    class Status(models.TextChoices):
        PENDING  = "pending",  "Pending"
        ACCEPTED = "accepted", "Accepted"
        REVOKED  = "revoked",  "Revoked"
        EXPIRED  = "expired",  "Expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="invitations",
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invitations_sent",
    )
    email = models.EmailField(blank=True)  # blank → invite-by-link
    role = models.CharField(
        max_length=16,
        choices=WorkspaceMembership.Role.choices,
        default=WorkspaceMembership.Role.MEMBER,
    )
    token = models.CharField(max_length=64, unique=True, default=_default_invitation_token)
    expires_at = models.DateTimeField(default=_default_invitation_expiry)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invitations_accepted",
    )

    class Meta:
        db_table = "workspace_invitations"
        ordering = ["-created_at"]
        constraints = [
            # OWNER invitations not allowed — ownership transfer is a
            # separate code path that re-uses the existing membership
            # service.
            models.CheckConstraint(
                condition=~models.Q(role="owner"),
                name="invitation_role_not_owner",
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "status"]),
            models.Index(fields=["email", "status"]),
        ]

    def __str__(self) -> str:
        return f"invitation:{self.email or self.token[:8]}@{self.workspace_id}"

    @property
    def is_active(self) -> bool:
        return (
            self.status == self.Status.PENDING
            and self.expires_at > timezone.now()
        )
