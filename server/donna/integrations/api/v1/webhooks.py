"""
ProviderWebhookView — single dispatcher for all connector webhooks.

URL: ``POST /api/v1/integrations/{slug}/webhook/callback``

Non-tenanted (provider doesn't send ``X-Workspace-Id``). Authenticated by
HMAC signature on the request body (or whatever the connector's webhook
handler implements). The view's job is small:

  1. Look up the connector by slug.
  2. Verify + parse the payload.
  3. Resolve workspace via connector.resolve_workspace(parsed).
  4. Enqueue the connector's Celery task with (workspace_id, item_id).
  5. Return 200 fast.

Any exception during 1–4 returns a clear 4xx with a logged event. The actual
ingestion runs out-of-band on the worker.
"""
from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from donna.core.integrations import (
    ProviderNotRegistered,
    WebhookPayloadInvalid,
    WebhookSignatureInvalid,
    WorkspaceResolutionFailed,
    get as get_provider,
)


logger = logging.getLogger(__name__)


class ProviderWebhookView(APIView):
    """Single endpoint for all connector webhooks."""

    authentication_classes: list = []   # signature-based, not DRF auth
    permission_classes = [AllowAny]

    # ── Provider-driven dispatch ────────────────────────────────────────────
    def post(self, request, slug: str, *args, **kwargs):
        # 1. Look up the connector
        try:
            provider_cls = get_provider(slug)
        except ProviderNotRegistered:
            logger.info("webhook_unknown_provider", extra={"slug": slug})
            return Response(
                {"detail": f"unknown integration {slug!r}"},
                status=status.HTTP_404_NOT_FOUND,
            )

        provider = provider_cls()
        handler = provider.webhook_handler()

        signature = request.headers.get(handler.signature_header)
        payload = request.body

        # 2. Parse — pure (json.loads), no side effects, runs before verify so
        #    we can resolve the Connection whose per-tenant secret will be
        #    used for HMAC verification (Fathom-style per-webhook secrets).
        #    Dispatch never happens until verify succeeds further below.
        try:
            parsed = handler.parse(payload)
        except WebhookPayloadInvalid as exc:
            logger.warning(
                "webhook_payload_invalid",
                extra={"slug": slug, "error": str(exc)},
            )
            return Response(
                {"detail": "invalid payload"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 3. Resolve workspace
        try:
            workspace = provider.resolve_workspace(parsed)
        except WorkspaceResolutionFailed as exc:
            logger.warning(
                "webhook_workspace_resolution_failed",
                extra={"slug": slug, "error": str(exc)},
            )
            # 200 with explicit "ignored" so the provider stops retrying.
            return Response(
                {"detail": "workspace not resolvable; ignoring", "reason": str(exc)},
                status=status.HTTP_200_OK,
            )

        # 4. Look up the Connection (used by handlers with per-tenant secrets,
        #    e.g. Fathom). Lookup keys off the Connection.provider_slug, which
        #    matches the URL slug.
        from donna.integrations.models import Connection

        connection = (
            Connection.objects
            .filter(workspace=workspace, provider_slug=slug)
            .first()
        )

        # 5. Verify HMAC. Per-Connection secrets read from connection.state;
        #    base handler ignores the kwarg and falls back to ClientCredentials.
        try:
            handler.verify(payload, signature, connection=connection)
        except WebhookSignatureInvalid as exc:
            logger.warning(
                "webhook_signature_invalid",
                extra={"slug": slug, "error": str(exc)},
            )
            return Response(
                {"detail": "invalid signature"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # 6. Dispatch to the connector-specific task. The connector is
        # responsible for putting `_dispatch_webhook(parsed, workspace)` in
        # its task module, OR we look it up by a naming convention. For v1
        # we delegate to a method on the provider so each connector decides.
        dispatcher = getattr(provider, "dispatch_webhook", None)
        if dispatcher is None:
            logger.error(
                "webhook_no_dispatcher",
                extra={"slug": slug},
            )
            return Response(
                {"detail": "provider does not implement dispatch_webhook"},
                status=status.HTTP_501_NOT_IMPLEMENTED,
            )

        try:
            # Pass the connection resolved above so the connector can route
            # the ingest fetch to the right token (transient — never stored).
            dispatcher(parsed=parsed, workspace=workspace, connection=connection)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "webhook_dispatch_failed",
                extra={"slug": slug, "workspace_id": str(workspace.id), "error": str(exc)},
            )
            return Response(
                {"detail": "internal error dispatching ingestion"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        logger.info(
            "webhook_accepted",
            extra={"slug": slug, "workspace_id": str(workspace.id)},
        )
        return Response(status=status.HTTP_200_OK)
