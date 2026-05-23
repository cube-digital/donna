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


class SeenPatchSerializer(serializers.Serializer):
    """
    Body for ``PATCH /notifications/seen/``.

    - ``seen``: required boolean — value to set.
    - ``ids``: optional list of notification IDs. Omitted/empty means
      "apply to ALL the caller's notifications that don't already match".
    """

    seen = serializers.BooleanField()
    ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
    )
