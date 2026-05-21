"""
GmailProvider — the connector class for Google's Gmail.

First multi-product Google connector — establishes the vendor-nested
layout (``connectors/google/mail/``) and the shared
``GoogleOAuthHandler`` / ``BaseGoogleClient`` plumbing that future
Drive/Calendar connectors will reuse.

v1 trigger model: scheduled poll via Celery beat (``supports_webhooks =
False``). Webhook + workspace-resolution stay unimplemented until Pub/Sub
push lands.

Per-Connection config (see plans/08a-gmail-integration.md):

- ``mode``  — ``everything`` | ``time_window`` | ``subscriptions``
- ``time_window_days``  — int (used iff mode=time_window)
- ``labels`` / ``queries`` / ``domains``  — OR-combined filters used iff
  mode=subscriptions
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from donna.core.integrations import (
    BaseWebhookHandler,
    register,
    validate_against_schema,
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
    from donna.integrations.models import Connection
    from donna.workspaces.models import Workspace


# JSON Schema for the user-editable ``Connection.config`` blob.
# Validated by ``GmailProvider.validate_config`` on every PATCH.
_GMAIL_CONFIG_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type":    "object",
    "required": ["mode"],
    "properties": {
        "mode": {"enum": ["everything", "time_window", "subscriptions"]},
        "time_window_days": {
            "type":    "integer",
            "minimum": 1,
            "maximum": 3650,
        },
        "labels":  {"type": "array", "items": {"type": "string", "maxLength": 200}},
        "queries": {"type": "array", "items": {"type": "string", "maxLength": 500}},
        "domains": {"type": "array", "items": {"type": "string", "maxLength": 255}},
    },
    "allOf": [
        {
            "if":   {"properties": {"mode": {"const": "time_window"}}, "required": ["mode"]},
            "then": {"required": ["time_window_days"]},
        },
        {
            "if":   {"properties": {"mode": {"const": "subscriptions"}}, "required": ["mode"]},
            "then": {
                "anyOf": [
                    {"required": ["labels"],  "properties": {"labels":  {"minItems": 1}}},
                    {"required": ["queries"], "properties": {"queries": {"minItems": 1}}},
                    {"required": ["domains"], "properties": {"domains": {"minItems": 1}}},
                ],
            },
        },
    ],
    "additionalProperties": False,
}


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

    # ── Per-Connection config contract ─────────────────────────────────────
    config_schema: dict = _GMAIL_CONFIG_SCHEMA
    default_config: dict = {
        "mode": "time_window",
        "time_window_days": 30,
    }

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

    # ── Per-Connection config hooks ─────────────────────────────────────────
    def validate_config(
        self, config: dict, *, connection: "Connection | None" = None
    ) -> dict:
        """Validate config blob against :data:`_GMAIL_CONFIG_SCHEMA`."""
        return validate_against_schema(config, self.config_schema)

    def picker(self, resource: str, params: dict, *, connection: "Connection") -> dict:
        """
        Serve picker data for the subscription config UI.

        Supported resources:

        - ``labels`` — returns ``{labels: [{id, name, type}, ...]}`` via
          ``users.labels.list``. Frontend renders the picker, user checks
          rows, frontend PATCHes ``subscription`` with the selected IDs.
        """
        if resource == "labels":
            with self.client(connection.token) as client:
                resp = client.list_labels()
            return {
                "labels": [
                    {
                        "id":   l.get("id"),
                        "name": l.get("name"),
                        "type": l.get("type", "user"),
                    }
                    for l in (resp.get("labels") or [])
                ],
            }
        raise ValueError(f"Gmail picker has no resource {resource!r}")
