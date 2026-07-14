from __future__ import annotations

from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet
from rest_framework_simplejwt.authentication import JWTAuthentication

from donna.core.viewsets import ModelViewSet
from donna.workspaces.api.v1.serializers import (
    InvitationInspectSerializer,
    WorkspaceInvitationReadSerializer,
    WorkspaceInvitationWriteSerializer,
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
    WorkspaceInvitationService,
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


# ── Invitations ─────────────────────────────────────────────────────────────
class WorkspaceInvitationViewSet(ModelViewSet):
    """Workspace-scoped invitation CRUD.

    Routes (registered under ``/api/v1/workspaces/invitations/``):
      GET    /                   — list ALL invitations (any status)
      POST   /                   — create + send email
      GET    /<id>/              — retrieve one
      POST   /<id>/resend/       — re-send a pending invite (extends TTL)
      DELETE /<id>/              — revoke (soft; status → REVOKED)

    PATCH/PUT not exposed — invitations are immutable except via resend/revoke.
    """

    service_class = WorkspaceInvitationService
    read_serializer_class = WorkspaceInvitationReadSerializer
    write_serializer_class = WorkspaceInvitationWriteSerializer

    http_method_names = ["get", "post", "delete", "head", "options"]

    permission_classes = [permissions.IsAuthenticated, IsWorkspaceAdminOrOwner]
    permission_classes_by_method = {
        "get":    [permissions.IsAuthenticated, IsWorkspaceAdminOrOwner],
        "post":   [permissions.IsAuthenticated, IsWorkspaceAdminOrOwner],
        "delete": [permissions.IsAuthenticated, IsWorkspaceAdminOrOwner],
    }

    def get_queryset(self):
        # Full history — the settings Invitations tab filters by status
        # (pending / accepted / revoked / expired) client-side.
        workspace = getattr(self.request, "workspace", None)
        if workspace is None:
            return WorkspaceInvitation.objects.none()
        return (
            workspace.invitations
            .select_related("invited_by")
            .order_by("-created_at")
        )

    @action(detail=True, methods=["post"], url_path="resend")
    def resend(self, request, pk=None):
        """Re-send a pending invitation (re-deliver email + extend TTL)."""
        invite = self.get_object()
        service = WorkspaceInvitationService(
            current_user=request.user, company=request.workspace
        )
        invite = service.resend(invite)
        return Response(WorkspaceInvitationReadSerializer(invite).data)


class PublicInvitationViewSet(GenericViewSet):
    """Token-based public invitation endpoints — no workspace tenancy.

    Routes (registered separately under ``/api/v1/invitations/``):
      GET  /<token>/         — retrieve (public, no auth) — accept-page preview
      POST /<token>/accept/  — accept (authenticated; email must match)
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []
    lookup_field = "token"
    lookup_value_regex = "[^/]+"
    serializer_class = InvitationInspectSerializer

    def retrieve(self, request, token=None):
        try:
            invite = WorkspaceInvitationService.verify_token(token)
        except ValidationError as exc:
            return Response(
                {"detail": _flatten_error(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(InvitationInspectSerializer(invite).data)

    @action(
        detail=True,
        methods=["post"],
        url_path="accept",
        permission_classes=[permissions.IsAuthenticated],
        # Must be an explicit list: the ViewSet disables auth (authentication_
        # classes = []) for the public token routes, and DRF iterates this
        # attribute — ``None`` raises "'NoneType' object is not iterable" in
        # initialize_request (500 on every accept).
        authentication_classes=[JWTAuthentication],
    )
    def accept(self, request, token=None):
        service = WorkspaceInvitationService(current_user=request.user, company=None)
        try:
            membership = service.accept(token=token, accepting_user=request.user)
        except ValidationError as exc:
            return Response(
                {"detail": _flatten_error(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {"workspace_id": str(membership.workspace_id), "role": membership.role},
            status=status.HTTP_200_OK,
        )

    @action(
        detail=False,
        methods=["get"],
        url_path="mine",
        permission_classes=[permissions.IsAuthenticated],
        authentication_classes=[JWTAuthentication],
    )
    def mine(self, request):
        """``GET /api/v1/invitations/mine/`` — pending invitations addressed to
        the authenticated user's email, across workspaces (no tenant context).

        Lets the workspace picker surface "you've been invited" for a user who
        signed in normally instead of via the invite link. Each item carries a
        freshly-signed accept token (tokens are signed, not stored). Expired
        rows are filtered out so we never show an un-acceptable invite.
        """
        email = (getattr(request.user, "email", "") or "").strip().lower()
        if not email:
            return Response([])
        invites = (
            WorkspaceInvitation.objects
            .filter(
                email__iexact=email,
                status=WorkspaceInvitation.Status.PENDING,
                expires_at__gt=timezone.now(),
            )
            .select_related("workspace", "invited_by")
            .order_by("-created_at")
        )
        items = []
        for inv in invites:
            data = InvitationInspectSerializer(inv).data
            data["token"] = WorkspaceInvitationService._sign_token(inv)
            items.append(data)
        return Response(items)


def _flatten_error(exc: ValidationError) -> str:
    detail = getattr(exc, "detail", str(exc))
    if isinstance(detail, list) and detail:
        return str(detail[0])
    if isinstance(detail, dict):
        for value in detail.values():
            if isinstance(value, list) and value:
                return str(value[0])
            return str(value)
    return str(detail)
