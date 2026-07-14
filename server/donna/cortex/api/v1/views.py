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


def _sign(key: str) -> str | None:
    """Best-effort presigned URL for a storage key (None on failure)."""
    from django.core.files.storage import default_storage

    try:
        return default_storage.url(key)
    except Exception:  # noqa: BLE001
        return None


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
        payload = card.as_dict()
        # Sign the bronze (raw source) URL lazily — only on detail open, not
        # per-row in the list. Body itself is served inline via ``body_md``
        # (authed, no cross-origin S3 fetch).
        bronze_key = payload.pop("bronze_storage_key", "") or ""
        payload["bronze_url"] = _sign(bronze_key) if bronze_key else None
        return Response(payload)

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

    @action(detail=False, methods=["get"], url_path="files")
    def files(self, request):
        """``GET /cortex/entities/files/?q=&type=&relationship=&cursor=&limit=``

        Paginated list of cortex entities surfaced as files for the
        Slack-files-style browser. Filter by ``type`` (meeting/email/doc/
        person/org/project/...) and, for ``type=org``, by ``relationship``
        (client/vendor/peer/self). Returns lightweight header cards only —
        **no signed URLs**; the body + raw-source link are signed lazily on
        detail open (``retrieve``) so a 200-row list doesn't sign 200 S3 URLs.
        """
        from donna.cortex.models import CortexEntity

        workspace = getattr(request, "workspace", None)
        if workspace is None:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        q = (request.query_params.get("q") or "").strip()
        type_filter = (request.query_params.get("type") or "").strip()
        relationship = (request.query_params.get("relationship") or "").strip()
        related_to = (request.query_params.get("related_to") or "").strip()
        limit = min(int(request.query_params.get("limit") or 50), 200)
        cursor = request.query_params.get("cursor")

        # Heads-only — superseded rows are hidden from the browser, same as
        # retrieval (a re-ingest with a changed body supersedes the old head).
        qs = (
            CortexEntity.objects
            .filter(workspace=workspace, superseded_by__isnull=True)
            .order_by("-occurred_at")
        )
        if type_filter:
            qs = qs.filter(type=type_filter)
        if q:
            qs = qs.filter(title__icontains=q)
        if cursor:
            qs = qs.filter(occurred_at__lt=cursor)
        if relationship:
            qs = qs.filter(extensions__relationship=relationship)
        if related_to:
            # Touchpoints: every entity that references this one via
            # ``entity_refs[]`` (the derived reverse edge — spec §4). Powers
            # "click a person/org → all its emails, meetings, docs". JSONB
            # ``@>`` containment; the value is a UUID string.
            qs = qs.filter(entity_refs__contains=[related_to])

        rows = list(qs[: limit + 1])
        next_cursor = rows[limit].occurred_at.isoformat() if len(rows) > limit else None
        rows = rows[:limit]

        items = []
        for e in rows:
            ext = e.extensions or {}
            items.append(
                {
                    "id": str(e.id),
                    "type": e.type,
                    "title": e.title,
                    "source": e.source,
                    "author": e.author,
                    "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
                    "has_bronze": bool(e.bronze_storage_key),
                    "relationship": ext.get("relationship") if e.type == "org" else None,
                    "client_id": str(e.client_id) if e.client_id else None,
                    "project_id": str(e.project_id) if e.project_id else None,
                }
            )

        return Response({"data": items, "next_cursor": next_cursor})

    @action(detail=False, methods=["get"], url_path="counts")
    def counts(self, request):
        """``GET /cortex/entities/counts/`` — per-type counts (+ an org
        relationship breakdown) via aggregate queries.

        Powers the browser sidebar without pulling a full 200-item list per
        type (which also signed an S3 URL per row). One cheap GROUP BY instead
        of ~14 body-bearing list calls.
        """
        from django.db.models import Count

        from donna.cortex.models import CortexEntity

        workspace = getattr(request, "workspace", None)
        if workspace is None:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        base = CortexEntity.objects.filter(
            workspace=workspace, superseded_by__isnull=True
        )
        by_type = {
            r["type"]: r["n"]
            for r in base.values("type").annotate(n=Count("id"))
        }
        by_relationship = {
            r["extensions__relationship"]: r["n"]
            for r in (
                base.filter(type="org")
                .values("extensions__relationship")
                .annotate(n=Count("id"))
            )
            if r["extensions__relationship"]
        }
        return Response({"by_type": by_type, "by_relationship": by_relationship})

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
