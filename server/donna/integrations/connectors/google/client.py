"""
BaseGoogleClient — shared HTTP client base for every Google product
(Gmail, Drive, Calendar, …).

Extends ``BaseHTTPClient`` with:

- Auto-refresh on 401: a single refresh attempt via ``GoogleOAuthHandler``,
  then retry. Avoids polluting every Google call with manual expiry checks.
- A small ``profile()`` shortcut to ``https://www.googleapis.com/userinfo/v2/me``
  for ``email``/``sub`` extraction (used by the workspace-resolution fallback
  and by future ``OAuthToken.external_account_id`` population).

Concrete product clients set their own ``base_url`` (Gmail's is
``https://gmail.googleapis.com/gmail/v1``).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx

from donna.core.integrations import BaseHTTPClient
from donna.core.integrations.exceptions import TokenRefreshFailed

if TYPE_CHECKING:
    from donna.authentication.models import OAuthToken


logger = logging.getLogger(__name__)


USERINFO_URL = "https://www.googleapis.com/userinfo/v2/me"


class BaseGoogleClient(BaseHTTPClient):
    """Common base for Google product clients."""

    # Subclasses MUST override.
    base_url: str = ""

    def _auth_headers(self) -> dict[str, str]:
        # Identical to the default Bearer scheme, kept explicit so future
        # Google quirks (e.g., service-account JWTs) can override here.
        if self.token is None or not getattr(self.token, "access_token", None):
            return {}
        return {"Authorization": f"Bearer {self.token.access_token}"}

    # ── Auto-refresh on 401 ─────────────────────────────────────────────────
    def request(self, method: str, path: str, **kwargs: Any) -> dict:
        try:
            return super().request(method, path, **kwargs)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 401 or self.token is None:
                raise
            logger.info(
                "google_token_refresh_attempt",
                extra={"path": path, "token_id": str(self.token.id)},
            )
            self._refresh_token_in_place()
            # One retry only — if it still 401s, surface the error.
            return super().request(method, path, **kwargs)

    def _refresh_token_in_place(self) -> None:
        """Refresh ``self.token``'s access_token via Google's refresh flow."""
        from donna.authentication.models import OAuthProvider
        # Lazy import — keeps framework deps clean.
        from .oauth import GoogleOAuthHandler

        try:
            oauth_config = OAuthProvider.objects.get(slug=self.token.provider.slug)
        except OAuthProvider.DoesNotExist as exc:
            raise TokenRefreshFailed(
                f"OAuthProvider({self.token.provider.slug!r}) row missing"
            ) from exc

        handler = GoogleOAuthHandler(config=oauth_config)
        refreshed = handler.refresh(self.token)

        self.token.access_token = refreshed["access_token"]
        if refreshed.get("refresh_token"):
            self.token.refresh_token = refreshed["refresh_token"]
        self.token.expires_at = refreshed.get("expires_at")
        if refreshed.get("scope"):
            self.token.scope = refreshed["scope"]
        self.token.save(
            update_fields=["access_token", "refresh_token", "expires_at", "scope"]
        )

    # ── Helpers ─────────────────────────────────────────────────────────────
    def profile(self) -> dict:
        """Return Google userinfo (``email``, ``id``, ``verified_email``, …)."""
        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(USERINFO_URL, headers=self._auth_headers())
            response.raise_for_status()
            return response.json()
