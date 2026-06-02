"""Serializers for the chat HTTP REST API."""
from __future__ import annotations

from rest_framework import serializers

from ...models import Channel, ChannelMembership, ChannelReadState, Message


class ChannelSerializer(serializers.ModelSerializer):
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
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


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
    class Meta:
        model = Message
        fields = [
            "id",
            "channel",
            "body",
            "author_user",
            "author_agent",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "author_agent", "created_at", "updated_at"]


class MessageCreateSerializer(serializers.Serializer):
    body = serializers.CharField()
    client_msg_id = serializers.CharField(required=False, allow_blank=True)


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


class AdvanceReadSerializer(serializers.Serializer):
    message_id = serializers.UUIDField()
