"""
GoogleLoginHandler — OAuth-based user signin/signup with Google.

Design notes:

- Google login is *intentionally separate* from the integration-OAuth
  flow under ``donna/integrations/connectors/google/oauth.py``. That one
  stores refresh tokens in ``OAuthToken`` and exists so Donna can call
  Gmail / Drive APIs. This one *only* identifies the user — we do NOT
  persist Google's refresh token at login.
- Credentials come from ``settings.GOOGLE_LOGIN_CLIENT_ID /
  GOOGLE_LOGIN_CLIENT_SECRET / GOOGLE_LOGIN_REDIRECT_URI``.
- State is signed with Django's ``signing.dumps`` so the callback view
  can verify it without server-side storage.
- On success the handler issues a simplejwt refresh token and returns a
  302 target that hands it to the frontend in the query string.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from django.conf import settings
from django.core import signing
from django.utils import timezone
from google_auth_oauthlib.flow import Flow
from rest_framework_simplejwt.tokens import RefreshToken

from donna.users.models import User

from .base import BaseOAuthHandler


if TYPE_CHECKING:
    from donna.authentication.services import AuthService


logger = logging.getLogger(__name__)


GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

# Salt isolates Google-login state from the integration-OAuth state salt.
_STATE_SALT = "donna.authentication.google_login.state"


class GoogleLoginHandler(BaseOAuthHandler):
    """Google OAuth handler for user authentication (login + signup)."""

    LOGIN_SCOPES = [
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
    ]

    # ── Helpers ─────────────────────────────────────────────────────────────
    def _flow(self) -> Flow:
        client_id = settings.GOOGLE_LOGIN_CLIENT_ID
        client_secret = settings.GOOGLE_LOGIN_CLIENT_SECRET
        redirect_uri = settings.GOOGLE_LOGIN_REDIRECT_URI
        if not (client_id and client_secret and redirect_uri):
            raise RuntimeError(
                "Google login is not configured — set GOOGLE_LOGIN_CLIENT_ID, "
                "GOOGLE_LOGIN_CLIENT_SECRET, GOOGLE_LOGIN_REDIRECT_URI in settings."
            )
        return Flow.from_client_config(
            client_config={
                "web": {
                    "client_id":     client_id,
                    "client_secret": client_secret,
                    "auth_uri":      GOOGLE_AUTHORIZE_URL,
                    "token_uri":     GOOGLE_TOKEN_URL,
                },
            },
            scopes=self.LOGIN_SCOPES,
            redirect_uri=redirect_uri,
        )

    # ── BaseOAuthHandler ────────────────────────────────────────────────────
    def get_authorization_url(self, state: dict[str, Any]) -> str:
        flow = self._flow()
        signed_state = signing.dumps(state or {"type": "login"}, salt=_STATE_SALT)
        url, _ = flow.authorization_url(
            access_type="online",            # login doesn't need refresh token
            include_granted_scopes="false",
            prompt="select_account",
            state=signed_state,
        )
        return url

    def handle_callback(self, request, auth_service: "AuthService") -> dict[str, Any]:
        try:
            code = request.GET.get("code")
            state = request.GET.get("state")
            error = request.GET.get("error")
            if error:
                logger.warning("google_login_upstream_error", extra={"error": error})
                return self._error_redirect("upstream_error")
            if not code or not state:
                return self._error_redirect("missing_code_or_state")

            # State is purely informational for login (no workspace context),
            # but verifying it prevents callback replays.
            try:
                signing.loads(state, salt=_STATE_SALT, max_age=600)
            except signing.BadSignature:
                logger.warning("google_login_state_invalid")
                return self._error_redirect("state_invalid")

            flow = self._flow()
            try:
                flow.fetch_token(code=code)
            except Exception as exc:  # noqa: BLE001
                logger.exception("google_login_token_exchange_failed: %s", exc)
                return self._error_redirect("exchange_failed")

            credentials = flow.credentials
            user_info = self._fetch_userinfo(credentials.token)
            email = user_info.get("email")
            if not email:
                return self._error_redirect("missing_email")

            user = self._create_or_get_user(user_info)

            refresh_token = RefreshToken.for_user(user)
            query = urlencode(
                {
                    "redirect_uri":  self._post_login_path(user),
                    "refresh_token": str(refresh_token),
                }
            )
            callback_url = f"{settings.WEB_REDIRECT_HOST.rstrip('/')}/login/callback?{query}"
            logger.info("google_login_success", extra={"user_id": str(user.id)})
            return {"redirect_url": callback_url}

        except Exception as exc:                # noqa: BLE001
            logger.exception("google_login_unhandled_error: %s", exc)
            return self._error_redirect("server_error")

    # ── Internals ───────────────────────────────────────────────────────────
    def _fetch_userinfo(self, access_token: str) -> dict[str, Any]:
        """Fetch userinfo using the freshly-issued access token."""
        import httpx

        with httpx.Client(timeout=10.0) as client:
            resp = client.get(
                "https://openidconnect.googleapis.com/v1/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            return resp.json()

    def _create_or_get_user(self, user_info: dict[str, Any]) -> User:
        email = user_info["email"]
        full_name = user_info.get("name") or " ".join(
            x for x in (user_info.get("given_name"), user_info.get("family_name")) if x
        )
        user = User.objects.filter(email__iexact=email).first()
        now = timezone.now()
        if user is None:
            user = User.objects.create_user(
                email=email,
                password=None,
                full_name=full_name or "",
                is_active=True,
                email_verified=True,           # Google has attested the email
                email_verified_at=now,
            )
            # ``create_user`` with ``password=None`` results in an
            # unusable password — fine, the user can request a reset
            # later to enable email/password sign-in.
            user.set_unusable_password()
            user.save(update_fields=["password"])
            logger.info("google_login_user_created", extra={"user_id": str(user.id)})
            return user

        # Existing user — backfill profile fields + flip email_verified once.
        updates: dict[str, Any] = {}
        if not user.full_name and full_name:
            updates["full_name"] = full_name
        if not user.is_active:
            updates["is_active"] = True
        if not user.email_verified:
            updates["email_verified"] = True
            updates["email_verified_at"] = now
        if updates:
            for k, v in updates.items():
                setattr(user, k, v)
            user.save(update_fields=list(updates.keys()))
        return user

    def _post_login_path(self, user: User) -> str:
        """Frontend route to land on after login. Kept simple in v1."""
        return "/"

    def _error_redirect(self, code: str) -> dict[str, Any]:
        host = settings.WEB_REDIRECT_HOST.rstrip("/")
        return {
            "error":        code,
            "redirect_url": f"{host}/login?error={code}",
        }
