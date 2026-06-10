"""Serializers for the chat HTTP REST API."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework import serializers

from ...models import AgentSession, Channel, ChannelMembership, ChannelReadState, Message


User = get_user_model()


class _AuthorUserSerializer(serializers.ModelSerializer):
    """Nested user shape embedded on Message.author_user.

    The chat UI keys on ``author_user.id`` + ``full_name``/``email``;
    returning a bare PK would crash the React tree. Kept minimal so the
    message list endpoint stays cheap.
    """

    class Meta:
        model = User
        fields = ["id", "email", "full_name"]
        read_only_fields = fields


class _AuthorAgentSerializer(serializers.ModelSerializer):
    """Nested agent shape — mirrors ``_AuthorUserSerializer``."""

    class Meta:
        model = AgentSession
        fields = ["id", "name"]
        read_only_fields = fields


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
            "settings",
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

    def validate_slug(self, value: str) -> str:
        """Pre-check the DB-level workspace+slug uniqueness constraint.

        Without this validator the duplicate raises ``IntegrityError`` in
        ``Channel.objects.create`` and bubbles out as a 500. The
        constraint (``uq_channel_workspace_slug``) is the source of
        truth — this check is a UX layer, not a security boundary, so
        the race window between this query and the insert is fine.
        """
        if not value:
            return value
        request = self.context.get("request")
        workspace = getattr(request, "workspace", None)
        if workspace is None:
            return value
        exists = Channel.objects.filter(
            workspace=workspace, slug=value,
        ).exclude(slug="").exists()
        if exists:
            raise serializers.ValidationError(
                "slug already taken in this workspace"
            )
        return value


class ChannelUpdateSerializer(serializers.Serializer):
    """Body for PATCH /chat/channels/{id}/. All fields optional.

    ``settings`` accepts a dict — keys outside Channel.DEFAULT_SETTINGS
    are stored but won't be enforced anywhere. We deliberately don't
    enumerate keys here so adding a new flag is a one-line model change.
    """

    name = serializers.CharField(max_length=120, required=False)
    slug = serializers.SlugField(max_length=120, required=False, allow_blank=True)
    topic = serializers.CharField(max_length=255, required=False, allow_blank=True)
    visibility = serializers.ChoiceField(
        choices=Channel.Visibility.choices, required=False
    )
    settings = serializers.DictField(required=False)


class MessageSerializer(serializers.ModelSerializer):
    # Nest the author rows so the frontend can render avatar / display
    # name without a follow-up users lookup. v1 returns null when the
    # field is null; the consumer broadcast helper
    # ``_serialize_message`` in services.py still emits a bare UUID
    # (kept stable for the WS protocol).
    author_user = _AuthorUserSerializer(read_only=True)
    author_agent = _AuthorAgentSerializer(read_only=True)

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
        read_only_fields = [
            "id", "author_user", "author_agent", "created_at", "updated_at",
        ]


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
