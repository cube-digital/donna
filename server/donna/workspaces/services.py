from __future__ import annotations

import logging
from typing import Any

from django.conf import settings as dj_settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.exceptions import PermissionDenied, ValidationError

from donna.audit.services import AuditService
from donna.core.services import BaseService
from donna.workspaces.models import Workspace, WorkspaceInvitation, WorkspaceMembership

User = get_user_model()

logger = logging.getLogger(__name__)


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
            membership = WorkspaceMembership.objects.create(
                workspace=self.company,
                user=user,
                role=role,
            )
        except IntegrityError:
            raise ValidationError("User is already a member of this workspace.")

        AuditService.record(
            action="workspace.member.added",
            actor=self.current_user,
            workspace=self.company,
            target=membership,
            context={"user_id": str(user.id), "role": role},
        )
        return membership

    @transaction.atomic
    def update(
        self, instance: WorkspaceMembership, data: dict[str, Any]
    ) -> WorkspaceMembership:
        new_role = data.get("role")
        if new_role is None or new_role == instance.role:
            return instance

        old_role = instance.role

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

        AuditService.record(
            action="workspace.member.role_changed",
            actor=self.current_user,
            workspace=instance.workspace,
            target=instance,
            context={
                "user_id":  str(instance.user_id),
                "old_role": old_role,
                "new_role": new_role,
            },
        )
        return instance

    def delete(self, instance: WorkspaceMembership) -> bool:
        if instance.role == WorkspaceMembership.Role.OWNER:
            self._refuse_if_last_owner(instance)
        snapshot = {
            "user_id": str(instance.user_id),
            "role":    instance.role,
        }
        workspace = instance.workspace
        instance.delete()
        AuditService.record(
            action="workspace.member.removed",
            actor=self.current_user,
            workspace=workspace,
            context=snapshot,
        )
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


class InvitationService:
    """
    Workspace invitation lifecycle — create / preview / accept.

    Two invitation flavours share the same row:
      - Invite-by-email: ``email`` is set; an email goes out with the
        accept URL.
      - Invite-by-link: ``email`` is blank; the token is shared
        out-of-band.
    """

    @staticmethod
    @transaction.atomic
    def create(
        *,
        workspace: Workspace,
        invited_by,
        email: str = "",
        role: str = WorkspaceMembership.Role.MEMBER,
    ) -> WorkspaceInvitation:
        if role == WorkspaceMembership.Role.OWNER:
            raise ValidationError(
                {"role": "Cannot invite as OWNER — transfer ownership instead."}
            )

        email_norm = (email or "").strip().lower()

        invitation = WorkspaceInvitation.objects.create(
            workspace=workspace,
            invited_by=invited_by,
            email=email_norm,
            role=role,
            # token + expires_at default to secrets.token_urlsafe(32) +
            # +7 days via model defaults.
        )

        if email_norm:
            InvitationService._send_email(invitation)

        AuditService.record(
            action="workspace.invitation.created",
            actor=invited_by,
            workspace=workspace,
            target=invitation,
            context={"email": email_norm, "role": role},
        )
        return invitation

    @staticmethod
    def preview(token: str) -> WorkspaceInvitation:
        """Return the invitation. Raises ``ValidationError`` if it's no longer usable."""
        try:
            invitation = (
                WorkspaceInvitation.objects
                .select_related("workspace", "invited_by")
                .get(token=token)
            )
        except WorkspaceInvitation.DoesNotExist as exc:
            raise WorkspaceInvitation.DoesNotExist from exc
        InvitationService._refuse_if_inactive(invitation)
        return invitation

    @staticmethod
    @transaction.atomic
    def accept(*, token: str, user) -> WorkspaceMembership:
        """Mark the invitation accepted and ensure the membership exists."""
        try:
            invitation = (
                WorkspaceInvitation.objects
                .select_for_update()
                .select_related("workspace")
                .get(token=token)
            )
        except WorkspaceInvitation.DoesNotExist as exc:
            raise WorkspaceInvitation.DoesNotExist from exc

        InvitationService._refuse_if_inactive(invitation)

        membership, created = WorkspaceMembership.objects.get_or_create(
            workspace=invitation.workspace,
            user=user,
            defaults={"role": invitation.role},
        )

        invitation.status = WorkspaceInvitation.Status.ACCEPTED
        invitation.accepted_at = timezone.now()
        invitation.accepted_by = user
        invitation.save(
            update_fields=["status", "accepted_at", "accepted_by", "updated_at"]
        )

        AuditService.record(
            action="workspace.invitation.accepted",
            actor=user,
            workspace=invitation.workspace,
            target=invitation,
            context={
                "role":               membership.role,
                "membership_created": created,
            },
        )
        return membership

    @staticmethod
    @transaction.atomic
    def revoke(*, invitation: WorkspaceInvitation, by_user) -> WorkspaceInvitation:
        if invitation.status != WorkspaceInvitation.Status.PENDING:
            raise ValidationError("only pending invitations can be revoked")
        invitation.status = WorkspaceInvitation.Status.REVOKED
        invitation.save(update_fields=["status", "updated_at"])
        AuditService.record(
            action="workspace.invitation.revoked",
            actor=by_user,
            workspace=invitation.workspace,
            target=invitation,
        )
        return invitation

    # ── Internals ───────────────────────────────────────────────────────────
    @staticmethod
    def _refuse_if_inactive(invitation: WorkspaceInvitation) -> None:
        if invitation.status != WorkspaceInvitation.Status.PENDING:
            raise ValidationError(f"invitation is {invitation.status}")
        if invitation.expires_at <= timezone.now():
            # Bookkeep — flip to EXPIRED so future reads short-circuit.
            WorkspaceInvitation.objects.filter(pk=invitation.pk).update(
                status=WorkspaceInvitation.Status.EXPIRED,
                updated_at=timezone.now(),
            )
            raise ValidationError("invitation has expired")

    @staticmethod
    def _send_email(invitation: WorkspaceInvitation) -> None:
        accept_url = (
            f"{dj_settings.WEB_REDIRECT_HOST.rstrip('/')}"
            f"/invitations/{invitation.token}"
        )
        try:
            send_mail(
                subject=f"You're invited to join {invitation.workspace.name}",
                message=(
                    f"You've been invited to join the workspace "
                    f"'{invitation.workspace.name}' on Donna.\n\n"
                    f"Accept the invitation:\n{accept_url}\n\n"
                    f"This link expires on "
                    f"{invitation.expires_at.isoformat(timespec='seconds')}."
                ),
                from_email=getattr(dj_settings, "DEFAULT_FROM_EMAIL", None),
                recipient_list=[invitation.email],
                fail_silently=True,
            )
        except Exception as exc:                # noqa: BLE001
            logger.warning(
                "invitation_email_send_failed",
                extra={"invitation_id": str(invitation.id), "error": str(exc)},
            )
