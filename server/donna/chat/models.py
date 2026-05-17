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
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="channels",
    )
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
            models.CheckConstraint(
                condition=~models.Q(kind=Kind.DIRECT)
                | models.Q(visibility=Visibility.PRIVATE),
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
    channel = models.ForeignKey(
        Channel,
        on_delete=models.CASCADE,
        related_name="agent_sessions",
    )
    name = models.CharField(max_length=120, default="Donna")
    memory = models.JSONField(default=dict, blank=True)
    config = models.JSONField(default=dict, blank=True)
    last_active_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "agent_sessions"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name}@{self.channel_id}"


class Message(TimestampsMixin):
    """A message in a channel, authored by exactly one of: a User or an AgentSession."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
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
    body = models.TextField()

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
        ]


class Document(TimestampsMixin, UserAuditMixin):
    """A Cowork-style collaborative artifact created within a channel."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    channel = models.ForeignKey(
        Channel,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True)

    class Meta:
        db_table = "documents"
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return self.title
