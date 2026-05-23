"""
ProviderOAuthCallbackView — single dispatcher for all OAuth callbacks.

URL: ``GET /api/v1/integrations/{vendor_slug}/oauth/callback``

The URL path carries the *vendor* slug (e.g. ``google``), not a connector
slug. One vendor app means one registered redirect URI; the connector
identity (gmail / drive / calendar / fathom) is recovered from the signed
state token. ``RegistryService.handle_callback`` decodes the state, looks
up the connector class, verifies the URL vendor matches the connector's
``oauth_provider_slug``, then exchanges the code and persists the
``OAuthToken``.

Non-tenanted; workspace + user come from the state payload. On success
the browser is redirected back to a frontend URL recovered from the same
payload.
"""
from __future__ import annotations

import logging
from urllib.parse import urlencode

from django.http import HttpResponseRedirect
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from donna.core.integrations import (
    OAuthExchangeFailed,
    OAuthStateInvalid,
    ProviderNotRegistered,
)

from ...services import RegistryService


logger = logging.getLogger(__name__)


# Default frontend redirect if the state payload doesn't carry one. Kept
# relative so it works in any deployment.
_DEFAULT_SUCCESS_PATH = "/app/integrations"


class ProviderOAuthCallbackView(APIView):
    """Single OAuth callback endpoint for all connectors."""

    authentication_classes: list = []   # state-based, not DRF auth
    permission_classes = [AllowAny]

    def get(self, request, slug: str, *args, **kwargs):
        code = request.query_params.get("code")
        state = request.query_params.get("state")
        upstream_error = request.query_params.get("error")

        upstream_error_description = request.query_params.get("error_description")
        if upstream_error:
            logger.warning(
                "oauth_callback_upstream_error slug=%s error=%s description=%s",
                slug,
                upstream_error,
                upstream_error_description,
            )
            return _redirect_with_status(
                _DEFAULT_SUCCESS_PATH,
                slug,
                status="error",
                reason=upstream_error,
                detail=(upstream_error_description or "")[:300],
            )

        if not code or not state:
            return Response(
                {"detail": "missing `code` or `state` query parameter"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        service = RegistryService(current_user=None, company=None)

        try:
            token = service.handle_callback(slug=slug, code=code, state=state)
        except ProviderNotRegistered:
            raise NotFound(f"unknown integration {slug!r}")
        except OAuthStateInvalid as exc:
            logger.warning(
                "oauth_callback_state_invalid slug=%s error=%s", slug, exc,
            )
            return Response(
                {"detail": "invalid or expired state"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except OAuthExchangeFailed as exc:
            # Log full traceback + upstream response text in one line.
            logger.exception(
                "oauth_callback_exchange_failed slug=%s error=%s", slug, exc,
            )
            return _redirect_with_status(
                _DEFAULT_SUCCESS_PATH,
                slug,
                status="error",
                reason="exchange_failed",
                detail=str(exc)[:300],
            )
        except Exception as exc:                 # noqa: BLE001
            logger.exception(
                "oauth_callback_unhandled slug=%s error=%s", slug, exc,
            )
            return _redirect_with_status(
                _DEFAULT_SUCCESS_PATH,
                slug,
                status="error",
                reason="server_error",
                detail=str(exc)[:300],
            )

        logger.info(
            "oauth_callback_success",
            extra={"slug": slug, "token_id": str(token.id)},
        )
        return _redirect_with_status(_DEFAULT_SUCCESS_PATH, slug, status="connected")


def _redirect_with_status(base_path: str, slug: str, **params) -> HttpResponseRedirect:
    """Build a 302 redirect to ``{base_path}/{slug}?<params>``."""
    qs = urlencode(params)
    return HttpResponseRedirect(f"{base_path}/{slug}?{qs}" if qs else f"{base_path}/{slug}")
