"""Serializers for the current-user (``/me``) profile API."""
from __future__ import annotations

from django.core.files.storage import default_storage
from rest_framework import serializers

from donna.users.models import User


class MeSerializer(serializers.ModelSerializer):
    """Read + partial-update shape for the signed-in user's own profile.

    ``email`` is read-only (identity key). ``picture`` is exposed as a
    signed/absolute URL under ``picture_url``; the raw file is written via a
    dedicated multipart upload endpoint, not this serializer.
    """

    picture_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "full_name", "status", "is_away", "picture_url"]
        read_only_fields = ["id", "email", "picture_url"]

    def get_picture_url(self, obj: User) -> str | None:
        if not obj.picture:
            return None
        try:
            return default_storage.url(obj.picture.name)
        except Exception:  # noqa: BLE001 — never let a storage hiccup 500 /me
            return None
