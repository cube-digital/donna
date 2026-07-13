"""DRF serializers for the automation app."""
from __future__ import annotations

from rest_framework import serializers

from donna.automation.models import Schedule


class ScheduleSerializer(serializers.ModelSerializer):
    """Read + write a ``Schedule`` row. ``workspace`` is implied from the
    request context (``X-Workspace-Id``) so the client never has to send it."""

    class Meta:
        model = Schedule
        fields = (
            "id",
            "agent_session",
            "name",
            "cron",
            "timezone",
            "payload",
            "enabled",
            "last_fired_at",
            "next_fires_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "last_fired_at", "next_fires_at",
                            "created_at", "updated_at")
