"""
Django admin registrations for the integrations app.

``ClientCredentials`` is the per-vendor OAuth-app row. The form's
``slug`` field is a dropdown populated from the connector registry —
admin picks an available vendor (``google``, ``fathom``, ...) instead of
typing a free-form slug. Rows for vendors that already have a row are
filtered out of the choices so a duplicate ``slug`` (the column is
``unique=True``) never gets attempted.

``OAuthToken`` rows are surfaced read-only — they're written by OAuth
callbacks, not by humans.
"""
from __future__ import annotations

from django import forms
from django.contrib import admin

from .models import ClientCredentials, Connection, DeliveryPackage, OAuthToken


# ─── ClientCredentials ────────────────────────────────────────────────────────
class ClientCredentialsForm(forms.ModelForm):
    """
    Admin form for ClientCredentials.

    ``slug`` becomes a dropdown sourced from registered connectors. The
    same slug can repeat across rows — one deployment-wide row
    (``workspace=NULL``) plus one row per workspace override. Uniqueness
    is enforced at the DB layer via partial unique constraints.
    """

    class Meta:
        model = ClientCredentials
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Lazy import — apps registry must be ready before discovery completes.
        from donna.core.integrations import all_loaded

        vendor_slugs = sorted({c.oauth_provider_slug for c in all_loaded()})
        choices = [(s, s) for s in vendor_slugs]
        if (
            self.instance.pk
            and self.instance.slug
            and self.instance.slug not in vendor_slugs
        ):
            # Surface legacy rows whose slug no longer matches a registered
            # connector — admin can clean them up.
            choices.insert(
                0,
                (self.instance.slug, f"{self.instance.slug} (unregistered)"),
            )

        self.fields["slug"] = forms.ChoiceField(
            choices=choices or [("", "— no connectors registered —")],
            help_text=ClientCredentials._meta.get_field("slug").help_text,
        )


@admin.register(ClientCredentials)
class ClientCredentialsAdmin(admin.ModelAdmin):
    form = ClientCredentialsForm

    list_display = ("slug", "scope_label", "display_name", "is_enabled", "client_id", "updated_at")
    list_filter = ("is_enabled", "slug")
    search_fields = ("slug", "display_name", "client_id", "workspace__slug")
    autocomplete_fields = ("workspace",)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Identity", {
            "fields": ("slug", "display_name", "workspace", "is_enabled"),
            "description": (
                "Leave <strong>workspace</strong> empty for the deployment-wide "
                "default. Set a workspace to override the default for that "
                "workspace only (per-workspace BYO OAuth app)."
            ),
        }),
        ("OAuth app credentials (admin-managed)", {
            "fields": ("client_id", "client_secret", "redirect_uri"),
            "description": (
                "Set in the upstream provider's developer console "
                "(Google Cloud, Fathom, etc.) and paste here."
            ),
        }),
        ("Webhook signing", {
            "fields": ("webhook_secret",),
            "classes": ("collapse",),
        }),
        ("Metadata", {
            "fields": ("metadata", "created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    @admin.display(description="scope", ordering="workspace")
    def scope_label(self, obj):
        return f"workspace={obj.workspace_id}" if obj.workspace_id else "global"


# ─── OAuthToken ───────────────────────────────────────────────────────────────
@admin.register(OAuthToken)
class OAuthTokenAdmin(admin.ModelAdmin):
    list_display = ("provider", "user", "workspace", "expires_at", "updated_at")
    list_filter = ("provider",)
    search_fields = (
        "provider__slug",
        "user__email",
        "workspace__slug",
    )
    autocomplete_fields = ("provider", "user", "workspace", "granter")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {
            "fields": ("provider", "user", "workspace", "granter"),
        }),
        ("Token material", {
            "fields": ("access_token", "refresh_token", "expires_at", "scope"),
        }),
        ("Audit", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )


# ─── Connection ───────────────────────────────────────────────────────────────
@admin.register(Connection)
class ConnectionAdmin(admin.ModelAdmin):
    list_display = ("provider_slug", "workspace", "user", "enabled", "last_synced_at")
    list_filter = ("provider_slug", "enabled")
    search_fields = ("provider_slug", "user__email", "workspace__slug")
    autocomplete_fields = ("workspace", "user", "token")
    readonly_fields = ("last_synced_at", "last_error_at", "last_error_msg", "created_at", "updated_at")


# ─── DeliveryPackage ──────────────────────────────────────────────────────────
@admin.register(DeliveryPackage)
class DeliveryPackageAdmin(admin.ModelAdmin):
    list_display = ("provider", "provider_item_type", "title", "workspace", "occurred_at")
    list_filter = ("provider", "provider_item_type")
    search_fields = ("provider_item_id", "title", "workspace__slug")
    autocomplete_fields = ("workspace",)
    readonly_fields = ("storage_key", "metadata", "created_at", "updated_at")
