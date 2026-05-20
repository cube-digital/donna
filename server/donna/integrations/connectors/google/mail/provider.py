"""
GmailProvider — the connector class for Google's Gmail.

First multi-product Google connector — establishes the vendor-nested
layout (``connectors/google/mail/``) and the shared
``GoogleOAuthHandler`` / ``BaseGoogleClient`` plumbing that future
Drive/Calendar connectors will reuse.

v1 trigger model: scheduled poll via Celery beat (``supports_webhooks =
False``). Webhook + workspace-resolution stay unimplemented until Pub/Sub
push lands.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from donna.core.integrations import (
    BaseWebhookHandler,
    register,
)
from donna.core.integrations.exceptions import (
    IntegrationError,
)

from ..client import BaseGoogleClient
from ..oauth import GoogleOAuthHandler
from .adapter import GmailMessageAdapter
from .client import GmailClient

if TYPE_CHECKING:
    from donna.authentication.models import OAuthProvider, OAuthToken
    from donna.workspaces.models import Workspace


@register
class GmailProvider:
    """Connector for Google Gmail — pulls messages via Gmail v1 REST API."""

    # ── Identity ────────────────────────────────────────────────────────────
    slug = "gmail"
    display_name = "Gmail"
    category = "email"

    # ── OAuth coupling ──────────────────────────────────────────────────────
    oauth_provider_slug = "google"
    token_scope = "user"

    # ── Static OAuth defaults (consumed by integrations_bootstrap) ─────────
    default_authorize_url = "https://accounts.google.com/o/oauth2/v2/auth"
    default_token_url = "https://oauth2.googleapis.com/token"
    default_scopes: list[str] = [
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/userinfo.email",
        "openid",
    ]

    # ── Capabilities ────────────────────────────────────────────────────────
    # v1 polls via Celery beat. Pub/Sub push notifications are deferred.
    supports_webhooks = False

    # ── Factory methods ─────────────────────────────────────────────────────
    def client(self, token: "OAuthToken") -> GmailClient:
        return GmailClient(token=token)

    def oauth_handler(self, oauth_provider: "OAuthProvider") -> GoogleOAuthHandler:
        return GoogleOAuthHandler(config=oauth_provider)

    def webhook_handler(self) -> BaseWebhookHandler:  # pragma: no cover
        raise NotImplementedError(
            "GmailProvider has no webhook handler in v1 (poll-based). "
            "Pub/Sub push integration is deferred."
        )

    def adapter_for(self, raw: dict) -> GmailMessageAdapter:
        return GmailMessageAdapter(raw=raw)

    # ── Webhook / workspace resolution (stubbed for v1) ────────────────────
    def resolve_workspace(self, parsed: dict) -> "Workspace":  # pragma: no cover
        raise NotImplementedError(
            "Gmail uses scheduled polling per workspace; resolve_workspace "
            "is unused until Pub/Sub push lands."
        )

    def dispatch_webhook(self, *, parsed: dict, workspace: "Workspace") -> None:  # pragma: no cover
        raise IntegrationError(
            "GmailProvider does not accept webhooks in v1; sync is poll-driven."
        )
