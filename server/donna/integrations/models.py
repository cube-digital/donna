"""
Integrations app models.

v1 has a single model: ``DeliveryPackage``. Each row corresponds to one
ingested item (a Fathom meeting, a Gmail message, a Linear issue) and points
at the raw blob in ``default_storage``. The unique constraint provides
idempotency without a separate ``WebhookDelivery`` log.

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
