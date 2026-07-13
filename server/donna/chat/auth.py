"""
JWT authentication helpers for async transports.

Two consumers today:

* ``SubprotocolJWTAuthMiddleware`` — WebSocket handshake. Frontend opens::

      new WebSocket("wss://api.donna/ws/", ["bearer", "<access-token>"])

  The two-element subprotocol list is the documented browser-portable
  way to ship a token through a WS handshake. Server reads
  ``scope["subprotocols"]``, validates the second value as a simplejwt
  access token, attaches the resolved User to ``scope["user"]``, and
  accepts the negotiated subprotocol so the handshake succeeds.

  Anonymous connections get ``scope["user"] = AnonymousUser()`` — the
  consumer decides whether to close (typically 4401).

* :func:`resolve_jwt_user` — also reused by the SSE notifications view
  (``donna/notifications/api/v1/views.py``). Django's
  ``AuthenticationMiddleware`` doesn't run DRF authenticators on async
  views, so ``request.user`` is always ``AnonymousUser`` there. The
  async view reads ``Authorization: Bearer <jwt>`` directly and calls
  this helper to resolve the user.
"""
from __future__ import annotations

import logging

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser


logger = logging.getLogger(__name__)


@database_sync_to_async
def resolve_jwt_user(raw_token: str):
    """
    Validate a JWT access token and return the matching User instance.

    Returns ``AnonymousUser`` (never raises) on any validation failure,
    so callers can do a single ``user.is_authenticated`` check.

    Lazy-imports rest_framework_simplejwt to avoid loading rest_framework
    before Django apps are ready — this module is imported from
    ``donna/asgi.py`` at startup.
    """
    from rest_framework_simplejwt.authentication import JWTAuthentication
    from rest_framework_simplejwt.exceptions import (
        AuthenticationFailed,
        InvalidToken,
        TokenError,
    )

    authenticator = JWTAuthentication()
    try:
        validated = authenticator.get_validated_token(raw_token)
        return authenticator.get_user(validated)
    except (InvalidToken, TokenError, AuthenticationFailed) as exc:
        logger.info("jwt_invalid", extra={"error": str(exc)})
        return AnonymousUser()


# Backward-compat alias — keep until external callers migrate.
_resolve_user = resolve_jwt_user


class SubprotocolJWTAuthMiddleware(BaseMiddleware):
    """
    Read ``Sec-WebSocket-Protocol: bearer, <jwt>`` and resolve a User.

    Some clients can't customize headers — they pass the JWT as the
    second WS subprotocol. We accept either format:

      ["bearer", "<jwt>"]      ← portable (preferred)
      ["bearer.<jwt>"]         ← single-value form (some libs)
    """

    async def __call__(self, scope, receive, send):
        subprotocols = scope.get("subprotocols") or []
        token = _extract_token(subprotocols)
        # Fallback: token in querystring (?token=<jwt>). Some proxies
        # (vite-dev, nginx without ws subprotocol pass-through) strip
        # Sec-WebSocket-Protocol headers. Query-string is universally
        # forwarded.
        if not token:
            token = _extract_token_from_qs(scope.get("query_string") or b"")
        if token:
            scope["user"] = await resolve_jwt_user(token)
            # When the client offered a subprotocol we must echo one back
            # or some browsers (Chrome) abort the handshake with code 1006
            # even though Channels' default accept() permits it. Echo
            # "bearer" whenever the client offered it; otherwise None.
            if any(sp.lower() == "bearer" for sp in subprotocols):
                scope["jwt_subprotocol"] = "bearer"
            else:
                scope["jwt_subprotocol"] = None
        else:
            scope["user"] = AnonymousUser()
        return await super().__call__(scope, receive, send)


def _extract_token_from_qs(query_string: bytes) -> str | None:
    """Pull ``token=<jwt>`` from the WS query string."""
    from urllib.parse import parse_qs

    try:
        params = parse_qs(query_string.decode("utf-8"))
    except UnicodeDecodeError:
        return None
    values = params.get("token") or params.get("access_token")
    if not values:
        return None
    return values[0] or None


def _extract_token(subprotocols: list[str]) -> str | None:
    if not subprotocols:
        return None
    # Form A: ["bearer", "<jwt>"]
    if len(subprotocols) >= 2 and subprotocols[0].lower() == "bearer":
        return subprotocols[1]
    # Form B: ["bearer.<jwt>"]
    for sp in subprotocols:
        if sp.lower().startswith("bearer."):
            return sp.split(".", 1)[1]
    return None


def SubprotocolJWTAuthMiddlewareStack(inner):  # noqa: N802 — matches Channels naming
    """Convenience wrapper so ``asgi.py`` reads like Channels' own stacks."""
    return SubprotocolJWTAuthMiddleware(inner)
