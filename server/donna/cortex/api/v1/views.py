"""Cortex HTTP API — query / read / get_context / create.

Multi-tenant via ``X-Workspace-Id`` header (resolved by
``WorkspaceMiddleware`` → ``request.workspace``). All endpoints
require an authenticated user; ``CortexService`` enforces scope.
"""
from __future__ import annotations

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from donna.cortex.services import CortexService

from .serializers import (
    CortexEntityReadSerializer,
    CortexEntityWriteSerializer,
    CortexQuerySerializer,
)


class CortexEntityViewSet(viewsets.ViewSet):
    """Cortex read + write HTTP surface (DRF)."""

    def _service(self, request) -> CortexService:
        return CortexService(
            current_user=getattr(request, "user", None),
            company=getattr(request, "workspace", None),
        )

    @action(detail=False, methods=["post"], url_path="query")
    def query(self, request):
        s = CortexQuerySerializer(data=request.data)
        s.is_valid(raise_exception=True)
        hits = self._service(request).query(**s.validated_data)
        return Response({"results": [h.summary() for h in hits]})

    def retrieve(self, request, pk=None):
        include_body = request.query_params.get("include_body", "true").lower() == "true"
        card = self._service(request).read_entity(pk, include_body=include_body)
        if card is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(card.as_dict())

    @action(detail=True, methods=["get"], url_path="context")
    def context(self, request, pk=None):
        depth = int(request.query_params.get("depth", "1"))
        cards = self._service(request).get_context(pk, depth=depth)
        return Response({"neighbors": [c.as_dict() for c in cards]})

    def create(self, request):
        s = CortexEntityWriteSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        entity = self._service(request).create_entity(**s.validated_data)
        return Response(
            CortexEntityReadSerializer(entity, context={"include_body": False}).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["patch"], url_path="scope")
    def promote_scope(self, request, pk=None):
        """PATCH scope (4c, 2026-06-15) — promote a suggested_scope
        entity to its final (client_id, project_id). Workspace-scoped,
        idempotent. Clears the ``suggested_scope`` extensions slot."""
        from donna.cortex.models import CortexEntity
        workspace = getattr(request, "workspace", None)
        if workspace is None:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        try:
            entity = CortexEntity.objects.get(id=pk, workspace_id=workspace.id)
        except CortexEntity.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        client_id = request.data.get("client_id")
        project_id = request.data.get("project_id")
        if client_id is not None:
            entity.client_id = client_id or None
        if project_id is not None:
            entity.project_id = project_id or None
        ext = dict(entity.extensions or {})
        ext.pop("suggested_scope", None)
        entity.extensions = ext
        entity.save(update_fields=[
            "client_id", "project_id", "extensions", "updated_at",
        ])
        return Response(
            CortexEntityReadSerializer(entity, context={"include_body": False}).data,
        )
