"""Serializers for the notifications API."""
from __future__ import annotations

from rest_framework import serializers

from ...models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    """Read-only DTO for ``Notification`` rows surfaced in the in-app feed."""

    class Meta:
        model  = Notification
        fields = [
            "id",
            "title",
            "message",
            "status",
            "type",
            "seen",
            "context",
            "workspace",
            "user",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class MarkReadSerializer(serializers.Serializer):
    """Body for ``POST /notifications/mark-read`` — list of notification IDs."""

    ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
    )
