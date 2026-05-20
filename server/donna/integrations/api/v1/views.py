"""
IntegrationViewSet — list, retrieve, connect, disconnect.

Header-tenanted (uses ``request.workspace`` set by WorkspaceMiddleware).
The webhook + OAuth callback endpoints live in sibling modules ``webhooks.py``
and ``oauth.py`` because they're public (not tenanted) and need different
permission classes.

Per plans/03-conventions-and-api.md, the ``integrations`` app intentionally
violates the "every ViewSet sets service_class" convention. The OAuth lifecycle
goes through ``RegistryService``; list/retrieve are inline.
"""
from __future__ import annotations

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response

from donna.core.integrations import (
    NotConfigured,
    ProviderNotRegistered,
    all_loaded,
)

from ...services import RegistryService
from .serializers import ConnectResponseSerializer, IntegrationStatusSerializer


class IntegrationViewSet(viewsets.ViewSet):
    """
    Header-tenanted integration endpoints.

    list:      GET    /api/v1/integrations
    retrieve:  GET    /api/v1/integrations/{slug}
    connect:   POST   /api/v1/integrations/{slug}/connect
    disconnect:POST   /api/v1/integrations/{slug}/disconnect
    """

    # We don't use a ModelSerializer here — the resource is an in-memory DTO
    # built from the registry + DB lookups.
    lookup_field = "slug"
    lookup_value_regex = r"[a-z0-9_-]+"

    # ── Helpers ─────────────────────────────────────────────────────────────
    def _service(self) -> RegistryService:
        return RegistryService(
            current_user=self.request.user,
            company=self.request.workspace,
        )

    def _require_workspace(self):
        workspace = getattr(self.request, "workspace", None)
        if workspace is None:
            raise PermissionDenied("X-Workspace-Id header required")
        return workspace

    # ── list ────────────────────────────────────────────────────────────────
    def list(self, request, *args, **kwargs):
        workspace = self._require_workspace()
        statuses = self._service().list_for_workspace(workspace)
        data = IntegrationStatusSerializer(statuses, many=True).data
        return Response(data)

    # ── retrieve ────────────────────────────────────────────────────────────
    def retrieve(self, request, slug=None, *args, **kwargs):
        workspace = self._require_workspace()
        try:
            status_dto = self._service().get_status(workspace, slug)
        except ProviderNotRegistered as exc:
            raise NotFound(str(exc))
        return Response(IntegrationStatusSerializer(status_dto).data)

    # ── connect ─────────────────────────────────────────────────────────────
    @action(detail=True, methods=["post"], url_path="connect")
    def connect(self, request, slug=None, *args, **kwargs):
        workspace = self._require_workspace()
        try:
            url = self._service().initiate_connect(
                workspace=workspace,
                user=request.user,
                slug=slug,
                redirect_to=request.data.get("redirect_to") if hasattr(request, "data") else None,
            )
        except ProviderNotRegistered as exc:
            raise NotFound(str(exc))
        except NotConfigured as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(ConnectResponseSerializer({"authorize_url": url}).data)

    # ── disconnect ──────────────────────────────────────────────────────────
    @action(detail=True, methods=["post"], url_path="disconnect")
    def disconnect(self, request, slug=None, *args, **kwargs):
        workspace = self._require_workspace()
        try:
            removed = self._service().disconnect(
                workspace=workspace, user=request.user, slug=slug
            )
        except ProviderNotRegistered as exc:
            raise NotFound(str(exc))
        if not removed:
            raise NotFound(f"no active connection for {slug!r}")
        return Response(status=status.HTTP_204_NO_CONTENT)
