"""
View layer for the integrations API.

Header-tenanted endpoints (read ``request.workspace`` set by
``WorkspaceMiddleware``):

- ``IntegrationViewSet`` — list / retrieve / connect / disconnect
- ``ConnectionView`` — GET/PATCH/DELETE the per-binding subscription
- ``ConnectionPickerView`` — picker data feeding the subscription editor
- ``ConnectionUpgradeScopeView`` — start an OAuth re-consent with extra scopes

The webhook + OAuth callback views live in sibling modules ``webhooks.py``
and ``oauth.py`` because they're public (not tenanted) and need different
permission classes.

Per plans/03-conventions-and-api.md, the ``integrations`` app intentionally
violates the "every ViewSet sets service_class" convention. The OAuth lifecycle
goes through ``RegistryService``; list/retrieve are inline.
"""
from __future__ import annotations

import logging

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from donna.core.integrations import (
    NotConfigured,
    ProviderNotRegistered,
    all_loaded,
    get as get_provider,
)

from ...models import Connection
from ...services import RegistryService
from .serializers import (
    ConnectResponseSerializer,
    ConnectionSerializer,
    IntegrationStatusSerializer,
)


logger = logging.getLogger(__name__)


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

    # ── list ────────────────────────────────────────────────────────────────
    def list(self, request, *args, **kwargs):
        statuses = self._service().list_for_workspace(request.workspace)
        data = IntegrationStatusSerializer(statuses, many=True).data
        return Response(data)

    # ── retrieve ────────────────────────────────────────────────────────────
    def retrieve(self, request, slug=None, *args, **kwargs):
        from donna.core.integrations import get as get_provider

        try:
            status_dto = self._service().get_status(request.workspace, slug)
            cls = get_provider(slug)
        except ProviderNotRegistered as exc:
            raise NotFound(str(exc))

        # Enrich with the per-connector schema so the frontend can render
        # structured config fields. List endpoint omits these — they can be
        # several KB per connector.
        payload = IntegrationStatusSerializer(status_dto).data
        payload["token_scope"] = getattr(cls, "token_scope", None)
        payload["config_schema"] = getattr(cls, "config_schema", None) or None
        payload["default_config"] = (
            dict(getattr(cls, "default_config", {}) or {}) or None
        )
        return Response(payload)

    # ── connect ─────────────────────────────────────────────────────────────
    @action(detail=True, methods=["post"], url_path="connect")
    def connect(self, request, slug=None, *args, **kwargs):
        try:
            url = self._service().initiate_connect(
                workspace=request.workspace,
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
        try:
            removed = self._service().disconnect(
                workspace=request.workspace, user=request.user, slug=slug
            )
        except ProviderNotRegistered as exc:
            raise NotFound(str(exc))
        if not removed:
            raise NotFound(f"no active connection for {slug!r}")
        return Response(status=status.HTTP_204_NO_CONTENT)


# ─── Connection (per-binding subscription editor) ─────────────────────────────
#
# URL noun is ``subscription`` (user mental model: "subscribe to an
# integration"); the underlying model is ``Connection`` (industry-standard,
# Airbyte/Nango). See plans/08-connection-pattern.md.

def _resolve_provider(slug: str):
    """Get the connector class for ``slug`` or raise 404."""
    try:
        return get_provider(slug)
    except ProviderNotRegistered as exc:
        raise NotFound(str(exc)) from exc


def _get_connection(*, slug: str, request) -> Connection:
    """
    Fetch the Connection row for ``(workspace, user|None, slug)``. 404 if
    absent. Token scope on the connector decides whether ``user`` is part
    of the lookup (workspace-scoped connectors store ``user=None``).
    """
    cls = _resolve_provider(slug)
    user = request.user if cls.token_scope == "user" else None
    try:
        return Connection.objects.select_related("token").get(
            workspace=request.workspace,
            user=user,
            provider_slug=slug,
        )
    except Connection.DoesNotExist as exc:
        raise NotFound(
            f"no subscription for {slug!r} — connect via "
            f"POST /api/v1/integrations/{slug}/connect/ first"
        ) from exc


class ConnectionView(APIView):
    """GET / PATCH / DELETE the per-binding subscription."""

    def get(self, request, slug: str, *args, **kwargs):
        conn = _get_connection(slug=slug, request=request)
        return Response(ConnectionSerializer(conn).data)

    def patch(self, request, slug: str, *args, **kwargs):
        conn = _get_connection(slug=slug, request=request)
        cls = _resolve_provider(slug)
        provider = cls()

        config = request.data.get("config")
        if config is None or not isinstance(config, dict):
            raise ValidationError({"config": "expected a JSON object"})

        try:
            normalized = provider.validate_config(config, connection=conn)
        except ValueError as exc:
            # validate_against_schema raises ValueError; surface as DRF 400.
            raise ValidationError({"config": str(exc)}) from exc

        conn.config = normalized
        conn.save(update_fields=["config", "updated_at"])

        logger.info(
            "connection_config_updated",
            extra={
                "slug": slug,
                "connection_id": str(conn.id),
                "workspace_id": str(conn.workspace_id),
                "user_id": str(conn.user_id) if conn.user_id else None,
            },
        )
        return Response(ConnectionSerializer(conn).data)

    def delete(self, request, slug: str, *args, **kwargs):
        conn = _get_connection(slug=slug, request=request)
        conn_id = str(conn.id)
        conn.delete()
        logger.info(
            "connection_deleted",
            extra={
                "slug": slug,
                "connection_id": conn_id,
                "workspace_id": str(request.workspace.id),
            },
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class ConnectionPickerView(APIView):
    """GET picker data used to populate the subscription config UI."""

    def get(self, request, slug: str, resource: str, *args, **kwargs):
        conn = _get_connection(slug=slug, request=request)
        cls = _resolve_provider(slug)
        provider = cls()
        try:
            data = provider.picker(
                resource,
                params=dict(request.query_params.items()),
                connection=conn,
            )
        except NotImplementedError as exc:
            raise NotFound(str(exc) or f"connector {slug!r} exposes no picker") from exc
        except ValueError as exc:
            raise ValidationError({"resource": str(exc)}) from exc
        return Response(data)


class ConnectionUpgradeScopeView(APIView):
    """
    POST endpoint that starts an OAuth re-consent flow requesting **extra
    scopes** on top of the connector's defaults.

    Currently used by Drive to add ``drive.readonly`` for folder watching.
    The connector implements ``build_scope_upgrade_url(connection,
    redirect_to=None) -> str`` and is the only authority on which extra
    scopes are valid.
    """

    def post(self, request, slug: str, *args, **kwargs):
        conn = _get_connection(slug=slug, request=request)
        cls = _resolve_provider(slug)
        provider = cls()

        builder = getattr(provider, "build_scope_upgrade_url", None)
        if builder is None:
            raise NotFound(f"connector {slug!r} exposes no scope upgrade flow")

        redirect_to = request.data.get("redirect_to") if hasattr(request, "data") else None
        try:
            url = builder(connection=conn, redirect_to=redirect_to)
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response({"authorize_url": url})
