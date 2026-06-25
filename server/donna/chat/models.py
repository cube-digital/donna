from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from donna.core.db.models import TimestampsMixin, UserAuditMixin
from donna.workspaces.models import Workspace


class Channel(TimestampsMixin, UserAuditMixin):
    """A room inside a workspace.

    ``kind`` distinguishes regular named channels from direct messages.
    DMs are channels with ``kind=DIRECT`` and (typically) no name/slug —
    they're identified by their member set, which is a service-layer concern.
    All channel machinery (membership, messages, agent sessions, documents)
    applies uniformly to both kinds.
    """

    class Kind(models.TextChoices):
        CHANNEL = "channel", "Channel"
        DIRECT = "direct", "Direct Message"

    class Visibility(models.TextChoices):
        PUBLIC = "public", "Public"
        PRIVATE = "private", "Private"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(
        max_length=16,
        choices=Kind.choices,
        default=Kind.CHANNEL,
    )
    name = models.CharField(max_length=120, blank=True)
    slug = models.SlugField(max_length=120, blank=True)
    topic = models.CharField(max_length=255, blank=True)
    visibility = models.CharField(
        max_length=16,
        choices=Visibility.choices,
        default=Visibility.PUBLIC,
    )

    # Relationships
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="channels",
    )

    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="ChannelMembership",
        related_name="channels",
    )

    class Meta:
        db_table = "channels"
        constraints = [
            # Slug uniqueness applies only to named channels (DMs have no slug).
            models.UniqueConstraint(
                fields=["workspace", "slug"],
                condition=~models.Q(slug=""),
                name="uq_channel_workspace_slug",
            ),
            # DMs are always private by definition.
            # NOTE: Use string values here — the inner Kind/Visibility enums
            # aren't in scope inside the Meta class body.
            models.CheckConstraint(
                condition=~models.Q(kind="direct") | models.Q(visibility="private"),
                name="dm_must_be_private",
            ),
        ]
        ordering = ["name"]
        indexes = [
            models.Index(fields=["workspace", "kind"]),
        ]

    def __str__(self) -> str:
        if self.kind == self.Kind.DIRECT:
            return f"dm:{self.id}"
        return f"#{self.slug or self.name}"


class ChannelMembership(TimestampsMixin):
    """Join: User × Channel, with role."""

    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        MEMBER = "member", "Member"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    channel = models.ForeignKey(
        Channel,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="channel_memberships",
    )
    role = models.CharField(
        max_length=16,
        choices=Role.choices,
        default=Role.MEMBER,
    )

    class Meta:
        db_table = "channel_memberships"
        constraints = [
            models.UniqueConstraint(
                fields=["channel", "user"],
                name="uq_channel_membership_channel_user",
            ),
        ]
        ordering = ["channel_id", "role"]

    def __str__(self) -> str:
        return f"{self.user_id}@{self.channel_id} ({self.role})"


class AgentSession(TimestampsMixin):
    """The agent's identity and persistent state within a channel.

    N:1 with Channel (Option C): typically one session per channel today,
    but the schema admits multiple personas/specialists without restructuring.
    Memory and config are kept here so they have their own lifecycle —
    resetting an agent = ``session.delete() + AgentSession.objects.create(...)``.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120, default="Donna")
    memory = models.JSONField(default=dict, blank=True)
    config = models.JSONField(default=dict, blank=True)
    last_active_at = models.DateTimeField(null=True, blank=True)

    # Relationships
    channel = models.ForeignKey(
        Channel,
        on_delete=models.CASCADE,
        related_name="agent_sessions",
    )

    class Meta:
        db_table = "agent_sessions"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name}@{self.channel_id}"


class Message(TimestampsMixin):
    """A message in a channel, authored by exactly one of: a User or an AgentSession.

    Threading: ``parent`` is a self-FK. Replies live as child rows; the UI
    enforces 1-level nesting (replies-to-replies collapse to the top-level
    thread). ``parent`` is indexed so reply lists are cheap.

    Mentions: ``mentions`` M2M lists tagged users; ``mention_flags`` carries
    special targets (``donna`` / ``channel`` / ``everyone``). Populated by
    ``donna.chat.mentions.parse`` from the body on write.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    body = models.TextField()

    # Relationships
    channel = models.ForeignKey(
        Channel,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    author_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="messages",
    )
    author_agent = models.ForeignKey(
        AgentSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="messages",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="replies",
        help_text="Thread parent. Top-level messages have parent=NULL.",
    )
    mentions = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="mentioned_in_messages",
        blank=True,
    )
    mention_flags = models.JSONField(
        default=dict,
        blank=True,
        help_text='Special mentions: {"donna": bool, "channel": bool, "everyone": bool}.',
    )

    class Meta:
        db_table = "messages"
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(author_user__isnull=False, author_agent__isnull=True)
                    | models.Q(author_user__isnull=True, author_agent__isnull=False)
                ),
                name="message_has_exactly_one_author",
            ),
        ]
        indexes = [
            models.Index(fields=["channel", "created_at"]),
            models.Index(fields=["parent", "created_at"]),
        ]


class ChannelReadState(TimestampsMixin):
    """
    Per ``(user, channel)`` last-read pointer. Drives unread badges.

    Slack-style: one row per (user, channel), not per message. The
    frontend reads this on channel open to position the unread divider,
    advances it via ``POST /api/v1/chat/channels/{id}/read-state/`` (or
    WS ``mark_read`` action), and re-reads it when waking from
    background. See plans/10-realtime-layer.md.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="channel_read_states",
    )
    channel = models.ForeignKey(
        Channel,
        on_delete=models.CASCADE,
        related_name="read_states",
    )
    last_read_message = models.ForeignKey(
        "Message",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Last message the user has read in this channel.",
    )
    last_read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "channel_read_states"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "channel"],
                name="uq_channel_read_state_user_channel",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "channel"]),
        ]

    def __str__(self) -> str:
        return f"read({self.user_id}@{self.channel_id})"


class Document(TimestampsMixin, UserAuditMixin):
    """A Cowork-style collaborative artifact created within a channel.

    A2 (2026-06-20): now carries the drafting lifecycle. Exactly one
    ``status=DRAFTING`` row may exist per channel (partial unique
    constraint = the "draft lock" that prevents the agent from forking
    two drafts in the same conversation). ``UpdateDraftSectionTool``
    bumps ``version`` under ``select_for_update``; tools pass
    ``expected_version`` to detect concurrent edits.

    ``FinalizeDraftTool`` flips ``status`` to FINALIZED and pins
    ``finalized_entity_id`` to the freshly-created ``CortexEntity``
    UUID. ABANDONED is reserved for explicit cancel + audit-history use.
    """

    class Status(models.TextChoices):
        DRAFTING = "drafting", "Drafting"
        FINALIZED = "finalized", "Finalized"
        ABANDONED = "abandoned", "Abandoned"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    channel = models.ForeignKey(
        Channel,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True)

    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.DRAFTING,
    )
    version = models.IntegerField(default=0)
    target_doc_type = models.CharField(
        max_length=32, blank=True, default="",
        help_text="DocType vocab from cortex.schemas (passed to linter on finalize).",
    )
    finalized_entity_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "documents"
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["channel"],
                condition=models.Q(status="drafting"),
                name="uq_one_active_draft_per_channel",
            ),
        ]

    def __str__(self) -> str:
        return self.title


class ChannelPin(TimestampsMixin):
    """Per-user pinned channel marker — drives the Sidebar "Pinned" section.

    One row per (user, channel). Pin/unpin = create/delete. Idempotent at
    the service layer.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="channel_pins",
    )
    channel = models.ForeignKey(
        Channel,
        on_delete=models.CASCADE,
        related_name="pins",
    )

    class Meta:
        db_table = "channel_pins"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "channel"],
                name="uq_channel_pin_user_channel",
            ),
        ]
        indexes = [
            models.Index(fields=["user"]),
        ]

    def __str__(self) -> str:
        return f"pin({self.user_id}@{self.channel_id})"


class MessageReaction(TimestampsMixin):
    """User → message reaction. Peer-to-peer only — agents do NOT react.

    Author is always a User (no agent FK). Emoji is a short code from the
    curated set in ``donna.chat.emojis`` (e.g. ``"thumbsup"``). UI renders
    the Unicode character from that lookup.

    Unique on (message, emoji, author_user) → one user can attach each
    emoji at most once per message; clicking again toggles via DELETE.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name="reactions",
    )
    emoji = models.CharField(max_length=64)
    author_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="message_reactions",
    )

    class Meta:
        db_table = "message_reactions"
        constraints = [
            models.UniqueConstraint(
                fields=["message", "emoji", "author_user"],
                name="uq_reaction_user_message_emoji",
            ),
        ]
        indexes = [
            models.Index(fields=["message", "emoji"]),
        ]

    def __str__(self) -> str:
        return f"reaction({self.author_user_id}:{self.emoji}@{self.message_id})"
