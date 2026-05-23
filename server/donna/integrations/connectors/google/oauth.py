"""
GoogleOAuthHandler — Google-specific OAuth handler shared by Gmail (+ future
Drive, Calendar, etc.).

Subclasses :class:`donna.core.integrations.BaseOAuthHandler` so the rest of
the framework (RegistryService.initiate_connect, ProviderOAuthCallbackView,
state verification, signed state TTL) keeps working unchanged.

What's Google-specific:

- ``access_type="offline"`` + ``prompt="consent"`` — required to receive a
  refresh_token on every grant. Without these, Google only returns a refresh
  token on the *first* consent for a given (user × app × scope set), which
  breaks any flow where the user reconnects.
- ``include_granted_scopes="true"`` — enables incremental authorization, so
  later Drive/Calendar consents don't drop earlier Gmail scopes.
- Scope-laxity workaround — Google Workspace tenants auto-attach ``openid``
  + ``userinfo.email`` + ``userinfo.profile`` to every grant regardless of
  what the application requested; ``google-auth-oauthlib`` then raises
  ``Scope has changed`` and aborts the token exchange. Setting
  ``OAUTHLIB_RELAX_TOKEN_SCOPE=1`` is Google's documented workaround.
- ``google.auth.exceptions`` is missing some names that ``requests`` users
  expect (``HTTPError``, ``RequestException``); monkey-patch to point at the
  ``requests`` equivalents. Both shims are verbatim from the narrio reference
  implementation.
- Revocation endpoint: ``https://oauth2.googleapis.com/revoke``.

State signing reuses Donna's :class:`BaseOAuthHandler` machinery (Django
``signing.dumps`` with the framework-level salt), so callbacks land in
``RegistryService.handle_callback`` without any provider-specific glue.
"""
from __future__ import annotations

# ── narrio's pre-import shims — must run BEFORE google_auth_oauthlib ─────────
import os
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

import requests  # noqa: E402
from google.auth import exceptions as _google_auth_exceptions  # noqa: E402

if not hasattr(_google_auth_exceptions, "HTTPError"):
    _google_auth_exceptions.HTTPError = _google_auth_exceptions.TransportError
if not hasattr(_google_auth_exceptions, "RequestException"):
    _google_auth_exceptions.RequestException = requests.exceptions.RequestException
# ────────────────────────────────────────────────────────────────────────────

import logging
from datetime import timezone as _tz

from django.core import signing
from django.utils import timezone
from google_auth_oauthlib.flow import Flow

from donna.core.integrations import BaseOAuthHandler
from donna.core.integrations.exceptions import (
    OAuthExchangeFailed,
)
# Re-use the framework-level state salt so signed state from
# ``BaseOAuthHandler.build_authorize_url`` and our override round-trip
# through the same ``verify_state`` call.
from donna.core.integrations.oauth import _STATE_SALT


logger = logging.getLogger(__name__)


GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"


class GoogleOAuthHandler(BaseOAuthHandler):
    """OAuth handler for any Google connector (Gmail, Drive, Calendar, …)."""

    revocation_url = GOOGLE_REVOKE_URL

    # ── Flow construction ──────────────────────────────────────────────────
    def _flow(
        self,
        redirect_uri: str | None = None,
        extra_scopes: list[str] | None = None,
    ) -> Flow:
        cfg = self.config
        # Scopes live on the connector class, not on the DB row.
        # BaseOAuthHandler.default_scopes unions across all connectors
        # sharing this credentials row (Gmail + Drive → google).
        scopes = list(self.default_scopes)
        if extra_scopes:
            for s in extra_scopes:
                if s not in scopes:
                    scopes.append(s)
        flow = Flow.from_client_config(
            client_config={
                "web": {
                    "client_id":     cfg.client_id,
                    "client_secret": cfg.client_secret,
                    "auth_uri":      GOOGLE_AUTHORIZE_URL,
                    "token_uri":     GOOGLE_TOKEN_URL,
                },
            },
            scopes=scopes,
            redirect_uri=redirect_uri or cfg.redirect_uri,
        )
        # google_auth_oauthlib ≥ recent versions default
        # ``autogenerate_code_verifier=True`` on ``Flow.__init__``. That auto-
        # adds ``code_challenge`` to the authorize URL, which Google then
        # demands matching ``code_verifier`` on exchange. We use the standard
        # ``client_secret`` (confidential) flow for Web clients — no PKCE.
        # Disable here so authorize URL stays free of code_challenge.
        flow.autogenerate_code_verifier = False
        flow.code_verifier = None
        return flow

    # ── Authorize URL ──────────────────────────────────────────────────────
    def build_authorize_url(
        self,
        *,
        state_payload: dict,
        redirect_uri: str | None = None,
        extra_params: dict[str, str] | None = None,
        extra_scopes: list[str] | None = None,
    ) -> str:
        """
        Build Google's authorize URL with offline access + incremental scopes.
        Signs state with Donna's framework-level salt so the callback view
        can verify it via ``BaseOAuthHandler.verify_state``.

        ``extra_scopes`` augments the per-vendor ``default_scopes`` for this
        single flow — used by Drive's progressive scope upgrade
        (``drive.readonly``).
        """
        state = signing.dumps(state_payload, salt=_STATE_SALT)
        flow = self._flow(redirect_uri=redirect_uri, extra_scopes=extra_scopes)
        url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
            state=state,
            **(extra_params or {}),
        )
        return url

    # ── Code exchange ──────────────────────────────────────────────────────
    def exchange_code(self, code: str, redirect_uri: str | None = None) -> dict:
        """
        Exchange the authorization code for tokens via google-auth-oauthlib.
        Returns the raw upstream response shape so ``parse_token_response``
        (inherited from the base class) can normalize it.
        """
        flow = self._flow(redirect_uri=redirect_uri)
        try:
            flow.fetch_token(code=code)
        except Exception as exc:  # noqa: BLE001
            raise OAuthExchangeFailed(
                f"Google token exchange failed: {exc}"
            ) from exc

        creds = flow.credentials
        # ``creds.expiry`` is a naive datetime expressed in UTC. Convert it to
        # an aware datetime so downstream ``parse_token_response`` can compute
        # a sensible ``expires_in``.
        expires_in: int | None = None
        if creds.expiry is not None:
            # google-auth credentials.expiry is a naive datetime in UTC.
            expiry_aware = creds.expiry.replace(tzinfo=_tz.utc)
            expires_in = max(0, int((expiry_aware - timezone.now()).total_seconds()))

        # ``creds.scopes`` mirrors the *requested* scopes — not the actually-
        # granted ones. With ``include_granted_scopes=true``, Google's
        # response carries the union (e.g. drive.file + gmail.modify) inside
        # the raw token's ``scope`` field. Read that for the source of truth.
        raw_token = getattr(flow.oauth2session, "token", None) or {}
        granted_scope = raw_token.get("scope") or " ".join(creds.scopes or [])

        return {
            "access_token":  creds.token,
            "refresh_token": creds.refresh_token or "",
            "expires_in":    expires_in if expires_in is not None else 3600,
            "scope":         granted_scope,
            "token_type":    "Bearer",
            # id_token surfaced for future userinfo extraction (deferred).
            "id_token":      getattr(creds, "id_token", None),
        }

    # ── parse_token_response / refresh / revoke ───────────────────────────
    # All inherited from BaseOAuthHandler. parse_token_response works on the
    # shape returned by exchange_code above. refresh uses standard
    # ``grant_type=refresh_token`` against GOOGLE_TOKEN_URL. revoke POSTs
    # to revocation_url with the token.
