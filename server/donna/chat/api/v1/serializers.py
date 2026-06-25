"""Serializers for the chat HTTP REST API."""
from __future__ import annotations

from django.db.models import Count, Exists, OuterRef
from rest_framework import serializers

from ...models import (
    Channel,
    ChannelMembership,
    ChannelPin,
    ChannelReadState,
    Document,
    Message,
    MessageReaction,
)


class ChannelSerializer(serializers.ModelSerializer):
    is_pinned = serializers.SerializerMethodField()

    class Meta:
        model = Channel
        fields = [
            "id",
            "kind",
            "name",
            "slug",
            "topic",
            "visibility",
            "workspace",
            "is_pinned",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "is_pinned", "created_at", "updated_at"]

    def get_is_pinned(self, obj):
        request = self.context.get("request") if hasattr(self, "context") else None
        if request is None or not getattr(request, "user", None) or not request.user.is_authenticated:
            return False
        # Fast path: annotated by viewset (avoid N+1 on lists).
        if hasattr(obj, "_is_pinned"):
            return bool(obj._is_pinned)
        return ChannelPin.objects.filter(user=request.user, channel=obj).exists()


class ChannelCreateSerializer(serializers.Serializer):
    """Body for POST /chat/channels/."""

    name = serializers.CharField(max_length=120)
    slug = serializers.SlugField(max_length=120, required=False, allow_blank=True)
    topic = serializers.CharField(max_length=255, required=False, allow_blank=True)
    visibility = serializers.ChoiceField(
        choices=Channel.Visibility.choices,
        default=Channel.Visibility.PUBLIC,
    )


class ChannelUpdateSerializer(serializers.Serializer):
    """Body for PATCH /chat/channels/{id}/. All fields optional."""

    name = serializers.CharField(max_length=120, required=False)
    slug = serializers.SlugField(max_length=120, required=False, allow_blank=True)
    topic = serializers.CharField(max_length=255, required=False, allow_blank=True)
    visibility = serializers.ChoiceField(
        choices=Channel.Visibility.choices, required=False
    )


class MessageSerializer(serializers.ModelSerializer):
    parent_id = serializers.UUIDField(read_only=True, allow_null=True)
    reply_count = serializers.SerializerMethodField()
    mentions = serializers.SerializerMethodField()
    reactions = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = [
            "id",
            "channel",
            "body",
            "author_user",
            "author_agent",
            "parent_id",
            "reply_count",
            "mentions",
            "mention_flags",
            "reactions",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id", "author_agent", "parent_id", "reply_count",
            "mentions", "mention_flags", "reactions",
            "created_at", "updated_at",
        ]

    def get_reply_count(self, obj):
        if hasattr(obj, "_reply_count"):
            return int(obj._reply_count)
        return obj.replies.count()

    def get_mentions(self, obj):
        return [str(uid) for uid in obj.mentions.values_list("id", flat=True)]

    def get_reactions(self, obj):
        """Aggregate reactions: [{emoji, count, by_me}, ...]."""
        request = self.context.get("request") if hasattr(self, "context") else None
        me = getattr(request, "user", None) if request else None
        out: dict[str, dict] = {}
        for r in obj.reactions.all():
            entry = out.setdefault(r.emoji, {"emoji": r.emoji, "count": 0, "by_me": False})
            entry["count"] += 1
            if me is not None and getattr(me, "is_authenticated", False) and r.author_user_id == me.id:
                entry["by_me"] = True
        return list(out.values())


class MessageCreateSerializer(serializers.Serializer):
    body = serializers.CharField()
    client_msg_id = serializers.CharField(required=False, allow_blank=True)
    parent_id = serializers.UUIDField(required=False, allow_null=True)


class MessageEditSerializer(serializers.Serializer):
    body = serializers.CharField()


class DMOpenSerializer(serializers.Serializer):
    peer_user_id = serializers.UUIDField()


class GroupDMOpenSerializer(serializers.Serializer):
    """
    Body for POST /chat/dms/group/.

    ``peer_user_ids`` are the *other* members; the caller is always
    added implicitly. Final member count must be ≥ 2 (so at least one
    peer is required — for a 2-person DM use /chat/dms/ instead).
    """

    peer_user_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        allow_empty=False,
    )


class ChannelMembershipSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChannelMembership
        fields = ["id", "channel", "user", "role", "created_at"]
        read_only_fields = ["id", "channel", "created_at"]


class AddMemberSerializer(serializers.Serializer):
    """
    Body for POST /chat/channels/{cid}/members/.

    Two call shapes:
    - admin-add: ``{user_id, role?}`` — caller must be a channel ADMIN.
    - self-join: ``{}`` (or ``{user_id: <caller-id>}``) — only valid on
      PUBLIC channels.
    """

    user_id = serializers.UUIDField(required=False)
    role = serializers.ChoiceField(
        choices=ChannelMembership.Role.choices,
        required=False,
    )


class ReadStateSerializer(serializers.ModelSerializer):
    unread_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = ChannelReadState
        fields = [
            "id",
            "user",
            "channel",
            "last_read_message",
            "last_read_at",
            "unread_count",
        ]
        read_only_fields = fields


class DocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = (
            "id",
            "channel",
            "title",
            "body",
            "status",
            "version",
            "target_doc_type",
            "finalized_entity_id",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class AdvanceReadSerializer(serializers.Serializer):
    message_id = serializers.UUIDField()


class ReactionCreateSerializer(serializers.Serializer):
    emoji = serializers.CharField(max_length=64)


class ReactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = MessageReaction
        fields = ["id", "message", "emoji", "author_user", "created_at"]
        read_only_fields = fields
