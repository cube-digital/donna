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

    ``mode`` (Plan 13 §2.1) gates which tools the agent can use this turn:
    chat (Q&A only), drafting (Q&A + draft mutations), planning (read-only
    rehearsal — no writes until user approves).
    """

    class Mode(models.TextChoices):
        CHAT = "chat", "chat"
        DRAFTING = "drafting", "drafting"
        PLANNING = "planning", "planning"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120, default="Donna")
    mode = models.CharField(max_length=16, choices=Mode.choices, default=Mode.CHAT)
    memory = models.JSONField(default=dict, blank=True)
    config = models.JSONField(default=dict, blank=True)
    last_active_at = models.DateTimeField(null=True, blank=True)

    # Plan 13 §5.2.2 — channel-resident named agents. When True, the
    # session belongs to a channel-installed teammate addressable via
    # ``@<resident_handle>`` (e.g. ContractBot installed in #legal).
    # The unique constraint below prevents two agents owning the same
    # handle in one channel.
    is_channel_resident = models.BooleanField(default=False)
    resident_handle = models.SlugField(max_length=40, blank=True, default="")

    # Relationships
    channel = models.ForeignKey(
        Channel,
        on_delete=models.CASCADE,
        related_name="agent_sessions",
    )

    class Meta:
        db_table = "agent_sessions"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["channel", "resident_handle"],
                condition=models.Q(is_channel_resident=True),
                name="uniq_resident_agent_per_channel",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name}@{self.channel_id}"


class SessionMemory(TimestampsMixin):
    """Plan 13 §4.1 + §4.4 — per-turn extracted notes.

    Replaces the unbounded ``AgentSession.memory`` JSONField for
    accumulating learnings. Each turn the post-turn extractor (Haiku)
    emits zero or more rows tagged by ``scope`` so cross-session reads
    can shard by relationship — "what does Donna know about Acme?" is a
    cheap index hit, not a full JSON scan.

    The ``scope`` discriminator:
    - ``user``    : facts about the active user
    - ``channel`` : facts about the channel itself (project, focus area)
    - ``peer``    : facts about another participant
    - ``project`` : facts about a cortex Project entity
    - ``org``     : facts about a client / vendor / peer org
    - ``self``    : facts the agent learned about its own behavior

    ``scope_ref`` is the foreign id (user_id / channel_id / project_id /
    org_id). Stored as a CharField so cross-app references stay loose;
    the cortex consolidation worker (§4.2) hydrates as needed.
    """

    class Scope(models.TextChoices):
        USER = "user", "user"
        CHANNEL = "channel", "channel"
        PEER = "peer", "peer"
        PROJECT = "project", "project"
        ORG = "org", "org"
        SELF = "self", "self"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        "AgentSession",
        on_delete=models.CASCADE,
        related_name="memory_entries",
    )
    turn_id = models.CharField(max_length=40)
    scope = models.CharField(
        max_length=16, choices=Scope.choices, default=Scope.USER,
    )
    scope_ref = models.CharField(max_length=80, blank=True, default="")
    body = models.TextField()
    confidence = models.FloatField(default=0.7)
    # Snapshot of the AutoDream daily worker's last consolidation pass,
    # so we don't re-consolidate already-merged notes. NULL = unprocessed.
    consolidated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "chat_session_memory"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["session", "scope"]),
            # §4.4 — cross-session lookup by (scope, scope_ref):
            # "show me everything Donna knows about Acme."
            models.Index(fields=["scope", "scope_ref"]),
            # AutoDream picks unprocessed rows.
            models.Index(
                fields=["consolidated_at"],
                condition=models.Q(consolidated_at__isnull=True),
                name="sessionmem_pending_idx",
            ),
        ]

    def __str__(self) -> str:
        body_preview = self.body[:60].replace("\n", " ")
        return f"[{self.scope}:{self.scope_ref}] {body_preview}"


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

    # Plan 13 §1.3 / §1.5 — HIL question/answer kind. ``chat`` (default)
    # behaves as before; ``question`` is an agent-authored message awaiting
    # user input; ``answer`` is the user's reply, linked via
    # ``answered_message``. ``answer_payload`` is mirrored onto the
    # question row on resolution so the agent can read it without a join.
    class Kind(models.TextChoices):
        CHAT = "chat", "chat"
        QUESTION = "question", "question"
        ANSWER = "answer", "answer"

    kind = models.CharField(
        max_length=16,
        choices=Kind.choices,
        default=Kind.CHAT,
    )
    question_options = models.JSONField(
        default=list,
        blank=True,
        help_text="Question-kind only: [{label, value, description}] for the picker.",
    )
    answer_payload = models.JSONField(
        null=True,
        blank=True,
        help_text="Set on a QUESTION row when answered, OR carries the answer body on an ANSWER row.",
    )
    answered_message = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="answers",
        help_text="ANSWER kind: points back to the QUESTION it resolves.",
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="QUESTION kind: cleanup cron retires the question after this time.",
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
            # Plan 13 §1.5 — cheap "open questions in this channel" query.
            models.Index(
                fields=["channel", "kind", "expires_at"],
                condition=models.Q(kind="question", answer_payload__isnull=True),
                name="msg_open_question_idx",
            ),
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


class Artifact(TimestampsMixin, UserAuditMixin):
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
        related_name="artifacts",
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

    # Plan 13 §6.1 + §6.3 — free-form metadata bag.
    #
    # §6.1 (MagicDocs): when the agent updates this artifact, a sibling
    #   "status" artifact tracks the agent's progress notes via
    #   ``metadata['status_artifact_id']``.
    # §6.3 (multi-audience): when the drafter emits N artifacts for N
    #   audiences, each carries ``metadata['audience'] = "team" |
    #   "customer" | "executive" | ...`` so the rail can group them.
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "artifacts"
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
