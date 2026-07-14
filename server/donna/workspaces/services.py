from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.exceptions import ValidationError

from donna.core.services import BaseService
from donna.workspaces.models import (
    Workspace,
    WorkspaceInvitation,
    WorkspaceMembership,
)

User = get_user_model()
logger = logging.getLogger(__name__)


_INVITE_SALT = "donna.workspaces.invitation"
_INVITE_MAX_AGE = 14 * 24 * 3600  # 14 days


class WorkspaceService(BaseService[Workspace]):
    """Workspaces are tenant roots; creation also seeds the creator's OWNER membership."""

    model_class = Workspace

    @transaction.atomic
    def create(self, data: dict[str, Any]) -> Workspace:
        if not self.current_user or not self.current_user.is_authenticated:
            raise ValidationError("Authenticated user required to create a workspace.")

        name = (data.get("name") or "").strip()
        if not name:
            raise ValidationError({"name": "Workspace name is required."})

        slug = data.get("slug") or self._generate_unique_slug(name)

        workspace = Workspace.objects.create(
            name=name,
            slug=slug,
            created_by=self.current_user,
            modified_by=self.current_user,
        )
        WorkspaceMembership.objects.create(
            workspace=workspace,
            user=self.current_user,
            role=WorkspaceMembership.Role.OWNER,
        )
        return workspace

    def update(self, instance: Workspace, data: dict[str, Any]) -> Workspace:
        if self.current_user and self.current_user.is_authenticated:
            data = {**data, "modified_by": self.current_user}
        return super().update(instance, data)

    @staticmethod
    def _generate_unique_slug(base_name: str) -> str:
        base = slugify(base_name)[:80] or "workspace"
        candidate = base
        counter = 2
        while Workspace.objects.filter(slug=candidate).exists():
            suffix = f"-{counter}"
            candidate = f"{base[: 80 - len(suffix)]}{suffix}"
            counter += 1
        return candidate


class WorkspaceMembershipService(BaseService[WorkspaceMembership]):
    """Memberships are always scoped to ``self.company`` (the active workspace)."""

    model_class = WorkspaceMembership

    @transaction.atomic
    def create(self, data: dict[str, Any]) -> WorkspaceMembership:
        if self.company is None:
            raise ValidationError("Workspace context required (X-Workspace-Id).")

        user = self._resolve_user(data.get("user_id"))
        role = data.get("role") or WorkspaceMembership.Role.MEMBER

        if role == WorkspaceMembership.Role.OWNER:
            raise ValidationError(
                {"role": "Cannot invite directly as OWNER. Use role change for ownership transfer."}
            )

        try:
            return WorkspaceMembership.objects.create(
                workspace=self.company,
                user=user,
                role=role,
            )
        except IntegrityError:
            raise ValidationError("User is already a member of this workspace.")

    @transaction.atomic
    def update(
        self, instance: WorkspaceMembership, data: dict[str, Any]
    ) -> WorkspaceMembership:
        new_role = data.get("role")
        if new_role is None or new_role == instance.role:
            return instance

        if new_role == WorkspaceMembership.Role.OWNER:
            # Ownership transfer — demote any existing owners to admin atomically.
            WorkspaceMembership.objects.filter(
                workspace=instance.workspace,
                role=WorkspaceMembership.Role.OWNER,
            ).exclude(pk=instance.pk).update(role=WorkspaceMembership.Role.ADMIN)
        elif instance.role == WorkspaceMembership.Role.OWNER:
            # Demoting the last owner would leave the workspace without one.
            self._refuse_if_last_owner(instance)

        instance.role = new_role
        instance.save(update_fields=["role", "updated_at"])
        return instance

    def delete(self, instance: WorkspaceMembership) -> bool:
        if instance.role == WorkspaceMembership.Role.OWNER:
            self._refuse_if_last_owner(instance)
        instance.delete()
        return True

    @staticmethod
    def _resolve_user(user_id: Any) -> User:
        if not user_id:
            raise ValidationError({"user_id": "Required."})
        try:
            return User.objects.get(id=user_id)
        except (User.DoesNotExist, ValueError):
            raise ValidationError({"user_id": "Unknown user."})

    @staticmethod
    def _refuse_if_last_owner(instance: WorkspaceMembership) -> None:
        has_other_owner = (
            WorkspaceMembership.objects.filter(
                workspace=instance.workspace,
                role=WorkspaceMembership.Role.OWNER,
            )
            .exclude(pk=instance.pk)
            .exists()
        )
        if not has_other_owner:
            raise ValidationError(
                "Cannot remove or demote the only owner. Transfer ownership first."
            )


# ── Workspace invitations (email-based) ────────────────────────────────────
class WorkspaceInvitationService(BaseService[WorkspaceInvitation]):
    """Send + manage email-based workspace invitations.

    Tokens are short-lived (default 14d), signed via Django's signing
    framework, and carry only the invitation id. The DB row is the
    source of truth — status changes (revoke/accept/expire) take effect
    immediately regardless of an unredeemed token in the wild.

    ``create``/``delete``/``update`` follow the ``ModelViewSet`` contract
    so the standard ``service_class`` plumbing in ``InvitationViewSet``
    works without overrides. ``delete`` is a soft revoke — the row stays
    so accept attempts after revocation get a clean error.
    """

    model_class = WorkspaceInvitation

    @transaction.atomic
    def create(self, data: dict[str, Any]) -> WorkspaceInvitation:
        if self.company is None:
            raise ValidationError("Workspace context required (X-Workspace-Id).")
        if not (self.current_user and self.current_user.is_authenticated):
            raise ValidationError("Authenticated user required to send invitations.")

        email = (data.get("email") or "").strip().lower()
        if not email:
            raise ValidationError({"email": "Required."})
        role = data.get("role") or WorkspaceMembership.Role.MEMBER
        if role == WorkspaceMembership.Role.OWNER:
            raise ValidationError({"role": "Cannot invite as OWNER."})

        # Already a member?
        already_member = (
            WorkspaceMembership.objects
            .filter(workspace=self.company, user__email__iexact=email)
            .exists()
        )
        if already_member:
            raise ValidationError({"email": "User is already a member."})

        # Revoke any existing pending invite for (workspace, email).
        WorkspaceInvitation.objects.filter(
            workspace=self.company,
            email=email,
            status=WorkspaceInvitation.Status.PENDING,
        ).update(status=WorkspaceInvitation.Status.REVOKED)

        invite = WorkspaceInvitation.objects.create(
            workspace=self.company,
            invited_by=self.current_user,
            email=email,
            role=role,
            expires_at=timezone.now() + timedelta(seconds=_INVITE_MAX_AGE),
        )
        token = self._sign_token(invite)
        self._send_email(invite, token)
        return invite

    def update(
        self, instance: WorkspaceInvitation, data: dict[str, Any]
    ) -> WorkspaceInvitation:
        # Invitations are immutable; PATCH/PUT not exposed by the viewset.
        raise ValidationError("Invitations are immutable; revoke + recreate instead.")

    @transaction.atomic
    def delete(self, instance: WorkspaceInvitation) -> bool:
        """Soft-revoke (status flips to REVOKED) so accept attempts see it."""
        if instance.status == WorkspaceInvitation.Status.PENDING:
            instance.status = WorkspaceInvitation.Status.REVOKED
            instance.save(update_fields=["status", "updated_at"])
        return True

    @transaction.atomic
    def resend(self, instance: WorkspaceInvitation) -> WorkspaceInvitation:
        """Re-send a pending invite: extend the TTL + re-deliver the email."""
        if instance.status != WorkspaceInvitation.Status.PENDING:
            raise ValidationError("Only pending invitations can be resent.")
        instance.expires_at = timezone.now() + timedelta(seconds=_INVITE_MAX_AGE)
        instance.save(update_fields=["expires_at", "updated_at"])
        self._send_email(instance, self._sign_token(instance))
        return instance

    # ── Token + email helpers ───────────────────────────────────────────────
    @staticmethod
    def _sign_token(invite: WorkspaceInvitation) -> str:
        return signing.dumps({"id": str(invite.id)}, salt=_INVITE_SALT)

    @staticmethod
    def verify_token(token: str) -> WorkspaceInvitation:
        try:
            data = signing.loads(token, salt=_INVITE_SALT, max_age=_INVITE_MAX_AGE)
        except signing.SignatureExpired as exc:
            raise ValidationError("invitation token expired") from exc
        except signing.BadSignature as exc:
            raise ValidationError("invitation token invalid") from exc
        try:
            invite = WorkspaceInvitation.objects.select_related("workspace", "invited_by").get(
                id=data["id"]
            )
        except WorkspaceInvitation.DoesNotExist as exc:
            raise ValidationError("invitation not found") from exc
        if invite.status == WorkspaceInvitation.Status.REVOKED:
            raise ValidationError("invitation revoked")
        if invite.status == WorkspaceInvitation.Status.ACCEPTED:
            raise ValidationError("invitation already accepted")
        if invite.expires_at < timezone.now():
            if invite.status == WorkspaceInvitation.Status.PENDING:
                invite.status = WorkspaceInvitation.Status.EXPIRED
                invite.save(update_fields=["status", "updated_at"])
            raise ValidationError("invitation expired")
        return invite

    @transaction.atomic
    def accept(self, *, token: str, accepting_user) -> WorkspaceMembership:
        invite = self.verify_token(token)
        if (accepting_user.email or "").lower() != invite.email.lower():
            raise ValidationError(
                "invitation email does not match logged-in user"
            )
        membership, _ = WorkspaceMembership.objects.get_or_create(
            workspace=invite.workspace,
            user=accepting_user,
            defaults={"role": invite.role},
        )
        invite.status = WorkspaceInvitation.Status.ACCEPTED
        invite.accepted_at = timezone.now()
        invite.accepted_by = accepting_user
        invite.save(update_fields=["status", "accepted_at", "accepted_by", "updated_at"])
        self._send_accept_email(invite, accepting_user)
        return membership

    # ── Email send ──────────────────────────────────────────────────────────
    def _send_email(self, invite: WorkspaceInvitation, token: str) -> None:
        base = getattr(settings, "FRONTEND_BASE_URL", "").rstrip("/")
        accept_url = f"{base}/invitations/{token}/accept"
        invited_by = (
            self.current_user.full_name
            or self.current_user.email
        ) if self.current_user else "A teammate"
        ctx = {
            "workspace_name": invite.workspace.name,
            "invited_by":     invited_by,
            "accept_url":     accept_url,
            "expires_at":     invite.expires_at,
        }
        subject = f"You're invited to join {invite.workspace.name} on Donna"
        try:
            html_body = render_to_string("workspaces/emails/invitation.html", ctx)
            text_body = render_to_string("workspaces/emails/invitation.txt", ctx)
            send_mail(
                subject=subject,
                message=text_body,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                recipient_list=[invite.email],
                html_message=html_body,
                fail_silently=False,
            )
        except Exception:  # noqa: BLE001 — never let SMTP failure block invite creation
            logger.exception(
                "invitation_email_send_failed",
                extra={"invitation_id": str(invite.id), "email": invite.email},
            )

    def _send_accept_email(self, invite: WorkspaceInvitation, accepting_user) -> None:
        """Welcome the member who just accepted. Best-effort — a send failure
        must never roll back the join (mirrors ``_send_email``)."""
        base = getattr(settings, "FRONTEND_BASE_URL", "").rstrip("/")
        workspace_url = f"{base}/channels"
        inviter = invite.invited_by
        invited_by = (
            (inviter.full_name or inviter.email) if inviter else "A teammate"
        )
        ctx = {
            "workspace_name": invite.workspace.name,
            "invited_by":     invited_by,
            "workspace_url":  workspace_url,
        }
        subject = f"You've joined {invite.workspace.name} on Donna"
        recipient = accepting_user.email or invite.email
        try:
            html_body = render_to_string("workspaces/emails/invitation_accepted.html", ctx)
            text_body = render_to_string("workspaces/emails/invitation_accepted.txt", ctx)
            send_mail(
                subject=subject,
                message=text_body,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                recipient_list=[recipient],
                html_message=html_body,
                fail_silently=False,
            )
        except Exception:  # noqa: BLE001 — never let SMTP failure block the join
            logger.exception(
                "invitation_accept_email_send_failed",
                extra={"invitation_id": str(invite.id), "email": recipient},
            )
