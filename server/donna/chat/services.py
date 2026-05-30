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

    # ── DMs ─────────────────────────────────────────────────────────────────
    @staticmethod
    @transaction.atomic
    def get_or_create_dm(caller, peer) -> Channel:
        """
        Return the DM Channel between caller and peer in any workspace
        they both belong to. Creates one if none exists.

        v1 uses the first overlapping workspace; future iterations may
        prompt the user when they share multiple workspaces.
        """
        if caller.id == peer.id:
            raise ValueError("Cannot open a DM with yourself.")

        # Find an overlapping workspace.
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

        workspace_id = next(iter(shared))

        # Look for an existing DM with exactly these two members.
        existing = (
            Channel.objects.filter(
                kind=Channel.Kind.DIRECT,
                workspace_id=workspace_id,
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
                workspace_id=workspace_id,
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
            # Race — another transaction beat us to it. Re-query.
            return ChannelService.get_or_create_dm(caller, peer)

        # Notify the peer's WS so a DM list refresh isn't needed.
        ChannelService._broadcast(
            presence_group(peer.id),
            {
                "type":    "chat.dm.opened",
                "payload": {
                    "channel_id":    str(channel.id),
                    "peer_user_id":  str(caller.id),
                    "workspace_id":  str(workspace_id),
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
