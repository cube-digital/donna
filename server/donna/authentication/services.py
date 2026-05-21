"""
AuthService — thin orchestrator over per-provider OAuth login handlers.

v1 ships one handler (``google_login``). Add a new provider by:

  1. Drop ``handlers/<slug>.py`` implementing ``BaseOAuthHandler``.
  2. Register the dotted path in ``AuthService.HANDLERS``.
  3. Wire URL + view (mirror the ``GoogleLoginView`` / ``GoogleCallbackView`` pair).

The service is deliberately tiny — narrio's full ``AuthService`` carried
HubSpot/Calendar helpers + invitation propagation we don't need here.
"""
from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from .handlers.base import BaseOAuthHandler


logger = logging.getLogger(__name__)


class AuthService:
    """Resolves provider slugs to handler instances and dispatches calls."""

    HANDLERS: dict[str, str] = {
        "google_login": "donna.authentication.handlers.google_login.GoogleLoginHandler",
    }

    # ── Public API ──────────────────────────────────────────────────────────
    def get_authorization_url(
        self, provider: str, state: dict[str, Any] | None = None
    ) -> str:
        handler = self._get_handler(provider)
        return handler.get_authorization_url(state or {})

    def handle_oauth_callback(self, provider: str, request) -> dict[str, Any]:
        handler = self._get_handler(provider)
        return handler.handle_callback(request, self)

    # ── Internals ───────────────────────────────────────────────────────────
    def _get_handler(self, provider: str) -> "BaseOAuthHandler":
        if provider not in self.HANDLERS:
            raise ValueError(
                f"Unknown OAuth login provider: {provider!r}. "
                f"Registered: {sorted(self.HANDLERS)}."
            )
        module_path, class_name = self.HANDLERS[provider].rsplit(".", 1)
        module = importlib.import_module(module_path)
        return getattr(module, class_name)()
