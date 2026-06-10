from __future__ import annotations

from rest_framework import permissions, status
from rest_framework.exceptions import (
    NotFound,
    PermissionDenied,
    ValidationError,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from donna.core.viewsets import ModelViewSet
from donna.workspaces.api.v1.serializers import (
    InvitationCreateSerializer,
    InvitationPreviewSerializer,
    InvitationReadSerializer,
    WorkspaceMembershipReadSerializer,
    WorkspaceMembershipWriteSerializer,
    WorkspaceReadSerializer,
    WorkspaceWriteSerializer,
)
from donna.workspaces.models import (
    Workspace,
    WorkspaceInvitation,
    WorkspaceMembership,
)
from donna.workspaces.services import (
    InvitationService,
    WorkspaceMembershipService,
    WorkspaceService,
)

ADMIN_ROLES = (
    WorkspaceMembership.Role.OWNER,
    WorkspaceMembership.Role.ADMIN,
)


def _user_has_role(user, workspace, roles) -> bool:
    if workspace is None or not getattr(user, "is_authenticated", False):
        return False
    return WorkspaceMembership.objects.filter(
        workspace=workspace, user=user, role__in=roles
    ).exists()


class IsWorkspaceMember(permissions.BasePermission):
    """Caller must be a member of ``request.workspace`` (or the target Workspace object)."""

    def has_permission(self, request, view):
        workspace = getattr(request, "workspace", None)
        if workspace is None:
            # Endpoint isn't tenant-scoped (e.g., POST /workspaces); defer to view logic.
            return True
        return WorkspaceMembership.objects.filter(
            workspace=workspace, user=request.user
        ).exists()

    def has_object_permission(self, request, view, obj):
        target = obj if isinstance(obj, Workspace) else getattr(obj, "workspace", None)
        if target is None:
            return True
        return WorkspaceMembership.objects.filter(
            workspace=target, user=request.user
        ).exists()


class IsWorkspaceAdminOrOwner(permissions.BasePermission):
    """Caller must be ADMIN or OWNER of the active workspace (or the target Workspace)."""

    def has_permission(self, request, view):
        workspace = getattr(request, "workspace", None)
        if workspace is None:
            return True
        return _user_has_role(request.user, workspace, ADMIN_ROLES)

    def has_object_permission(self, request, view, obj):
        target = obj if isinstance(obj, Workspace) else getattr(obj, "workspace", None)
        return _user_has_role(request.user, target, ADMIN_ROLES)


class IsWorkspaceOwner(permissions.BasePermission):
    """Caller must be OWNER of the active workspace (or the target Workspace)."""

    OWNER_ROLES = (WorkspaceMembership.Role.OWNER,)

    def has_permission(self, request, view):
        workspace = getattr(request, "workspace", None)
        if workspace is None:
            return True
        return _user_has_role(request.user, workspace, self.OWNER_ROLES)

    def has_object_permission(self, request, view, obj):
        target = obj if isinstance(obj, Workspace) else getattr(obj, "workspace", None)
        return _user_has_role(request.user, target, self.OWNER_ROLES)


class WorkspaceViewSet(ModelViewSet):
    """CRUD for workspaces. Listing is always scoped to caller's memberships."""

    queryset = Workspace.objects.all()
    service_class = WorkspaceService
    read_serializer_class = WorkspaceReadSerializer
    write_serializer_class = WorkspaceWriteSerializer

    permission_classes = [permissions.IsAuthenticated]
    permission_classes_by_method = {
        "get": [permissions.IsAuthenticated, IsWorkspaceMember],
        "post": [permissions.IsAuthenticated],
        "patch": [permissions.IsAuthenticated, IsWorkspaceAdminOrOwner],
        "delete": [permissions.IsAuthenticated, IsWorkspaceOwner],
    }

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action == "list" and self.request.user.is_authenticated:
            qs = qs.filter(memberships__user=self.request.user).distinct()
        return qs


# ── Invitations ─────────────────────────────────────────────────────────────
class InvitationCreateView(APIView):
    """
    ``POST /api/v1/invitations/`` — workspace admin sends an invitation.

    This endpoint sits in :data:`WorkspaceMiddleware.IGNORED_PATHS` so
    the public preview / accept endpoints under the same prefix work
    without a tenant header. The create path therefore resolves the
    workspace and authorizes the caller itself.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        workspace_id = request.META.get("HTTP_X_WORKSPACE_ID")
        if not workspace_id:
            raise ValidationError({"X-Workspace-Id": "header required"})
        try:
            workspace = Workspace.objects.get(id=workspace_id)
        except (Workspace.DoesNotExist, ValueError, TypeError) as exc:
            raise NotFound("workspace not found") from exc

        caller_is_admin = WorkspaceMembership.objects.filter(
            workspace=workspace,
            user=request.user,
            role__in=ADMIN_ROLES,
        ).exists()
        if not caller_is_admin:
            raise PermissionDenied("workspace admin or owner required")

        serializer = InvitationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data.get("email") or ""
        role = (
            serializer.validated_data.get("role")
            or WorkspaceMembership.Role.MEMBER
        )

        try:
            invitation = InvitationService.create(
                workspace=workspace,
                invited_by=request.user,
                email=email,
                role=role,
            )
        except ValidationError:
            raise

        return Response(
            InvitationReadSerializer(invitation).data,
            status=status.HTTP_201_CREATED,
        )


class InvitationPreviewView(APIView):
    """
    ``GET /api/v1/invitations/{token}/`` — public preview by token.

    Returns the workspace name + inviter display name so the recipient
    can decide whether to accept. No auth required (the token *is* the
    credential).
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request, token):
        try:
            invitation = InvitationService.preview(token)
        except WorkspaceInvitation.DoesNotExist as exc:
            raise NotFound("invitation not found") from exc
        # ValidationError ("invitation expired" / "no longer pending")
        # bubbles up as the standard 400 envelope.
        return Response(InvitationPreviewSerializer(invitation).data)


class InvitationAcceptView(APIView):
    """
    ``POST /api/v1/invitations/{token}/accept`` — signed-in user accepts.

    The accepting user joins the workspace at the role baked into the
    invitation. Idempotent: re-accepting (or accepting when the user is
    already a member) returns the existing membership.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, token):
        try:
            membership = InvitationService.accept(token=token, user=request.user)
        except WorkspaceInvitation.DoesNotExist as exc:
            raise NotFound("invitation not found") from exc
        return Response(
            WorkspaceMembershipReadSerializer(membership).data,
            status=status.HTTP_200_OK,
        )


class WorkspaceMembershipViewSet(ModelViewSet):
    """CRUD for memberships inside the active workspace (resolved by middleware)."""

    service_class = WorkspaceMembershipService
    read_serializer_class = WorkspaceMembershipReadSerializer
    write_serializer_class = WorkspaceMembershipWriteSerializer

    # URL identifies the membership by its user, not by the join row's PK.
    lookup_field = "user_id"
    lookup_url_kwarg = "user_id"

    permission_classes = [permissions.IsAuthenticated, IsWorkspaceMember]
    permission_classes_by_method = {
        "get": [permissions.IsAuthenticated, IsWorkspaceMember],
        "post": [permissions.IsAuthenticated, IsWorkspaceAdminOrOwner],
        "patch": [permissions.IsAuthenticated, IsWorkspaceAdminOrOwner],
        # Allow both admin-kick (IsWorkspaceAdminOrOwner) and self-leave (IsWorkspaceMember);
        # the service enforces the "last owner can't leave" rule.
        "delete": [permissions.IsAuthenticated, IsWorkspaceMember],
    }

    def get_queryset(self):
        workspace = getattr(self.request, "workspace", None)
        if workspace is None:
            return WorkspaceMembership.objects.none()
        return (
            WorkspaceMembership.objects.filter(workspace=workspace)
            .select_related("user")
        )
