"""Cortex API serializers."""
from __future__ import annotations

from rest_framework import serializers

from donna.cortex.models import CortexEntity


class CortexEntityReadSerializer(serializers.ModelSerializer):
    body_md = serializers.SerializerMethodField()

    class Meta:
        model = CortexEntity
        fields = (
            "id", "type", "author", "source", "title",
            "occurred_at", "client_id", "project_id", "cluster_id",
            "extensions", "entity_refs", "sources", "cross_refs",
            "supersedes", "superseded_by", "contradicts", "applied_in",
            "confidence", "last_synthesized", "body_byte_size",
            "created_at", "updated_at",
            "body_md",
        )
        read_only_fields = fields

    def get_body_md(self, obj: CortexEntity) -> str:
        if self.context.get("include_body"):
            return obj.load_body()
        return ""


class CortexEntityWriteSerializer(serializers.Serializer):
    type = serializers.CharField()
    author = serializers.ChoiceField(choices=("donna", "human", "agent"))
    source = serializers.CharField()
    title = serializers.CharField()
    body_md = serializers.CharField()
    extensions = serializers.DictField(required=False, default=dict)
    occurred_at = serializers.DateTimeField(required=False, allow_null=True)
    client_id = serializers.UUIDField(required=False, allow_null=True)
    project_id = serializers.UUIDField(required=False, allow_null=True)
    bronze_storage_key = serializers.CharField(required=False, default="", allow_blank=True)


class CortexQuerySerializer(serializers.Serializer):
    text = serializers.CharField()
    type = serializers.CharField(required=False, allow_blank=True)
    doc_type = serializers.CharField(required=False, allow_blank=True)
    client_id = serializers.UUIDField(required=False, allow_null=True)
    project_id = serializers.UUIDField(required=False, allow_null=True)
    limit = serializers.IntegerField(required=False, default=8, min_value=1, max_value=25)
