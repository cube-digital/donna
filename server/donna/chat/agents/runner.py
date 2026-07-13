"""Turn runner — bridges Celery task ↔ graph.

run_agent_turn() in tasks.py is the Celery entry; it:
1. Acquires the per-channel turn lock.
2. Loads channel + session + ctx.
3. Builds state from history.
4. Builds the per-turn tool registry.
5. Runs the graph.
6. Persists the final assistant message (Message + WS broadcast).
7. Updates AgentSession.memory + last_active_at.

This module groups the non-Celery helpers so the task body stays thin.
"""
from __future__ import annotations

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone

from donna.chat.agents.state.builder import AgentState
from donna.chat.models import AgentSession, Channel, Message
from donna.chat.services import channel_group, channel_typing_group


logger = logging.getLogger(__name__)


def emit_typing(channel: Channel, session: AgentSession, *, active: bool) -> None:
    """Emit chat.typing for the agent on the channel's typing group.

    Wraps the agent turn (active=True at start, active=False at end)
    so the FE renders Donna with a typing indicator like a human
    teammate. Payload carries ``author_agent`` instead of ``user_id``
    — FE matches on the present field.
    """
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(
            channel_typing_group(channel.id),
            {
                "type": "chat.typing",
                "payload": {
                    "channel_id": str(channel.id),
                    "author_agent": str(session.id),
                    "name": session.name,
                    "active": bool(active),
                },
            },
        )
    except Exception:  # noqa: BLE001 — typing is cosmetic; never fail the turn
        logger.warning("agent_typing_broadcast_failed", extra={
            "channel_id": str(channel.id),
            "active": active,
        })


def persist_agent_message(channel: Channel, session: AgentSession, body: str) -> Message:
    """Write the agent's final message + broadcast on chat-channel-{id}.

    Mirrors ``ChannelService._broadcast`` shape (chat.message.created)
    so the FE renders agent messages identically to human ones — except
    the author field is ``author_agent`` instead of ``author_user``.
    """
    message = Message.objects.create(
        channel=channel,
        author_agent=session,
        body=body,
        kind=Message.Kind.CHAT,
    )
    _broadcast_agent_message(channel, message)
    return message


def update_session_memory(session: AgentSession, state: AgentState) -> None:
    """A3 extends this with a Haiku-compacted rolling summary; the Q&A
    slice just bumps ``last_active_at`` so presence + ordering stay fresh."""
    session.last_active_at = timezone.now()
    session.save(update_fields=["last_active_at", "updated_at"])


def _broadcast_agent_message(channel: Channel, message: Message) -> None:
    layer = get_channel_layer()
    if layer is None:
        logger.warning("channel_layer_missing")
        return
    async_to_sync(layer.group_send)(
        channel_group(channel.id),
        {
            "type": "chat.message.created",
            "payload": {
                "id": str(message.id),
                "channel_id": str(message.channel_id),
                "body": message.body,
                "author_user": None,
                "author_agent": str(message.author_agent_id) if message.author_agent_id else None,
                "created_at": message.created_at.isoformat() if message.created_at else None,
                "updated_at": message.updated_at.isoformat() if message.updated_at else None,
                "client_msg_id": None,
            },
        },
    )
