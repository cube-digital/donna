"""
Integrations app models.

Two models live here:

- ``DeliveryPackage`` — one row per ingested item (Fathom meeting, Gmail
  message, Drive file). Idempotent via unique constraint on
  (workspace, provider, provider_item_id). The raw payload sits in
  ``default_storage`` at ``storage_key``.

- ``Connection`` — one row per ``(workspace, [user], provider_slug)``
  binding. Holds user-editable ``config`` (validated against
  ``Provider.config_schema``) and sync-task-managed ``state``. Replaces
  the per-connector subscription tables we considered earlier; see
  ``plans/08-connection-pattern.md`` for the design discussion + industry
  validation.

`WebhookDelivery` and `IngestionJob` are intentionally deferred — see
plans/02-data-model.md "Open" section.
"""
from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from donna.core.db.models import TimestampsMixin


class DeliveryPackage(TimestampsMixin):
    """
    One ingested item from an upstream provider.

    Populated by the connector's adapter; the raw payload lives in
    ``default_storage`` at ``storage_key``. The unique constraint on
    (workspace, provider, provider_item_id) makes re-delivery idempotent.
    """

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

    # ── Provider identity ───────────────────────────────────────────────────
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

    # ── Adapter outputs ─────────────────────────────────────────────────────
    title = models.CharField(_("title"), max_length=500, blank=True)
    occurred_at = models.DateTimeField(
        _("occurred at"),
        null=True,
        blank=True,
        help_text=_("When the source event happened."),
    )
    metadata = models.JSONField(_("metadata"), default=dict, blank=True)

    # ── Storage pointer ─────────────────────────────────────────────────────
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


class Connection(TimestampsMixin):
    """
    Per ``(workspace, [user], provider_slug)`` ingest binding.

    One row holds:

    - ``config`` — user-editable JSON, validated by
      ``Provider.config_schema`` (JSON Schema). Shape varies per
      connector; see ``connectors/*/provider.py``.
    - ``state``  — sync-task-managed JSON, keyed per-resource so that
      future per-stream resets/parallelisation don't need a migration.
      Shape: ``{"streams": {<id>: {...}}, "global": {...}}``.

    ``user`` is non-null when the backing connector is user-scoped
    (Gmail/Drive); null for workspace-scoped connectors (Fathom).
    """

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
        "authentication.OAuthToken",
        on_delete=models.CASCADE,
        related_name="connections",
        related_query_name="connection",
        help_text=_(
            "The OAuthToken backing this binding. N:1 — one token can back "
            "multiple Connections (Gmail + Drive share Google token)."
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

    # ── Hot-queryable fields (lifted from state per Nango pattern) ─────────
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
