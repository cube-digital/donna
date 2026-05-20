"""
Serializers for the integrations API.

The list/retrieve endpoints return a lightweight status DTO — they don't
expose ``OAuthProvider`` or ``OAuthToken`` rows directly.
"""
from __future__ import annotations

from rest_framework import serializers


class IntegrationStatusSerializer(serializers.Serializer):
    """One row per registered connector. Read-only."""

    slug = serializers.CharField()
    display_name = serializers.CharField()
    category = serializers.CharField()
    is_configured = serializers.BooleanField()
    is_connected = serializers.BooleanField()


class ConnectResponseSerializer(serializers.Serializer):
    """Response for POST /integrations/{slug}/connect — the authorize URL."""

    authorize_url = serializers.URLField()
