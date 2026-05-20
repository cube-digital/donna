"""
IntegrationProvider Protocol — the contract every connector class implements.

A "connector" (single Python class) declares:
- Identity: slug, display_name, category
- OAuth coupling: which OAuthProvider row backs it, token scope, capability flags
- Static OAuth defaults: authorize/token URLs and scopes that bootstrap consumes
- Factory methods that return runtime collaborators (client, webhook handler,
  oauth handler, adapter)

The framework code never depends on app models; type hints use TYPE_CHECKING
so this module is importable without Django apps being ready.
"""
from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    ClassVar,
    Literal,
    Protocol,
    runtime_checkable,
)

if TYPE_CHECKING:
    from donna.authentication.models import OAuthProvider, OAuthToken
    from donna.workspaces.models import Workspace

    from .adapter import BaseAdapter
    from .client import BaseHTTPClient
    from .oauth import BaseOAuthHandler
    from .webhook import BaseWebhookHandler


TokenScope = Literal["user", "workspace"]


@runtime_checkable
class IntegrationProvider(Protocol):
    """
    Contract for every connector class. Implementations register themselves via
    the `@register` decorator from `.registry`.
    """

    # ── Identity ────────────────────────────────────────────────────────────
    slug: ClassVar[str]
    display_name: ClassVar[str]
    category: ClassVar[str]

    # ── OAuth coupling ──────────────────────────────────────────────────────
    # The `slug` of the OAuthProvider row that backs this connector. Multiple
    # connectors under the same vendor (Gmail + Drive) share an OAuthProvider.
    oauth_provider_slug: ClassVar[str]
    token_scope: ClassVar[TokenScope]

    # ── Static defaults (consumed by `integrations_bootstrap`) ──────────────
    default_authorize_url: ClassVar[str]
    default_token_url: ClassVar[str]
    default_scopes: ClassVar[list[str]]

    # ── Capabilities ────────────────────────────────────────────────────────
    supports_webhooks: ClassVar[bool]

    # ── Factory methods ─────────────────────────────────────────────────────
    def client(self, token: "OAuthToken") -> "BaseHTTPClient":
        """Return an HTTP client bound to the given OAuthToken."""
        ...

    def webhook_handler(self) -> "BaseWebhookHandler":
        """Return the webhook handler (signature verification + parse)."""
        ...

    def oauth_handler(self, oauth_provider: "OAuthProvider") -> "BaseOAuthHandler":
        """Return the OAuth handler bound to a specific OAuthProvider row."""
        ...

    def adapter_for(self, raw: dict) -> "BaseAdapter":
        """Return an adapter that renders the raw payload to text/markdown/json/metadata."""
        ...

    def resolve_workspace(self, parsed: dict) -> "Workspace":
        """
        Map a parsed webhook payload to the Workspace it belongs to.

        Lives on the connector (not the webhook handler) because the lookup
        convention is provider-specific (Fathom: by external user id; Slack:
        by team_id; etc.). The framework calls this after webhook verify+parse.
        """
        ...

    def dispatch_webhook(self, *, parsed: dict, workspace: "Workspace") -> None:
        """
        Enqueue the connector-specific Celery task for an incoming webhook.

        The connector knows which task to invoke and which fields to extract
        from the parsed payload. Implementations typically look like::

            from .tasks import ingest_<entity>
            ingest_<entity>.delay(str(workspace.id), parsed["<id_field>"])
        """
        ...
