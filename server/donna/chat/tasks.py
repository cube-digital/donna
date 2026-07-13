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
from donna.chat.models import AgentSession, Channel, Message

# Register MagicDocs status updater task name with the worker. The task is
# defined in donna.chat.agents.magicdocs.draft_status_updater but Celery's
# autodiscover only walks <app>.tasks — importing here makes it visible.
from donna.chat.agents.magicdocs import draft_status_updater  # noqa: F401


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
            # Plan 13 §8.2 — ambient drafting chip.
            try:
                from donna.chat.services import broadcast_agent_status
                # Q&A turns surface as "typing…" (cheap chat reply);
                # drafting/plan-mode turns surface as "drafting…" so
                # the user sees the heavier work signaled differently.
                status_state = (
                    "drafting"
                    if session.mode in (AgentSession.Mode.DRAFTING, AgentSession.Mode.PLANNING)
                    else "typing"
                )
                broadcast_agent_status(
                    channel=channel, agent_session=session,
                    state=status_state,
                    detail=f"mode={session.mode}",
                )
            except Exception:  # noqa: BLE001
                pass
            try:
                ctx = ToolContext(
                    workspace=channel.workspace,
                    user=triggering.author_user,
                    channel=channel,
                    agent_session=session,
                )
                state = build_state(channel, session)
                # Plan 13 §2.1: mode-gated registry. Prefer session.mode;
                # fall back to legacy config["draft_enabled"] shim so
                # existing rows w/o a migrated mode still behave correctly.
                mode = session.mode
                draft_enabled = bool((session.config or {}).get("draft_enabled", True))
                registry = build_registry(
                    channel=channel, mode=mode, draft_enabled=draft_enabled,
                )
                state = run_graph(state, ctx, registry)

                persist_agent_message(channel, session, state.final_text or "")
                update_session_memory(session, state)
            finally:
                emit_typing(channel, session, active=False)
                # §8.2 — clear the chip when the turn ends.
                try:
                    from donna.chat.services import broadcast_agent_status
                    broadcast_agent_status(
                        channel=channel, agent_session=session,
                        state="idle",
                    )
                except Exception:  # noqa: BLE001
                    pass

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


# ── Plan 13 §1.5 — HIL suspend/resume + cleanup ─────────────────────────────
@shared_task(name="chat.resume_turn")
def resume_turn(question_message_id: str) -> None:
    """Resume a turn previously suspended by ``AskUserQuestion``.

    Looks up the QUESTION message, pulls the originating channel +
    session, and rekicks ``run_agent_turn`` against the ANSWER row. The
    graph-state replay itself is owned by the runner — this task just
    schedules it. Full graph-state preservation across the suspend
    boundary is groundwork for Phase 3.1 (output-cap recovery); for the
    v1 ship we synthesize a synthetic resume message that carries the
    answer payload so the LLM picks up the thread.
    """
    try:
        question = Message.objects.select_related(
            "channel", "author_agent",
        ).get(id=question_message_id, kind=Message.Kind.QUESTION)
    except Message.DoesNotExist:
        logger.warning("resume_turn_missing_question", extra={"id": question_message_id})
        return
    answer = question.answers.order_by("-created_at").first()
    if answer is None:
        logger.warning("resume_turn_no_answer", extra={"id": question_message_id})
        return
    # Reuse the normal entrypoint — the ANSWER message is what we run the
    # turn against. The LLM sees the question + answer naturally in
    # channel history when the state builder rebuilds context.
    run_agent_turn.delay(str(question.channel_id), str(answer.id))


@shared_task(name="chat.run_subagent_async")
def run_subagent_async(
    *,
    subagent_type: str,
    prompt: str,
    parent_session_id: str,
    parent_channel_id: str,
    job_id: str,
) -> dict:
    """Plan 13 §5.1 — async subagent worker.

    Runs the same forked graph as the sync path but in a background
    Celery task. Posts the synthesized text as an agent message back
    into the parent channel so the parent's next turn picks it up
    naturally (no special integration with state.builder needed).
    """
    from donna.chat.agents.subagents import resolve
    from donna.chat.agents.tools.agent_tool import run_subagent_sync
    from donna.chat.agents.tools.base import ToolContext

    defn = resolve(subagent_type)
    if defn is None:
        logger.warning("subagent_async_unknown_type", extra={
            "subagent_type": subagent_type, "job_id": job_id,
        })
        return {"job_id": job_id, "error": "unknown_subagent_type"}

    try:
        channel = Channel.objects.select_related("workspace").get(id=parent_channel_id)
        session = AgentSession.objects.get(id=parent_session_id)
    except (Channel.DoesNotExist, AgentSession.DoesNotExist):
        logger.warning("subagent_async_missing_parent", extra={"job_id": job_id})
        return {"job_id": job_id, "error": "missing_parent"}

    ctx = ToolContext(
        workspace=channel.workspace,
        user=None,
        channel=channel,
        agent_session=session,
    )
    out = run_subagent_sync(defn=defn, prompt=prompt, parent_ctx=ctx)
    text = out.get("text") or ""
    if text:
        persist_agent_message(
            channel, session,
            f"[subagent:{defn.name}] {text}",
        )
    return {"job_id": job_id, "rounds": out.get("rounds", 0)}


@shared_task(name="chat.expire_open_questions")
def expire_open_questions() -> dict:
    """Beat-driven cleanup — retire questions past their ``expires_at``.

    Posts a system answer ("Question timed out") on each one so the
    frontend can de-render the picker, then marks them resolved by
    setting ``answer_payload={"expired": true}``.
    """
    from django.utils import timezone

    now = timezone.now()
    expired = list(
        Message.objects
        .filter(
            kind=Message.Kind.QUESTION,
            answer_payload__isnull=True,
            expires_at__lt=now,
        )
        .only("id")[:200]
    )
    for q in expired:
        q.answer_payload = {"expired": True}
        q.save(update_fields=["answer_payload", "updated_at"])
    return {"expired": len(expired)}
