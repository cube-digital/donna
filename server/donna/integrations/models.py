"""
Integrations app models.

Four models live here:

- ``ClientCredentials`` — per-deployment OAuth-app configuration. One
  row per upstream vendor (Google's row backs Gmail + Drive + Calendar).
  Holds ``client_id`` / ``client_secret`` / ``redirect_uri`` /
  ``default_scopes`` / ``webhook_secret``. Admin populates these via
  Django admin; bootstrap seeds stubs.

- ``OAuthToken`` — per-(user XOR workspace) token issued by the
  upstream provider after the OAuth dance. FK to ``ClientCredentials``.

- ``Connection`` — per ``(workspace, [user], provider_slug)`` ingest
  binding. Holds user-editable ``config`` (validated against
  ``Provider.config_schema``) and sync-task-managed ``state``. FK to
  ``OAuthToken``. See plans/08-connection-pattern.md for design notes.

- ``DeliveryPackage`` — one row per ingested item (Fathom meeting,
  Gmail message, Drive file). Idempotent via unique constraint on
  (workspace, provider, provider_item_id). Raw payload sits in
  ``default_storage`` at ``storage_key``.

Login-related token models (``ResetPasswordToken``, ``EmailVerificationToken``)
live in ``donna/authentication/models.py`` — they don't belong here.

``WebhookDelivery`` and ``IngestionJob`` are intentionally deferred —
see plans/02-data-model.md "Open" section.
"""
from __future__ import annotations

import uuid

from django.contrib.auth import get_user_model
from django.db import models
from django.utils.translation import gettext_lazy as _

from donna.core.db.fields import EncryptedTextField
from donna.core.db.models import TimestampsMixin, UserAuditMixin


# ─── ClientCredentials (was OAuthProvider, moved here) ───────────────────────
class ClientCredentialsManager(models.Manager):
    """Convenience lookups for the deployment-default / workspace-override pair."""

    def resolve(self, slug: str, workspace=None):
        """
        Return the most-specific ClientCredentials row for ``slug``:

        - workspace-scoped row (if ``workspace`` provided and it exists)
        - else deployment-wide row (``workspace=NULL``)
        - else None

        Match the same precedence rule downstream code expects.
        """
        if workspace is not None:
            row = (
                self.filter(slug=slug, workspace=workspace, is_enabled=True)
                .first()
            )
            if row is not None:
                return row
        return (
            self.filter(slug=slug, workspace__isnull=True, is_enabled=True)
            .first()
        )


class ClientCredentials(TimestampsMixin, UserAuditMixin):
    """
    OAuth-app credentials per upstream vendor. Two flavours:

    - **Deployment-wide** (``workspace=NULL``) — created by
      ``integrations_bootstrap``. The default app every workspace uses.
    - **Workspace-scoped** (``workspace=<id>``) — a workspace's own
      BYO OAuth app. Overrides the deployment default for that one
      workspace (rate-limit isolation, custom branding, etc.).

    Lookup precedence: workspace row if present + enabled, else
    deployment-wide row. See ``ClientCredentialsManager.resolve``.

    Connector classes reference rows here via ``oauth_provider_slug``.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        db_index=True,
    )

    # Identity
    slug = models.CharField(
        _("slug"),
        max_length=64,
        help_text=_(
            "Stable identifier; matches connector class "
            "``oauth_provider_slug`` (e.g. \"google\", \"fathom\")."
        ),
    )
    display_name = models.CharField(_("display name"), max_length=120)

    # NULL → deployment-wide default. Non-NULL → workspace-specific override.
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="client_credentials",
        related_query_name="client_credentials",
        help_text=_(
            "Leave empty to make this the deployment-wide default for the slug. "
            "Set to a workspace to override the default for that workspace only."
        ),
    )

    # Master switch — until True, the provider doesn't appear to users.
    is_enabled = models.BooleanField(_("is enabled"), default=False)

    # OAuth-app credentials (set by the admin via Django admin)
    client_id = models.CharField(_("client id"), max_length=255, blank=True, default="")
    client_secret = EncryptedTextField(_("client secret"), null=True, blank=True)
    redirect_uri = models.URLField(_("redirect uri"), blank=True, default="")

    # ``authorize_url``, ``token_url`` and ``default_scopes`` come from the
    # registered connector class (``default_authorize_url`` etc.) at runtime;
    # see ``BaseOAuthHandler._connector_classes``. No DB caching → no drift,
    # no bootstrap command, no "URL is empty" admin footgun.

    # Webhook signing secret (when the provider sends webhooks). Webhook
    # verification always uses the deployment-wide row — see services
    # for the workspace-scoped resolver path.
    webhook_secret = EncryptedTextField(_("webhook secret"), null=True, blank=True)

    # Free-form provider-specific extras (e.g., Slack signing secret, region overrides)
    metadata = models.JSONField(_("metadata"), default=dict, blank=True)

    objects = ClientCredentialsManager()

    class Meta:
        db_table = "client_credentials"
        verbose_name = _("Client Credentials")
        verbose_name_plural = _("Client Credentials")
        constraints = [
            # Exactly one deployment-wide row per slug.
            models.UniqueConstraint(
                fields=["slug"],
                condition=models.Q(workspace__isnull=True),
                name="uq_clientcred_slug_global",
            ),
            # At most one workspace-scoped row per (slug, workspace).
            models.UniqueConstraint(
                fields=["slug", "workspace"],
                condition=models.Q(workspace__isnull=False),
                name="uq_clientcred_slug_workspace",
            ),
        ]
        indexes = [
            models.Index(fields=["slug", "workspace"]),
        ]

    def __str__(self):
        scope = f" @ workspace={self.workspace_id}" if self.workspace_id else " (global)"
        return f"{self.display_name or self.slug}{scope}"

    def __repr__(self):
        return (
            f"<{self.__class__.__name__}: slug={self.slug!r} "
            f"workspace={self.workspace_id} id={self.id}>"
        )


# ─── OAuthToken (moved from authentication app) ──────────────────────────────
class OAuthToken(TimestampsMixin):
    """
    OAuth token issued by the upstream provider for one connected
    account. Always tied to a ``ClientCredentials`` row, plus exactly
    one of:

    - ``user`` — user-scoped token (e.g. Gmail per employee).
    - ``workspace`` — workspace-scoped token (e.g. Slack per workspace);
      ``granter`` records the authorizing user for audit.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        db_index=True,
    )

    provider = models.ForeignKey(
        ClientCredentials,
        on_delete=models.CASCADE,
        related_name="tokens",
        related_query_name="token",
    )

    user = models.ForeignKey(
        get_user_model(),
        on_delete=models.CASCADE,
        related_name="oauth_tokens",
        related_query_name="oauth_token",
        null=True,
        blank=True,
    )
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="oauth_tokens",
        related_query_name="oauth_token",
        null=True,
        blank=True,
    )
    granter = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        related_name="granted_oauth_tokens",
        related_query_name="granted_oauth_token",
        null=True,
        blank=True,
        help_text=_("User who authorized a workspace-scoped token."),
    )

    # Token material
    access_token = EncryptedTextField(_("access token"), null=True, blank=True)
    refresh_token = EncryptedTextField(_("refresh token"), null=True, blank=True)
    expires_at = models.DateTimeField(
        _("access token expiry"),
        null=True,
        blank=True,
        help_text=_("When the current access_token expires (UTC)."),
    )
    scope = models.TextField(_("scope"), null=True, blank=True)

    class Meta:
        db_table = "oauth_tokens"
        verbose_name = _("OAuth token")
        verbose_name_plural = _("OAuth tokens")
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(user__isnull=False, workspace__isnull=True)
                    | models.Q(user__isnull=True, workspace__isnull=False)
                ),
                name="oauth_token_has_exactly_one_owner",
            ),
            models.UniqueConstraint(
                fields=["provider", "user"],
                condition=models.Q(user__isnull=False),
                name="uq_oauth_token_per_user_provider",
            ),
            models.UniqueConstraint(
                fields=["provider", "workspace"],
                condition=models.Q(workspace__isnull=False),
                name="uq_oauth_token_per_workspace_provider",
            ),
        ]
        indexes = [
            models.Index(fields=["provider", "user"]),
            models.Index(fields=["provider", "workspace"]),
        ]

    def __str__(self):
        owner = self.user or self.workspace
        return f"{self.provider} - {owner}"

    def __repr__(self):
        return (
            f"<{self.__class__.__name__}: "
            f"provider={self.provider_id} user={self.user_id} workspace={self.workspace_id}>"
        )


# ─── DeliveryPackage ─────────────────────────────────────────────────────────
class DeliveryPackage(TimestampsMixin):
    """One ingested item from an upstream provider."""

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        db_index=True,
    )

    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="delivery_packages",
        related_query_name="delivery_package",
    )

    provider = models.CharField(
        _("provider"),
        max_length=64,
        help_text=_("Connector slug, e.g. \"fathom\", \"gmail\"."),
    )
    provider_item_id = models.CharField(
        _("provider item id"),
        max_length=255,
        help_text=_("Upstream provider's stable id for this item."),
    )
    provider_item_type = models.CharField(
        _("provider item type"),
        max_length=64,
        help_text=_("E.g. \"meeting\", \"email\", \"issue\"."),
    )

    title = models.CharField(_("title"), max_length=500, blank=True)
    occurred_at = models.DateTimeField(
        _("occurred at"),
        null=True,
        blank=True,
        help_text=_("When the source event happened."),
    )
    metadata = models.JSONField(_("metadata"), default=dict, blank=True)

    storage_key = models.CharField(
        _("storage key"),
        max_length=500,
        help_text=_("Key under STORAGES[\"default\"], e.g. \"{ws}/fathom/meetings/{id}.json\"."),
    )

    class Meta:
        db_table = "delivery_packages"
        verbose_name = _("Delivery Package")
        verbose_name_plural = _("Delivery Packages")
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "provider", "provider_item_id"],
                name="uq_delivery_package_workspace_provider_item",
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "provider", "occurred_at"]),
            models.Index(fields=["workspace", "occurred_at"]),
        ]
        ordering = ["-occurred_at", "-created_at"]

    def __str__(self):
        return f"{self.provider}:{self.provider_item_id} ({self.title})"

    def __repr__(self):
        return (
            f"<{self.__class__.__name__}: "
            f"workspace={self.workspace_id} provider={self.provider!r} "
            f"item={self.provider_item_id!r}>"
        )


# ─── Connection ──────────────────────────────────────────────────────────────
class Connection(TimestampsMixin):
    """Per (workspace, [user], provider_slug) ingest binding."""

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        db_index=True,
    )

    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="integration_connections",
        related_query_name="integration_connection",
    )
    user = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="integration_connections",
        related_query_name="integration_connection",
        help_text=_(
            "Set when the backing connector is user-scoped; null for "
            "workspace-scoped connectors."
        ),
    )
    provider_slug = models.CharField(
        _("provider slug"),
        max_length=50,
        help_text=_("Connector slug, e.g. \"gmail\", \"drive\", \"fathom\"."),
    )
    token = models.ForeignKey(
        OAuthToken,
        on_delete=models.CASCADE,
        related_name="connections",
        related_query_name="connection",
        help_text=_(
            "The OAuthToken backing this binding. N:1 — one token can "
            "back multiple Connections (Gmail + Drive share Google token)."
        ),
    )

    config = models.JSONField(
        _("config"),
        default=dict,
        blank=True,
        help_text=_(
            "User-editable. Validated by Provider.config_schema (JSON Schema) "
            "on every PATCH."
        ),
    )
    state = models.JSONField(
        _("state"),
        default=dict,
        blank=True,
        help_text=_(
            "Sync-task-managed. Shape: {streams: {<id>: {...}}, global: {...}}."
        ),
    )

    enabled = models.BooleanField(_("enabled"), default=True)

    last_synced_at = models.DateTimeField(_("last synced at"), null=True, blank=True)
    last_error_at = models.DateTimeField(_("last error at"), null=True, blank=True)
    last_error_msg = models.TextField(_("last error msg"), blank=True)

    class Meta:
        db_table = "integration_connections"
        verbose_name = _("Integration Connection")
        verbose_name_plural = _("Integration Connections")
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "user", "provider_slug"],
                name="uq_connection_ws_user_provider",
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "provider_slug", "enabled"]),
            models.Index(fields=["token"]),
            models.Index(fields=["last_synced_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        scope = f"user={self.user_id}" if self.user_id else "workspace"
        return f"{self.provider_slug} ({scope}, ws={self.workspace_id})"

    def __repr__(self):
        return (
            f"<{self.__class__.__name__}: "
            f"workspace={self.workspace_id} user={self.user_id} "
            f"provider={self.provider_slug!r} enabled={self.enabled}>"
        )
