from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils.text import slugify
from rest_framework.exceptions import ValidationError

from donna.core.services import BaseService
from donna.workspaces.models import Workspace, WorkspaceMembership

User = get_user_model()


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
