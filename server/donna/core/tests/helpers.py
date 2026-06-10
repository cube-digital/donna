"""
Shared test helpers — authenticated DRF + WS clients, token mint.

Keep this module free of app-specific knowledge so any test file can
import it. App-specific factories live in ``donna/<app>/tests/factories.py``.
"""
from __future__ import annotations

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken


def jwt_for(user) -> str:
    """Generate a fresh access token without hitting the signin endpoint."""
    return str(AccessToken.for_user(user))


def api_client(*, user=None, workspace=None) -> APIClient:
    """
    Configured DRF test client.

    - If ``user`` is given, sets ``Authorization: Bearer <jwt>``.
    - If ``workspace`` is given, sets ``X-Workspace-Id``.

    Returns a fresh client each call so tests can't leak headers.
    """
    client = APIClient()
    if user is not None:
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {jwt_for(user)}")
    if workspace is not None:
        client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {jwt_for(user)}" if user else "",
            HTTP_X_WORKSPACE_ID=str(workspace.id),
        )
    return client


def envelope(response):
    """
    Extract the ``data`` value from the rendered StandardJSONRenderer
    envelope ``{data, meta, message, code}``.

    Use this instead of ``response.data`` in tests — ``response.data``
    is the *pre-render* payload from the view, but the renderer wraps
    it before serialization. ``response.json()['data']`` is what the
    HTTP client actually sees.
    """
    return response.json()["data"]


def envelope_full(response) -> dict:
    """Same as ``envelope`` but returns the full {data, meta, message, code}."""
    return response.json()
