from __future__ import annotations

import uuid

# Alias the import: the Channel model defines a JSONField called
# ``settings`` which would otherwise shadow ``django.conf.settings`` for
# the rest of the class body (and break ``dj_settings.AUTH_USER_MODEL`` on
# the related fields below).
from django.conf import settings as dj_settings
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

    #: Channel-scoped behavior flags. Channel admins flip flags via PATCH;
    #: defaults below are intentionally conservative. Add a key here AND
    #: in ``DEFAULT_SETTINGS`` so callers using :meth:`get_setting` always
    #: see a deterministic value.
    #:
    #: Documented keys (Phase 2c):
    #:   - ``allow_member_pins``    — non-admin members may pin messages
    #:                                 (enforced in Phase 5a Pinning).
    #:   - ``allow_member_invites`` — non-admin members may add others
    #:                                 to a private channel. Enforced in
    #:                                 :class:`ChannelMembersView.post`.
    #:   - ``read_only``            — only admins / agents may post
    #:                                 (announcement channels). Enforced
    #:                                 in :meth:`ChannelService.send_message`.
    DEFAULT_SETTINGS: "dict[str, bool]" = {
        "allow_member_pins":    False,
        "allow_member_invites": False,
        "read_only":            False,
    }

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
    settings = models.JSONField(
        default=dict,
        blank=True,
        help_text="Per-channel behavior flags; see DEFAULT_SETTINGS for documented keys.",
    )

    # Relationships
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="channels",
    )

    members = models.ManyToManyField(
        dj_settings.AUTH_USER_MODEL,
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

    def get_setting(self, key: str) -> bool:
        """Return a settings flag with the documented default for ``key``."""
        if key in self.settings:
            return bool(self.settings[key])
        return bool(self.DEFAULT_SETTINGS.get(key, False))


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
        dj_settings.AUTH_USER_MODEL,
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
    """A message in a channel, authored by exactly one of: a User or an AgentSession."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    body = models.TextField()

    # Relationships
    channel = models.ForeignKey(
        Channel,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    author_user = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL,
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
        dj_settings.AUTH_USER_MODEL,
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
