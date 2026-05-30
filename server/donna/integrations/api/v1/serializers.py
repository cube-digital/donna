"""
Serializers for the integrations API.

The list/retrieve endpoints return a lightweight status DTO — they don't
expose ``OAuthProvider`` or ``OAuthToken`` rows directly.

``ConnectionSerializer`` is the read-only shape for the per-binding
subscription editor (``/integrations/{slug}/subscription/``).
"""
from __future__ import annotations

from rest_framework import serializers

from ...models import Connection


class IntegrationStatusSerializer(serializers.Serializer):
    """One row per registered connector. Read-only.

    ``config_schema`` and ``default_config`` are optional and populated only on
    the retrieve endpoint (heavyweight to ship in every list response). The
    frontend uses them to render the schema-driven config form.
    """

    slug = serializers.CharField()
    display_name = serializers.CharField()
    category = serializers.CharField()
    is_configured = serializers.BooleanField()
    is_connected = serializers.BooleanField()
    token_scope = serializers.CharField(required=False, allow_null=True)
    config_schema = serializers.DictField(required=False, allow_null=True)
    default_config = serializers.DictField(required=False, allow_null=True)


class ConnectResponseSerializer(serializers.Serializer):
    """Response for POST /integrations/{slug}/connect — the authorize URL."""

    authorize_url = serializers.URLField()


class ConnectionSerializer(serializers.ModelSerializer):
    """Read-only DTO for ``Connection``. PATCH body is shaped separately."""

    class Meta:
        model  = Connection
        fields = [
            "id",
            "workspace",
            "user",
            "provider_slug",
            "config",
            "state",
            "enabled",
            "last_synced_at",
            "last_error_at",
            "last_error_msg",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
