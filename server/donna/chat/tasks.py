"""Chat Celery tasks — agent turn dispatcher.

``run_agent_turn`` is the Q&A entry point: called from
``ChannelService.send_message`` via ``transaction.on_commit`` when a
user message lands in a DM or @-mentions Donna.

Anti-loop: ``maybe_dispatch_agent`` short-circuits when the inbound
message is itself agent-authored. Without this guard, the agent's own
reply would re-trigger a turn → infinite spiral.
"""
from __future__ import annotations

import logging

from celery import shared_task

from donna.chat.agents.graph import run_graph
from donna.chat.agents.locks import TurnBusy, turn_lock
from donna.chat.agents.runner import (
    emit_typing,
    persist_agent_message,
    update_session_memory,
)
from donna.chat.agents.state.builder import build_state
from donna.chat.agents.tools.base import ToolContext
from donna.chat.agents.tools.factory import build_registry
from donna.chat.models import Channel, Message


logger = logging.getLogger(__name__)


# ── Dispatcher hook ─────────────────────────────────────────────────


# Mention pattern (interim until a proper Mention model lands in
# comm-platform Phase 4a). Case-insensitive substring match on session.name.
def _mentioned(body: str, agent_name: str) -> bool:
    return f"@{agent_name.lower()}" in (body or "").lower()


def maybe_dispatch_agent(message: Message) -> None:
    """Decide whether this message should trigger an agent turn.

    Rules:
    - Skip if author_agent is set (anti-loop).
    - DM channel → always dispatch.
    - Named channel → dispatch only when the message mentions the agent.
    """
    if message.author_agent_id is not None:
        return

    session = message.channel.agent_sessions.first()
    if session is None:
        return  # channel has no agent attached

    is_dm = message.channel.kind == Channel.Kind.DIRECT
    if not (is_dm or _mentioned(message.body, session.name)):
        return

    run_agent_turn.delay(str(message.channel_id), str(message.id))


# ── Celery task ─────────────────────────────────────────────────────


@shared_task(bind=True, name="chat.run_agent_turn", max_retries=3)
def run_agent_turn(self, channel_id: str, message_id: str) -> None:
    """Execute one agent turn for the given (channel, triggering message)."""
    channel: Channel | None = None
    session = None
    try:
        with turn_lock(channel_id):
            channel = (
                Channel.objects
                .select_related("workspace")
                .get(id=channel_id)
            )
            session = channel.agent_sessions.first()
            if session is None:
                logger.info("no_agent_session_skip_turn", extra={"channel_id": channel_id})
                return

            try:
                triggering = Message.objects.select_related("author_user").get(id=message_id)
            except Message.DoesNotExist:
                logger.warning("trigger_message_missing", extra={"message_id": message_id})
                return

            # Colleague-mode WS: typing on (start) → wraps the whole turn,
            # off (end) regardless of success/error. Cosmetic — never
            # fails the turn.
            emit_typing(channel, session, active=True)
            try:
                ctx = ToolContext(
                    workspace=channel.workspace,
                    user=triggering.author_user,
                    channel=channel,
                    agent_session=session,
                )
                state = build_state(channel, session)
                draft_enabled = bool((session.config or {}).get("draft_enabled", True))
                registry = build_registry(channel=channel, draft_enabled=draft_enabled)
                state = run_graph(state, ctx, registry)

                persist_agent_message(channel, session, state.final_text or "")
                update_session_memory(session, state)
            finally:
                emit_typing(channel, session, active=False)

    except TurnBusy as exc:
        logger.info("turn_busy_retry", extra={"channel_id": channel_id, "detail": str(exc)})
        raise self.retry(exc=exc, countdown=5)
    except Exception:
        # Best-effort typing-off on outer failure so the indicator
        # doesn't get stuck if the lock acquired but body crashed.
        if channel is not None and session is not None:
            try:
                emit_typing(channel, session, active=False)
            except Exception:  # noqa: BLE001
                pass
        logger.exception("agent_turn_failed", extra={
            "channel_id": channel_id,
            "message_id": message_id,
        })
        raise
