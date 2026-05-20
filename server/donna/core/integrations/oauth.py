"""
BaseOAuthHandler — standard OAuth 2.0 authorization-code flow.

Provides default implementations of the full lifecycle:
- `build_authorize_url(state_payload, ...)` returns the upstream URL
- `exchange_code(code)` POSTs to the token endpoint
- `parse_token_response(resp)` extracts access/refresh tokens
- `refresh(token)` uses refresh_token
- `revoke(token)` best-effort
- `handle_callback(code, state, ...)` orchestrates the callback path

Providers with custom OAuth flows (Slack bot+user tokens, GitHub installations,
PKCE, incremental scopes) subclass and override the relevant method.
"""
from __future__ import annotations

import json
import logging
import secrets
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

import httpx
from django.core import signing
from django.utils import timezone

if TYPE_CHECKING:
    from donna.authentication.models import OAuthProvider, OAuthToken

from .exceptions import (
    OAuthExchangeFailed,
    OAuthStateInvalid,
    TokenRefreshFailed,
)


logger = logging.getLogger(__name__)


# Signed state payloads live for 10 minutes. Anything longer is a smell.
_STATE_MAX_AGE_SECONDS = 600
_STATE_SALT = "donna.integrations.oauth.state"


class BaseOAuthHandler:
    """
    Default OAuth 2.0 authorization-code flow.

    One instance bound to a specific OAuthProvider row (which carries
    client_id, client_secret, redirect_uri, authorize_url, token_url, scopes).
    """

    #: Optional revocation endpoint. Override per provider when known.
    revocation_url: str | None = None

    #: HTTP timeout for token-endpoint calls.
    timeout: float = 30.0

    def __init__(self, config: "OAuthProvider"):
        self.config = config

    # ── Authorize URL ───────────────────────────────────────────────────────
    def build_authorize_url(
        self,
        *,
        state_payload: dict,
        redirect_uri: str | None = None,
        extra_params: dict[str, str] | None = None,
    ) -> str:
        """
        Build the upstream authorize URL with a signed `state` token.

        `state_payload` should include enough to recover (user, workspace, slug)
        after the round-trip. The framework signs + serializes it; the upstream
        provider passes it back verbatim on the callback.
        """
        state = signing.dumps(state_payload, salt=_STATE_SALT)

        params: dict[str, str] = {
            "response_type": "code",
            "client_id": self.config.client_id,
            "redirect_uri": redirect_uri or self.config.redirect_uri,
            "scope": " ".join(self.config.default_scopes or []),
            "state": state,
        }
        if extra_params:
            params.update(extra_params)

        return f"{self.config.authorize_url}?{urlencode(params)}"

    # ── State verification ──────────────────────────────────────────────────
    def verify_state(self, state: str) -> dict:
        """Verify and decode a state token. Raises OAuthStateInvalid on failure."""
        try:
            return signing.loads(state, salt=_STATE_SALT, max_age=_STATE_MAX_AGE_SECONDS)
        except signing.SignatureExpired as exc:
            raise OAuthStateInvalid("state token expired") from exc
        except signing.BadSignature as exc:
            raise OAuthStateInvalid("state token signature invalid") from exc

    # ── Token exchange ──────────────────────────────────────────────────────
    def exchange_code(self, code: str, redirect_uri: str | None = None) -> dict:
        """POST to the upstream token endpoint with the auth code."""
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "redirect_uri": redirect_uri or self.config.redirect_uri,
        }
        try:
            response = httpx.post(self.config.token_url, data=data, timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise OAuthExchangeFailed(f"network error contacting token endpoint: {exc}") from exc

        if response.status_code >= 400:
            raise OAuthExchangeFailed(
                f"token endpoint returned {response.status_code}: {response.text}"
            )

        try:
            return response.json()
        except ValueError as exc:
            raise OAuthExchangeFailed(f"token endpoint returned non-JSON: {exc}") from exc

    def parse_token_response(self, resp: dict) -> dict:
        """
        Normalize the upstream token response. Returns a dict ready for
        OAuthToken construction:
            access_token, refresh_token, expires_at, scope
        Override per provider for non-standard shapes.
        """
        access_token = resp.get("access_token")
        if not access_token:
            raise OAuthExchangeFailed(f"token response missing access_token: {resp}")

        expires_at = None
        expires_in = resp.get("expires_in")
        if expires_in is not None:
            expires_at = timezone.now() + timedelta(seconds=int(expires_in))

        return {
            "access_token": access_token,
            "refresh_token": resp.get("refresh_token", ""),
            "expires_at": expires_at,
            "scope": resp.get("scope", ""),
        }

    # ── Refresh ─────────────────────────────────────────────────────────────
    def refresh(self, token: "OAuthToken") -> dict:
        """
        Use the refresh_token to obtain a new access_token. Returns the same
        shape as `parse_token_response`. Caller persists the updated token.
        """
        if not token.refresh_token:
            raise TokenRefreshFailed("token has no refresh_token; cannot refresh")

        data = {
            "grant_type": "refresh_token",
            "refresh_token": token.refresh_token,
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
        }
        try:
            response = httpx.post(self.config.token_url, data=data, timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise TokenRefreshFailed(f"network error refreshing token: {exc}") from exc

        if response.status_code >= 400:
            raise TokenRefreshFailed(
                f"refresh endpoint returned {response.status_code}: {response.text}"
            )

        try:
            return self.parse_token_response(response.json())
        except ValueError as exc:
            raise TokenRefreshFailed(f"refresh endpoint returned non-JSON: {exc}") from exc

    # ── Revoke ──────────────────────────────────────────────────────────────
    def revoke(self, token: "OAuthToken") -> None:
        """
        Best-effort revocation. If revocation_url isn't set or the call fails,
        we log and proceed — the caller still deletes the OAuthToken row.
        """
        if not self.revocation_url:
            logger.info(
                "oauth_revoke_skipped",
                extra={"provider": self.config.slug, "reason": "no revocation_url"},
            )
            return

        try:
            httpx.post(
                self.revocation_url,
                data={
                    "token": token.access_token,
                    "client_id": self.config.client_id,
                    "client_secret": self.config.client_secret,
                },
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "oauth_revoke_failed",
                extra={"provider": self.config.slug, "error": str(exc)},
            )
