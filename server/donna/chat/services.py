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
from django.db.models import Q
from django.utils import timezone

from donna.audit.services import AuditService
from donna.workspaces.models import WorkspaceMembership

from .models import (
    Channel,
    ChannelMembership,
    ChannelReadState,
    Message,
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


def agent_run_group(run_id) -> str:
    return f"agent-run-{run_id}-tokens"


# ── Service ──────────────────────────────────────────────────────────────────
class ChannelService:
    """All chat mutations live here. Views + WS consumer call into it."""

    # ── Role / visibility helpers ───────────────────────────────────────────
    @staticmethod
    def _workspace_role(*, user, workspace) -> str | None:
        return (
            WorkspaceMembership.objects
            .filter(user=user, workspace=workspace)
            .values_list("role", flat=True)
            .first()
        )

    @staticmethod
    def visible_channels(*, user, workspace, include_public: bool = False):
        """
        QuerySet of channels in ``workspace`` the user may *see in a list*.

        - Default: channels the user is a direct member of.
        - ``include_public=True``: also surface public named channels
          ("browse"), **except** when the caller is a GUEST — guests
          only see channels they were explicitly added to.

        DMs (``kind=DIRECT``) are always excluded from the
        include-public branch — public discovery of DMs isn't meaningful.
        """
        base = Channel.objects.filter(workspace=workspace)
        role = ChannelService._workspace_role(user=user, workspace=workspace)
        is_guest = role == WorkspaceMembership.Role.GUEST

        if include_public and not is_guest:
            qs = base.filter(
                Q(memberships__user=user)
                | Q(
                    visibility=Channel.Visibility.PUBLIC,
                    kind=Channel.Kind.CHANNEL,
                )
            )
        else:
            qs = base.filter(memberships__user=user)
        return qs.distinct()

    @staticmethod
    def refuse_if_guest(*, user, workspace, action: str = "perform this action") -> None:
        """Raise PermissionError if ``user`` is a GUEST in ``workspace``."""
        role = ChannelService._workspace_role(user=user, workspace=workspace)
        if role == WorkspaceMembership.Role.GUEST:
            raise PermissionError(f"guests cannot {action}")

    # ── Messages ────────────────────────────────────────────────────────────
    @staticmethod
    @transaction.atomic
    def send_message(*, channel: Channel, sender_user, body: str, client_msg_id: str | None = None) -> Message:
        """
        Persist a new message and push it to WS subscribers of the channel.
        Author is always ``sender_user``; agent-authored messages use a
        separate path (the agent worker writes the Message + group_send).
        """
        message = Message.objects.create(
            channel=channel,
            author_user=sender_user,
            body=body,
        )
        ChannelService._broadcast(
            channel_group(channel.id),
            {
                "type":    "chat.message.created",
                "payload": _serialize_message(message, client_msg_id=client_msg_id),
            },
        )
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
        """
        Move the (user, channel) pointer to ``message`` *iff* ``message``
        is strictly newer (by ``created_at``) than the existing pointer.

        Calls with an older or equal message are no-ops — the pointer
        never regresses. This matches the docstring contract that
        unread counts are monotonically decreasing for a given session.

        The broadcast still fires on every call (so concurrent clients
        can re-sync their UI even when the pointer didn't move on the
        server).
        """
        state, _ = ChannelReadState.objects.select_for_update().get_or_create(
            user=user, channel=channel
        )

        if state.last_read_message_id is None:
            advance = True
        else:
            current = state.last_read_message
            advance = current is None or message.created_at > current.created_at
        if advance:
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

        AuditService.record(
            action="channel.member.added",
            actor=added_by,
            workspace=channel.workspace,
            target=channel,
            context={
                "channel_id": str(channel.id),
                "user_id":    str(user.id),
                "role":       role,
            },
        )
        return membership

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

        AuditService.record(
            action="channel.member.removed",
            actor=removed_by,
            workspace=channel.workspace,
            target=channel,
            context={
                "channel_id": str(channel.id),
                "user_id":    str(user.id),
                "self_leave": str(user.id) == str(removed_by.id),
            },
        )
        return True

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
    return {
        "id":           str(message.id),
        "channel_id":   str(message.channel_id),
        "body":         message.body,
        "author_user":  str(message.author_user_id) if message.author_user_id else None,
        "author_agent": str(message.author_agent_id) if message.author_agent_id else None,
        "created_at":   message.created_at.isoformat() if message.created_at else None,
        "updated_at":   message.updated_at.isoformat() if message.updated_at else None,
        "client_msg_id": client_msg_id,
    }


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
