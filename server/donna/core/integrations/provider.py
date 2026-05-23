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
    Any,
    ClassVar,
    Literal,
    Protocol,
    runtime_checkable,
)

if TYPE_CHECKING:
    from donna.integrations.models import ClientCredentials, Connection, OAuthToken
    from donna.workspaces.models import Workspace

    from .adapter import BaseAdapter
    from .client import BaseHTTPClient
    from .oauth import BaseOAuthHandler
    from .webhook import BaseWebhookHandler


TokenScope = Literal["user", "workspace"]


def validate_against_schema(config: dict, schema: dict) -> dict:
    """
    Default config-validator helper. Runs jsonschema validation, raises
    ``ValueError`` on failure (translated to DRF 400 at the view layer).

    Connectors override ``IntegrationProvider.validate_config`` to layer
    cross-field rules on top (e.g. Drive's scope-required check).
    """
    from jsonschema import Draft202012Validator, ValidationError as _SchemaError

    try:
        Draft202012Validator(schema).validate(config)
    except _SchemaError as exc:
        # exc.message focuses on the failing field; absolute_path adds context
        path = "/".join(str(p) for p in exc.absolute_path) or "<root>"
        raise ValueError(f"config[{path}]: {exc.message}") from exc
    return config


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

    # ── Per-Connection config contract ──────────────────────────────────────
    # JSON Schema describing the shape of ``Connection.config`` for this
    # connector. Validated server-side on every PATCH. Connectors can also
    # generate a UI form from it later (Airbyte's connectionSpecification
    # pattern — see plans/08-connection-pattern.md).
    config_schema: ClassVar[dict[str, Any]]

    # Default ``Connection.config`` value applied when the framework
    # auto-creates a Connection row on OAuth pair.
    default_config: ClassVar[dict[str, Any]]

    # ── Factory methods ─────────────────────────────────────────────────────
    def client(self, token: "OAuthToken") -> "BaseHTTPClient":
        """Return an HTTP client bound to the given OAuthToken."""
        ...

    def webhook_handler(self) -> "BaseWebhookHandler":
        """Return the webhook handler (signature verification + parse)."""
        ...

    def oauth_handler(self, oauth_provider: "ClientCredentials") -> "BaseOAuthHandler":
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

    # ── Per-Connection config hooks ─────────────────────────────────────────
    def validate_config(self, config: dict, *, connection: "Connection | None" = None) -> dict:
        """
        Validate the incoming ``Connection.config`` payload and return the
        normalized version. Default impl runs ``validate_against_schema``;
        connectors override to add cross-field rules (e.g. "drive.readonly
        scope required when mode=everything").

        ``connection`` is passed when the validator needs to inspect the
        backing OAuthToken (e.g. scopes granted).
        """
        ...

    def picker(self, resource: str, params: dict, *, connection: "Connection") -> dict:
        """
        Return vendor data used to populate the Subscription config UI.

        Examples: Gmail's ``labels``, Drive's ``browse`` / ``drives``.
        Reached via ``GET /api/v1/integrations/{slug}/subscription/picker/{resource}``.

        Connectors that don't expose any picker raise ``NotImplementedError``.
        """
        ...
