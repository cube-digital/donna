from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework import serializers

from donna.workspaces.models import Workspace, WorkspaceInvitation, WorkspaceMembership

User = get_user_model()


class _UserShortSerializer(serializers.ModelSerializer):
    """Lightweight User shape embedded in membership reads.

    Lives here temporarily; move to ``donna.users.api.v1.serializers`` when
    the users app is built out and import from there.
    """

    class Meta:
        model = User
        fields = ["id", "email", "full_name"]
        read_only_fields = fields


class WorkspaceReadSerializer(serializers.ModelSerializer):
    """Read shape exposes my_role so clients can branch on access without a second call."""

    my_role = serializers.SerializerMethodField()

    class Meta:
        model = Workspace
        fields = ["id", "name", "slug", "my_role", "created_at", "updated_at"]
        read_only_fields = fields

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

    name = serializers.CharField(max_length=255)
    slug = serializers.SlugField(max_length=80, required=False, allow_blank=True)

    class Meta:
        model = Workspace
        fields = ["name", "slug"]


class WorkspaceMembershipReadSerializer(serializers.ModelSerializer):
    user = _UserShortSerializer(read_only=True)

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


class InvitationCreateSerializer(serializers.Serializer):
    """Body for POST /api/v1/invitations/.

    Both fields are optional:
    - omit ``email`` for an invite-by-link (token is shared out-of-band)
    - omit ``role`` to default to MEMBER
    """

    email = serializers.EmailField(required=False, allow_blank=True)
    role = serializers.ChoiceField(
        choices=WorkspaceMembership.Role.choices,
        required=False,
    )


class InvitationReadSerializer(serializers.ModelSerializer):
    workspace_name = serializers.CharField(source="workspace.name", read_only=True)
    invited_by = _UserShortSerializer(read_only=True)

    class Meta:
        model = WorkspaceInvitation
        fields = [
            "id",
            "workspace",
            "workspace_name",
            "invited_by",
            "email",
            "role",
            "token",
            "expires_at",
            "status",
            "accepted_at",
            "created_at",
        ]
        read_only_fields = fields


class InvitationPreviewSerializer(serializers.ModelSerializer):
    """Lighter shape served by the unauthenticated preview endpoint.

    Deliberately omits the token (the caller already has it in the URL)
    and the inviter's full identity beyond display name, so a leaked
    URL leaks the *least* extra metadata.
    """

    workspace_name = serializers.CharField(source="workspace.name", read_only=True)
    invited_by_name = serializers.CharField(
        source="invited_by.full_name", read_only=True
    )

    class Meta:
        model = WorkspaceInvitation
        fields = [
            "workspace_name",
            "invited_by_name",
            "email",
            "role",
            "expires_at",
            "status",
        ]
        read_only_fields = fields
