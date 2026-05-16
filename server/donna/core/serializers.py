from rest_framework import serializers


class FileUploadSerializer(serializers.Serializer):
    """Generic serializer for file uploads"""

    file = serializers.FileField()


class UserAuditRetrieveSerializer(serializers.Serializer):
    """Serializes user audit info"""

    created_by = serializers.SerializerMethodField(
        "get_creator_full_name", source="created_by"
    )
    modified_by = serializers.SerializerMethodField(
        "get_modifier_full_name", source="modified_by"
    )

    def get_creator_full_name(self, obj) -> str:
        if getattr(obj, "created_by", None):
            return obj.created_by.full_name
        return ""

    def get_modifier_full_name(self, obj) -> str:
        if getattr(obj, "modified_by", None):
            return obj.modified_by.full_name
        return ""
