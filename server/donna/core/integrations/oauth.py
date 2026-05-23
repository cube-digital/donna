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
    from donna.integrations.models import ClientCredentials, OAuthToken

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

    Bound to one ``ClientCredentials`` row (carries client_id / secret /
    redirect_uri / webhook_secret). The vendor's authorize_url, token_url
    and default scope list come from the registered connector class —
    not from the DB row — so admins never have to paste URLs or keep
    them in sync.
    """

    #: Optional revocation endpoint. Override per provider when known.
    revocation_url: str | None = None

    #: HTTP timeout for token-endpoint calls.
    timeout: float = 30.0

    #: Where the client_id / client_secret travel in token-endpoint requests.
    #: RFC 6749 mandates Basic ("client_secret_basic"); some providers also
    #: accept body ("client_secret_post"). Strict ones (e.g. Fathom) reject
    #: body. Default is Basic — override per provider only when needed.
    token_endpoint_auth_method: str = "client_secret_basic"

    def __init__(
        self,
        config: "ClientCredentials",
        connector_cls: type | None = None,
    ):
        """
        ``connector_cls`` pins the handler to one specific connector so the
        authorize URL only requests *that* connector's scopes. Required for
        incremental OAuth: connecting Gmail must not request Drive scopes
        even though both share ``oauth_provider_slug='google'``. Providers
        pass ``type(self)`` from their ``oauth_handler()`` factory.

        When ``connector_cls`` is None, scopes union across all connectors
        sharing the credentials row (legacy behaviour).
        """
        self.config = config
        self.connector_cls = connector_cls

    # ── Connector metadata (URLs + scopes live on the connector class) ─────
    def _connector_classes(self) -> list:
        """All registered connector classes backed by this credentials row."""
        from .registry import all_loaded

        slug = self.config.slug
        matches = [c for c in all_loaded() if c.oauth_provider_slug == slug]
        if not matches:
            from .exceptions import OAuthError

            raise OAuthError(
                f"no connector class registered with oauth_provider_slug={slug!r}"
            )
        return matches

    def _primary_connector(self):
        """Connector pinned at construction, or first match by slug."""
        return self.connector_cls or self._connector_classes()[0]

    @property
    def authorize_url(self) -> str:
        return self._primary_connector().default_authorize_url

    @property
    def token_url(self) -> str:
        return self._primary_connector().default_token_url

    @property
    def default_scopes(self) -> list[str]:
        """
        Scopes for the pinned connector only when ``connector_cls`` was set
        at construction (enables incremental OAuth); otherwise union across
        all connectors sharing this credentials row.
        """
        if self.connector_cls is not None:
            return list(self.connector_cls.default_scopes or [])
        scopes: set[str] = set()
        for cls in self._connector_classes():
            scopes.update(cls.default_scopes or [])
        return sorted(scopes)

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
            "scope": " ".join(self.default_scopes),
            "state": state,
        }
        if extra_params:
            params.update(extra_params)

        return f"{self.authorize_url}?{urlencode(params)}"

    # ── State verification ──────────────────────────────────────────────────
    @staticmethod
    def verify_state(state: str) -> dict:
        """
        Verify and decode a state token. Raises OAuthStateInvalid on failure.

        Static — signing salt is framework-level, not row- or handler-specific.
        Callers can decode state before knowing which connector / credentials
        row to use (e.g. callback view dispatching by URL vendor slug).
        """
        try:
            return signing.loads(state, salt=_STATE_SALT, max_age=_STATE_MAX_AGE_SECONDS)
        except signing.SignatureExpired as exc:
            raise OAuthStateInvalid("state token expired") from exc
        except signing.BadSignature as exc:
            raise OAuthStateInvalid("state token signature invalid") from exc

    # ── Token endpoint auth helpers ─────────────────────────────────────────
    def _token_request_kwargs(self, body: dict) -> dict:
        """
        Apply this handler's ``token_endpoint_auth_method`` to an httpx
        ``post`` call. Returns kwargs for ``httpx.post``.
        """
        method = self.token_endpoint_auth_method
        if method == "client_secret_basic":
            # Pass via HTTP Basic — RFC 6749 §2.3.1 preferred.
            return {
                "data": body,
                "auth": (self.config.client_id, self.config.client_secret or ""),
            }
        if method == "client_secret_post":
            # Some legacy providers want creds in body.
            return {
                "data": {
                    **body,
                    "client_id":     self.config.client_id,
                    "client_secret": self.config.client_secret or "",
                },
            }
        raise OAuthExchangeFailed(
            f"unsupported token_endpoint_auth_method: {method!r}"
        )

    # ── Token exchange ──────────────────────────────────────────────────────
    def exchange_code(self, code: str, redirect_uri: str | None = None) -> dict:
        """POST to the upstream token endpoint with the auth code."""
        body = {
            "grant_type":   "authorization_code",
            "code":         code,
            "redirect_uri": redirect_uri or self.config.redirect_uri,
        }
        try:
            response = httpx.post(
                self.token_url,
                timeout=self.timeout,
                **self._token_request_kwargs(body),
            )
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

        body = {
            "grant_type":    "refresh_token",
            "refresh_token": token.refresh_token,
        }
        try:
            response = httpx.post(
                self.token_url,
                timeout=self.timeout,
                **self._token_request_kwargs(body),
            )
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
