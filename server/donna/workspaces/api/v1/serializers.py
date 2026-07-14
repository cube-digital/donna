from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework import serializers

from donna.users.api.v1.serializers import UserShortSerializer
from donna.workspaces.models import (
    Workspace,
    WorkspaceInvitation,
    WorkspaceMembership,
)

User = get_user_model()


class WorkspaceReadSerializer(serializers.ModelSerializer):
    """Read shape exposes my_role so clients can branch on access without a second call."""

    my_role = serializers.SerializerMethodField()
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = Workspace
        fields = [
            "id", "name", "slug", "primary_domain", "member_count",
            "my_role", "created_at", "updated_at",
        ]
        read_only_fields = fields

    def get_member_count(self, obj: Workspace) -> int:
        return WorkspaceMembership.objects.filter(workspace=obj).count()

    def get_my_role(self, obj: Workspace) -> str | None:
        request = self.context.get("request")
        if not request or not getattr(request.user, "is_authenticated", False):
            return None
        membership = (
            WorkspaceMembership.objects.filter(workspace=obj, user=request.user)
            .only("role")
            .first()
        )
        return membership.role if membership else None


class WorkspaceWriteSerializer(serializers.ModelSerializer):
    """Write shape accepts only the fields a caller may set; slug auto-generates if omitted."""

    name = serializers.CharField(max_length=255, required=False)
    slug = serializers.SlugField(max_length=80, required=False, allow_blank=True)
    primary_domain = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )

    class Meta:
        model = Workspace
        fields = ["name", "slug", "primary_domain"]


class WorkspaceMembershipReadSerializer(serializers.ModelSerializer):
    user = UserShortSerializer(read_only=True)

    class Meta:
        model = WorkspaceMembership
        fields = ["id", "user", "role", "created_at"]
        read_only_fields = fields


class WorkspaceMembershipWriteSerializer(serializers.ModelSerializer):
    """Write shape covers both create (user_id required) and update (role only).

    ``user_id`` is enforced on create via ``validate``; on PATCH it's optional
    and ignored even if present, since a membership's user is immutable.
    """

    user_id = serializers.UUIDField(write_only=True, required=False)
    role = serializers.ChoiceField(
        choices=WorkspaceMembership.Role.choices,
        required=False,
    )

    class Meta:
        model = WorkspaceMembership
        fields = ["user_id", "role"]

    def validate(self, attrs):
        if self.instance is None and not attrs.get("user_id"):
            raise serializers.ValidationError(
                {"user_id": "Required when creating a membership."}
            )
        return attrs


# ── Invitations ─────────────────────────────────────────────────────────────
class WorkspaceInvitationReadSerializer(serializers.ModelSerializer):
    """Admin-facing — full invite metadata for the invitations list."""

    invited_by = UserShortSerializer(read_only=True)
    accept_url = serializers.SerializerMethodField()

    class Meta:
        model = WorkspaceInvitation
        fields = [
            "id",
            "email",
            "role",
            "status",
            "invited_by",
            "accept_url",
            "expires_at",
            "accepted_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_accept_url(self, obj: WorkspaceInvitation) -> str | None:
        # Copy-link — signed accept URL, only meaningful while pending.
        if obj.status != WorkspaceInvitation.Status.PENDING:
            return None
        from django.conf import settings

        from donna.workspaces.services import WorkspaceInvitationService

        base = (getattr(settings, "FRONTEND_BASE_URL", "") or "").rstrip("/")
        return f"{base}/invitations/{WorkspaceInvitationService._sign_token(obj)}/accept"


class WorkspaceInvitationWriteSerializer(serializers.ModelSerializer):
    """Create-only — caller supplies email + role; everything else server-set."""

    email = serializers.EmailField()
    role = serializers.ChoiceField(
        choices=WorkspaceMembership.Role.choices,
        required=False,
    )

    class Meta:
        model = WorkspaceInvitation
        fields = ["email", "role"]


class InvitationInspectSerializer(serializers.ModelSerializer):
    """Public preview — strips DB ids and metadata.

    Used by the accept page so the invitee sees the workspace name + who
    invited them BEFORE logging in. Nothing leaks beyond what an attacker
    could probe with the signed token anyway.
    """

    workspace_name = serializers.CharField(source="workspace.name", read_only=True)
    invited_by = serializers.SerializerMethodField()

    class Meta:
        model = WorkspaceInvitation
        fields = ["workspace_name", "email", "invited_by", "expires_at"]
        read_only_fields = fields

    def get_invited_by(self, obj):
        u = obj.invited_by
        return (u.full_name or u.email) if u else "Someone"
