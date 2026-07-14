"""
ChannelService — mutations for chat channels, messages, DMs, read-state.

Single code path for both transports:
- HTTP REST views call into the service.
- WS ``ChatConsumer`` calls into the same service.

Each mutation:
  1. Persists the DB change inside a transaction.
  2. Publishes a Channels ``group_send`` so WS subscribers in the affected
     group receive the event.
  3. (Optional) emits a Notification via ``NotificationService`` when the
     change deserves a notification (e.g. message in a DM you're a
     member of, mention, channel created in your workspace).

See plans/10-realtime-layer.md.
"""
from __future__ import annotations

import logging
from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import IntegrityError, transaction
from django.utils import timezone

from donna.workspaces.models import WorkspaceMembership

from .models import (
    AgentSession,
    Channel,
    ChannelMembership,
    ChannelPin,
    ChannelReadState,
    Message,
    MessageReaction,
)


logger = logging.getLogger(__name__)


# ── Channel group naming (kept centralized) ──────────────────────────────────
def channel_group(channel_id) -> str:
    """Channels ``group_add`` name for chat messages in one channel."""
    return f"chat-channel-{channel_id}"


def channel_typing_group(channel_id) -> str:
    return f"chat-channel-{channel_id}-typing"


def workspace_events_group(workspace_id) -> str:
    return f"workspace-{workspace_id}-events"


def presence_group(user_id) -> str:
    return f"presence-user-{user_id}"


def broadcast_agent_status(
    *,
    channel,
    agent_session,
    state: str,
    detail: str = "",
    eta: str = "",
) -> None:
    """Plan 13 §8.2 — surface ambient agent state to the channel.

    States the frontend chip understands:
    - ``typing``         — Q&A reply mid-flight (cheap chat turn)
    - ``drafting``       — drafter/planner mid-flight (writing an artifact)
    - ``waiting_on_user`` — paused on an AskUserQuestion (§1.3 / §1.5)
    - ``running_tool``   — dispatching tool calls this round
    - ``scheduled_for``  — has a Schedule that fires next at ``eta``
    - ``idle``           — back to default

    Best-effort: a missed status update never blocks the agent loop.
    """
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(
            channel_group(channel.id),
            {
                "type": "chat.agent.status",
                "payload": {
                    "session_id": str(agent_session.id),
                    "channel_id": str(channel.id),
                    "state": state,
                    "detail": detail,
                    "eta": eta,
                },
            },
        )
    except Exception:  # noqa: BLE001
        pass


def send_synthetic_agent_message(
    *,
    channel: "Channel",
    agent_session,
    body: str,
) -> "Message":
    """Plan 13 §7.1 — write an agent-authored message that LOOKS like the
    agent spoke without going through the normal user-message turn loop.

    Used by the schedule worker so a cron-driven kickoff lands as a
    visible message in the channel and the agent runner picks up the
    next turn naturally.
    """
    from donna.chat.models import Message
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer

    from donna.chat.models import Message

    message = Message.objects.create(
        channel=channel,
        author_agent=agent_session,
        body=body,
    )
    layer = get_channel_layer()
    if layer is not None:
        try:
            async_to_sync(layer.group_send)(
                channel_group(channel.id),
                {"type": "chat.message", "payload": _serialize_message(message)},
            )
        except Exception:  # noqa: BLE001 — broadcast is best-effort
            pass
    return message


def agent_run_group(run_id) -> str:
    return f"agent-run-{run_id}-tokens"


def _dispatch_agent_if_applicable(message: "Message") -> None:
    """Lazy import to avoid circular: tasks imports services for groups."""
    try:
        from .tasks import maybe_dispatch_agent
        maybe_dispatch_agent(message)
    except Exception:  # noqa: BLE001 — never let dispatch errors fail send_message
        logger.exception("agent_dispatch_hook_failed", extra={"message_id": str(message.id)})


def _force_dispatch_agent(message: "Message") -> None:
    """@donna direct address — always run an agent turn (bypasses heuristic).

    The agent worker's own turn_lock + already-replied checks make repeat
    dispatches a no-op, so it's safe to call alongside maybe_dispatch_agent
    if both fire.
    """
    try:
        from .tasks import run_agent_turn
        run_agent_turn.delay(str(message.channel_id), str(message.id))
    except Exception:  # noqa: BLE001
        logger.exception("agent_force_dispatch_failed", extra={"message_id": str(message.id)})


def _fanout_mention_notifications(message: "Message", users: list, flags: dict[str, bool]) -> None:
    """Create per-recipient notifications for @<user>, @channel, @everyone.

    Skips the author (no self-notifications). Best-effort: failures here
    must not roll the message back.
    """
    try:
        from donna.notifications.services import NotificationService
    except ImportError:
        logger.warning("notifications_service_unavailable")
        return

    recipients = {u.id for u in users}
    if flags.get("everyone"):
        recipients.update(
            WorkspaceMembership.objects
            .filter(workspace_id=message.channel.workspace_id)
            .exclude(user_id=message.author_user_id)
            .values_list("user_id", flat=True)
        )
    elif flags.get("channel"):
        recipients.update(
            ChannelMembership.objects
            .filter(channel_id=message.channel_id)
            .exclude(user_id=message.author_user_id)
            .values_list("user_id", flat=True)
        )

    # Self-mention sanity: never notify the author.
    recipients.discard(message.author_user_id)

    if not recipients:
        return

    svc = NotificationService()
    payload = {
        "channel_id": str(message.channel_id),
        "message_id": str(message.id),
        "preview":    (message.body or "")[:140],
    }
    for uid in recipients:
        try:
            # NotificationService is expected to expose a create(...) call.
            # Fall back to a direct ORM write if the API differs.
            create = getattr(svc, "create", None)
            if callable(create):
                create(user_id=uid, kind="mention", payload=payload)
            else:
                logger.debug(
                    "notification_service_create_missing",
                    extra={"user_id": str(uid)},
                )
        except Exception:  # noqa: BLE001
            logger.exception("mention_notification_failed", extra={"user_id": str(uid)})


def _record_agent_mention(message: "Message", channel: "Channel") -> None:
    """Append @donna mention to AgentSession.memory['mentions'] (cap last 50).

    Older entries are consolidated by AutoDream (plan 13 Phase 4). For now
    we keep the rolling buffer in-process so the agent's state builder can
    pull recent mentions as context at turn time.
    """
    try:
        session = AgentSession.objects.filter(channel=channel).first()
        if session is None:
            return
        memory = session.memory or {}
        mentions = list(memory.get("mentions") or [])
        mentions.append({
            "message_id":     str(message.id),
            "author_user_id": str(message.author_user_id) if message.author_user_id else None,
            "body_preview":   (message.body or "")[:500],
            "at":             message.created_at.isoformat() if message.created_at else None,
        })
        memory["mentions"] = mentions[-50:]
        session.memory = memory
        session.save(update_fields=["memory", "updated_at"])
    except Exception:  # noqa: BLE001
        logger.exception("agent_mention_record_failed", extra={"message_id": str(message.id)})


# ── Service ──────────────────────────────────────────────────────────────────
class ChannelService:
    """All chat mutations live here. Views + WS consumer call into it."""

    # ── Messages ────────────────────────────────────────────────────────────
    @staticmethod
    @transaction.atomic
    def send_message(
        *,
        channel: Channel,
        sender_user,
        body: str,
        client_msg_id: str | None = None,
        parent: Message | None = None,
    ) -> Message:
        """
        Persist a new message and push it to WS subscribers of the channel.
        Author is always ``sender_user``; agent-authored messages use a
        separate path (the agent worker writes the Message + group_send).

        Threading: pass ``parent`` to attach as a reply. Top-level posts
        leave it None. The UI enforces 1-level nesting (replies don't have
        their own threads).

        Mention parsing: body is scanned for ``@<handle>``, ``@donna``,
        ``@channel``, ``@everyone``. Tagged users get notifications.
        ``@donna`` additionally appends the message to the channel's
        ``AgentSession.memory['mentions']`` (long-term context) and
        dispatches the agent unconditionally.

        Agent dispatch hook (00j A1, 2026-06-14): after the row commits,
        ``maybe_dispatch_agent(message)`` decides whether to enqueue an
        agent turn. ``@donna`` short-circuits that decision via the
        mention path so the agent always runs on direct address.
        """
        from .mentions import parse as parse_mentions

        message = Message.objects.create(
            channel=channel,
            author_user=sender_user,
            body=body,
            parent=parent,
        )

        # Parse + persist mentions.
        mention_users, mention_flags = parse_mentions(body, channel)
        if mention_users:
            message.mentions.set(mention_users)
        if any(mention_flags.values()):
            message.mention_flags = mention_flags
            message.save(update_fields=["mention_flags", "updated_at"])

        ChannelService._broadcast(
            channel_group(channel.id),
            {
                "type":    "chat.message.created",
                "payload": _serialize_message(message, client_msg_id=client_msg_id),
            },
        )

        # Notifications fanout (mentions only — generic message notifs
        # are handled elsewhere if at all).
        if mention_users or any(mention_flags.values()):
            transaction.on_commit(
                lambda: _fanout_mention_notifications(message, mention_users, mention_flags)
            )

        # @donna sugar — long-term memory + force agent dispatch.
        if mention_flags.get("donna"):
            transaction.on_commit(lambda: _record_agent_mention(message, channel))
            transaction.on_commit(lambda: _force_dispatch_agent(message))
        else:
            # Normal dispatch heuristic (DM auto-replies, etc).
            transaction.on_commit(lambda: _dispatch_agent_if_applicable(message))
        return message

    @staticmethod
    @transaction.atomic
    def edit_message(*, message: Message, body: str) -> Message:
        message.body = body
        message.save(update_fields=["body", "updated_at"])
        ChannelService._broadcast(
            channel_group(message.channel_id),
            {
                "type":    "chat.message.updated",
                "payload": _serialize_message(message),
            },
        )
        return message

    @staticmethod
    @transaction.atomic
    def delete_message(*, message: Message) -> None:
        cid = message.channel_id
        mid = str(message.id)
        message.delete()
        ChannelService._broadcast(
            channel_group(cid),
            {
                "type":    "chat.message.deleted",
                "payload": {"channel_id": str(cid), "message_id": mid},
            },
        )

    @staticmethod
    def authorize_delete_message(*, user, message: Message) -> None:
        """
        Raise ``PermissionError`` unless ``user`` may delete ``message``.

        Permitted callers:
        - The message author.
        - A ``ChannelMembership.Role.ADMIN`` on the message's channel.

        Called from both ``MessageDetailView.delete`` (REST) and
        ``ChatConsumer._action_delete_message`` (WS) so the two transports
        always agree.
        """
        if message.author_user_id == user.id:
            return
        is_admin = ChannelMembership.objects.filter(
            channel_id=message.channel_id,
            user_id=user.id,
            role=ChannelMembership.Role.ADMIN,
        ).exists()
        if not is_admin:
            raise PermissionError(
                "only the author or a channel admin can delete a message"
            )

    # ── DMs ─────────────────────────────────────────────────────────────────
    @staticmethod
    @transaction.atomic
    def get_or_create_dm(caller, peer, *, workspace_id=None) -> Channel:
        """
        Return the 1:1 DM Channel between ``caller`` and ``peer``,
        creating one if it doesn't exist.

        ``workspace_id`` disambiguates when caller and peer share more
        than one workspace. Clients should always pass it explicitly —
        for backward compatibility, omitting it falls back to "first
        overlapping workspace" with a warning log. Plan
        ``04-roadmap.md`` flags removal of the legacy fallback after
        the rollout window.
        """
        if caller.id == peer.id:
            raise ValueError("Cannot open a DM with yourself.")

        # Find overlapping workspaces.
        caller_ws_ids = set(
            WorkspaceMembership.objects
            .filter(user_id=caller.id)
            .values_list("workspace_id", flat=True)
        )
        peer_ws_ids = set(
            WorkspaceMembership.objects
            .filter(user_id=peer.id)
            .values_list("workspace_id", flat=True)
        )
        shared = caller_ws_ids & peer_ws_ids
        if not shared:
            raise PermissionError("Users do not share a workspace.")

        if workspace_id is not None:
            from uuid import UUID
            try:
                wsid = UUID(str(workspace_id))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"invalid workspace_id: {workspace_id!r}"
                ) from exc
            if wsid not in shared:
                raise PermissionError(
                    "caller and peer do not both belong to the requested workspace"
                )
            target_wsid = wsid
        else:
            # Deprecated path — pick the first overlapping workspace. Log
            # so we can track when clients still rely on this.
            logger.warning(
                "get_or_create_dm_without_workspace_id",
                extra={
                    "caller_id":    str(caller.id),
                    "peer_id":      str(peer.id),
                    "shared_count": len(shared),
                },
            )
            target_wsid = next(iter(shared))

        # Look for an existing DM with exactly these two members.
        existing = (
            Channel.objects.filter(
                kind=Channel.Kind.DIRECT,
                workspace_id=target_wsid,
                memberships__user_id__in=[caller.id, peer.id],
            )
            .distinct()
        )
        for ch in existing:
            member_ids = set(
                ch.memberships.values_list("user_id", flat=True)
            )
            if member_ids == {caller.id, peer.id}:
                return ch

        # Create
        try:
            channel = Channel.objects.create(
                kind=Channel.Kind.DIRECT,
                visibility=Channel.Visibility.PRIVATE,
                workspace_id=target_wsid,
                name="",
                slug="",
            )
            ChannelMembership.objects.bulk_create(
                [
                    ChannelMembership(channel=channel, user_id=caller.id),
                    ChannelMembership(channel=channel, user_id=peer.id),
                ]
            )
        except IntegrityError:
            # Race — another transaction beat us to it. Re-query (with
            # the same workspace_id so we don't loop on a different one).
            return ChannelService.get_or_create_dm(
                caller, peer, workspace_id=target_wsid
            )

        # Notify the peer's WS so a DM list refresh isn't needed.
        ChannelService._broadcast(
            presence_group(peer.id),
            {
                "type":    "chat.dm.opened",
                "payload": {
                    "channel_id":    str(channel.id),
                    "peer_user_id":  str(caller.id),
                    "workspace_id":  str(target_wsid),
                },
            },
        )
        return channel

    @staticmethod
    @transaction.atomic
    def create_group_dm(*, workspace, users: list) -> Channel:
        """
        Open a group DM (a ``Channel(kind=DIRECT)`` with N≥2 members).

        Semantics — exact-set-match: if a DIRECT channel with *exactly*
        this member set already exists in the workspace, return it.
        Otherwise create a new one. We deliberately do not treat subsets
        as a match (a group of {A, B, C} is distinct from {A, B}).

        ``users`` must all belong to ``workspace``. The caller is
        responsible for verifying authorization before calling.
        """
        if len(users) < 2:
            raise ValueError("group DM needs at least 2 distinct members")
        unique_ids = {u.id for u in users}
        if len(unique_ids) != len(users):
            raise ValueError("duplicate members not allowed")

        # All members must belong to the workspace.
        ws_member_ids = set(
            WorkspaceMembership.objects
            .filter(user_id__in=unique_ids, workspace_id=workspace.id)
            .values_list("user_id", flat=True)
        )
        if ws_member_ids != unique_ids:
            raise PermissionError(
                "all members must belong to the target workspace"
            )

        # Look for an exact-set-match existing group DM.
        candidates = (
            Channel.objects.filter(
                kind=Channel.Kind.DIRECT,
                workspace=workspace,
                memberships__user_id__in=unique_ids,
            )
            .distinct()
        )
        for ch in candidates:
            member_ids = set(ch.memberships.values_list("user_id", flat=True))
            if member_ids == unique_ids:
                return ch

        # Create
        try:
            channel = Channel.objects.create(
                kind=Channel.Kind.DIRECT,
                visibility=Channel.Visibility.PRIVATE,
                workspace=workspace,
                name="",
                slug="",
            )
            ChannelMembership.objects.bulk_create(
                [ChannelMembership(channel=channel, user_id=uid) for uid in unique_ids]
            )
        except IntegrityError:
            # Race — re-query.
            return ChannelService.create_group_dm(
                workspace=workspace, users=users
            )

        # Notify every member's WS so their sidebar surfaces the room.
        member_ids_str = sorted(str(uid) for uid in unique_ids)
        for uid in unique_ids:
            ChannelService._broadcast(
                presence_group(uid),
                {
                    "type":    "chat.dm.opened",
                    "payload": {
                        "channel_id":   str(channel.id),
                        "members":      member_ids_str,
                        "workspace_id": str(workspace.id),
                    },
                },
            )
        return channel

    # ── Read state ──────────────────────────────────────────────────────────
    @staticmethod
    @transaction.atomic
    def advance_read_pointer(*, user, channel: Channel, message: Message) -> ChannelReadState:
        """Move the (user, channel) pointer to ``message`` if it's a forward move."""
        state, _ = ChannelReadState.objects.select_for_update().get_or_create(
            user=user, channel=channel
        )

        # Only advance — never regress.
        if (
            state.last_read_message_id is None
            or state.last_read_message_id != message.id
        ):
            state.last_read_message = message
            state.last_read_at = timezone.now()
            state.save(update_fields=["last_read_message", "last_read_at", "updated_at"])

        ChannelService._broadcast(
            channel_group(channel.id),
            {
                "type":    "chat.read.advanced",
                "payload": {
                    "channel_id": str(channel.id),
                    "user_id":    str(user.id),
                    "message_id": str(message.id),
                    "read_at":    state.last_read_at.isoformat() if state.last_read_at else None,
                },
            },
        )
        return state

    @staticmethod
    def unread_count(*, user, channel: Channel) -> int:
        try:
            state = ChannelReadState.objects.get(user=user, channel=channel)
        except ChannelReadState.DoesNotExist:
            return Message.objects.filter(channel=channel).count()
        if state.last_read_message_id is None:
            return Message.objects.filter(channel=channel).count()
        last = state.last_read_message
        return Message.objects.filter(
            channel=channel, created_at__gt=last.created_at
        ).count()

    # ── Typing (ephemeral) ──────────────────────────────────────────────────
    @staticmethod
    def emit_typing(*, channel_id, user_id) -> None:
        ChannelService._broadcast(
            channel_typing_group(channel_id),
            {
                "type":    "chat.typing",
                "payload": {"channel_id": str(channel_id), "user_id": str(user_id)},
            },
        )

    # ── Channel lifecycle events (member added, channel created) ────────────
    @staticmethod
    def emit_channel_created(channel: Channel) -> None:
        ChannelService._broadcast(
            workspace_events_group(channel.workspace_id),
            {
                "type":    "chat.channel.created",
                "payload": _serialize_channel(channel),
            },
        )

    @staticmethod
    def emit_channel_updated(channel: Channel) -> None:
        ChannelService._broadcast(
            workspace_events_group(channel.workspace_id),
            {
                "type":    "chat.channel.updated",
                "payload": _serialize_channel(channel),
            },
        )

    @staticmethod
    def emit_channel_deleted(channel_id: str, workspace_id: str) -> None:
        ChannelService._broadcast(
            workspace_events_group(workspace_id),
            {
                "type":    "chat.channel.deleted",
                "payload": {"channel_id": str(channel_id)},
            },
        )

    @staticmethod
    def emit_member_added(channel: Channel, user_id) -> None:
        ChannelService._broadcast(
            channel_group(channel.id),
            {
                "type":    "chat.channel.member.added",
                "payload": {"channel_id": str(channel.id), "user_id": str(user_id)},
            },
        )

    # ── Membership mutations ────────────────────────────────────────────────
    @staticmethod
    @transaction.atomic
    def add_member(
        *,
        channel: Channel,
        user,
        added_by,
        role: str = ChannelMembership.Role.MEMBER,
    ) -> ChannelMembership:
        """
        Add ``user`` to ``channel`` with ``role``. Idempotent: if the user
        is already a member, the existing row is returned unchanged.

        Validates the target user belongs to the channel's workspace. The
        caller (view / consumer) is responsible for upstream authorization
        (admin-add vs. self-join) before calling this.

        Broadcasts on two groups (the "dual broadcast" pattern from
        ``plans/10-realtime-layer.md``):

        - ``chat-channel-{id}`` — existing members see ``channel.member.added``.
        - ``presence-user-{new_member_uid}`` — the invitee's WS receives
          ``channel.added.to_you`` with the full channel payload so the
          sidebar can update without a refresh.
        """
        if not WorkspaceMembership.objects.filter(
            user_id=user.id, workspace_id=channel.workspace_id
        ).exists():
            raise PermissionError("user does not belong to this workspace")

        membership, created = ChannelMembership.objects.get_or_create(
            channel=channel,
            user=user,
            defaults={"role": role},
        )
        if not created:
            return membership

        # 1. Broadcast to the channel group (existing members).
        ChannelService.emit_member_added(channel, user.id)

        # 2. Broadcast to the new member's presence group so their UI
        #    learns about the channel without a list refetch.
        ChannelService._broadcast(
            presence_group(user.id),
            {
                "type":    "chat.channel.added.to_you",
                "payload": {
                    "channel":  _serialize_channel(channel),
                    "added_by": str(added_by.id),
                    "role":     role,
                },
            },
        )
        return membership

    @staticmethod
    def join_public_channels(*, workspace, user, added_by=None) -> list[ChannelMembership]:
        """Add ``user`` to every PUBLIC named channel in ``workspace``.

        Called when someone joins the workspace (invite-accept or admin-add)
        so the Slack-style rule "everyone sees every public channel" holds
        without a manual self-join. Idempotent via ``add_member``.
        """
        channels = Channel.objects.filter(
            workspace=workspace,
            kind=Channel.Kind.CHANNEL,
            visibility=Channel.Visibility.PUBLIC,
        )
        memberships = []
        for channel in channels:
            memberships.append(
                ChannelService.add_member(
                    channel=channel,
                    user=user,
                    added_by=added_by or user,
                    role=ChannelMembership.Role.MEMBER,
                )
            )
        return memberships

    @staticmethod
    def add_all_workspace_members(*, channel: Channel, added_by) -> list[ChannelMembership]:
        """Add every workspace member to ``channel``.

        Called when a PUBLIC channel is created (or flipped private→public)
        so it appears for everyone. ``add_member`` is idempotent, so the
        creator/existing members (incl. their ADMIN role) are left unchanged.
        """
        from donna.users.models import User

        user_ids = WorkspaceMembership.objects.filter(
            workspace_id=channel.workspace_id
        ).values_list("user_id", flat=True)
        memberships = []
        for user in User.objects.filter(id__in=list(user_ids)):
            memberships.append(
                ChannelService.add_member(
                    channel=channel,
                    user=user,
                    added_by=added_by,
                    role=ChannelMembership.Role.MEMBER,
                )
            )
        return memberships

    @staticmethod
    @transaction.atomic
    def remove_member(*, channel: Channel, user, removed_by) -> bool:
        """
        Remove ``user`` from ``channel``. Returns True if a membership
        row was deleted, False if there was nothing to remove.

        Caller is responsible for upstream authorization (self-leave vs.
        admin-kick).
        """
        deleted, _ = ChannelMembership.objects.filter(
            channel=channel, user=user
        ).delete()
        if deleted == 0:
            return False

        # Tell remaining channel members.
        ChannelService._broadcast(
            channel_group(channel.id),
            {
                "type":    "chat.channel.member.removed",
                "payload": {
                    "channel_id": str(channel.id),
                    "user_id":    str(user.id),
                    "removed_by": str(removed_by.id),
                },
            },
        )
        # Tell the removed user's WS so their sidebar can drop the channel.
        ChannelService._broadcast(
            presence_group(user.id),
            {
                "type":    "chat.channel.removed.from_you",
                "payload": {
                    "channel_id": str(channel.id),
                    "removed_by": str(removed_by.id),
                },
            },
        )
        return True

    @staticmethod
    @transaction.atomic
    def set_member_role(*, channel: Channel, user_id, role) -> ChannelMembership:
        """Change a channel member's role (admin/member). Caller authorizes.

        Guards the last admin so a channel can't be left without one.
        """
        if role not in dict(ChannelMembership.Role.choices):
            raise ValidationError({"role": "Invalid role."})
        try:
            membership = (
                ChannelMembership.objects
                .select_for_update()
                .get(channel=channel, user_id=user_id)
            )
        except ChannelMembership.DoesNotExist as exc:
            raise ValidationError("User is not a member of this channel.") from exc
        demoting_admin = (
            membership.role == ChannelMembership.Role.ADMIN
            and role != ChannelMembership.Role.ADMIN
        )
        if demoting_admin and channel.memberships.filter(
            role=ChannelMembership.Role.ADMIN
        ).count() <= 1:
            raise ValidationError("Cannot demote the last channel admin.")
        if membership.role != role:
            membership.role = role
            membership.save(update_fields=["role"])
            ChannelService._broadcast(
                channel_group(channel.id),
                {
                    "type":    "chat.channel.member.role_changed",
                    "payload": {
                        "channel_id": str(channel.id),
                        "user_id":    str(user_id),
                        "role":       role,
                    },
                },
            )
        return membership

    # ── Pins ────────────────────────────────────────────────────────────────
    @staticmethod
    @transaction.atomic
    def pin_channel(*, user, channel: Channel) -> ChannelPin:
        """Idempotent per-user pin."""
        pin, _ = ChannelPin.objects.get_or_create(user=user, channel=channel)
        ChannelService._broadcast(
            presence_group(user.id),
            {
                "type":    "chat.channel.pinned",
                "payload": {"channel_id": str(channel.id)},
            },
        )
        return pin

    @staticmethod
    @transaction.atomic
    def unpin_channel(*, user, channel: Channel) -> bool:
        deleted, _ = ChannelPin.objects.filter(user=user, channel=channel).delete()
        ChannelService._broadcast(
            presence_group(user.id),
            {
                "type":    "chat.channel.unpinned",
                "payload": {"channel_id": str(channel.id)},
            },
        )
        return deleted > 0

    # ── Reactions ───────────────────────────────────────────────────────────
    @staticmethod
    @transaction.atomic
    def add_reaction(*, user, message: Message, emoji: str) -> MessageReaction:
        """Attach an emoji reaction. Idempotent (same user × emoji × message)."""
        from .emojis import is_valid

        if not is_valid(emoji):
            raise ValueError(f"unknown emoji: {emoji!r}")

        reaction, created = MessageReaction.objects.get_or_create(
            message=message, emoji=emoji, author_user=user,
        )
        if created:
            ChannelService._broadcast(
                channel_group(message.channel_id),
                {
                    "type":    "chat.reaction.added",
                    "payload": {
                        "message_id": str(message.id),
                        "channel_id": str(message.channel_id),
                        "emoji":      emoji,
                        "user_id":    str(user.id),
                    },
                },
            )
        return reaction

    @staticmethod
    @transaction.atomic
    def remove_reaction(*, user, message: Message, emoji: str) -> bool:
        deleted, _ = MessageReaction.objects.filter(
            message=message, emoji=emoji, author_user=user,
        ).delete()
        if deleted:
            ChannelService._broadcast(
                channel_group(message.channel_id),
                {
                    "type":    "chat.reaction.removed",
                    "payload": {
                        "message_id": str(message.id),
                        "channel_id": str(message.channel_id),
                        "emoji":      emoji,
                        "user_id":    str(user.id),
                    },
                },
            )
        return deleted > 0

    # ── Helpers ─────────────────────────────────────────────────────────────
    @staticmethod
    def _broadcast(group: str, event: dict[str, Any]) -> None:
        layer = get_channel_layer()
        if layer is None:
            logger.warning("channel_layer_missing", extra={"group": group})
            return
        # ``async_to_sync`` lets us call group_send from sync code (Celery
        # tasks, signal receivers, REST views). Channels supports both.
        async_to_sync(layer.group_send)(group, event)


# ── Serialization (kept tiny — DRF serializers handle the HTTP REST side) ────
def _serialize_message(message: Message, client_msg_id: str | None = None) -> dict:
    out = {
        "id":           str(message.id),
        "channel_id":   str(message.channel_id),
        "body":         message.body,
        "author_user":  str(message.author_user_id) if message.author_user_id else None,
        "author_agent": str(message.author_agent_id) if message.author_agent_id else None,
        "created_at":   message.created_at.isoformat() if message.created_at else None,
        "updated_at":   message.updated_at.isoformat() if message.updated_at else None,
        "client_msg_id": client_msg_id,
    }
    # Plan 13 §1.3 / §1.5 — emit HIL fields only when this row is a
    # question or answer. The chat fast path stays compact.
    if message.kind != Message.Kind.CHAT:
        out["server_kind"] = message.kind
        if message.kind == Message.Kind.QUESTION:
            out["question_options"] = message.question_options or []
            out["expires_at"] = (
                message.expires_at.isoformat() if message.expires_at else None
            )
        out["answer_payload"] = message.answer_payload
        if message.answered_message_id:
            out["answered_message"] = str(message.answered_message_id)
    return out


def _serialize_channel(channel: Channel) -> dict:
    return {
        "id":           str(channel.id),
        "kind":         channel.kind,
        "name":         channel.name,
        "slug":         channel.slug,
        "topic":        channel.topic,
        "visibility":   channel.visibility,
        "workspace_id": str(channel.workspace_id),
    }
