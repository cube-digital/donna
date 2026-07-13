"""Plan 13 §1.3 + §1.5 — AskUserQuestion tool.

The agent posts a question into the channel as a ``Message(kind=question)``
and stores a marker on the session so the runner can suspend cleanly.
The frontend renders the question with an options picker; on user answer
``POST /api/v1/chat/messages/<id>/answer`` writes the ANSWER message,
mirrors the payload onto the QUESTION row, and re-queues the turn via
``chat.resume_turn``.

Multi-step (§1.5): the same tool may be called N times per turn — each
call creates its own QUESTION row. Open questions are tracked via the
``msg_open_question_idx`` partial index.
"""
from __future__ import annotations

from datetime import timedelta
from typing import ClassVar, List, Optional

from django.utils import timezone
from pydantic import BaseModel, Field

from donna.chat.agents.tools.base import DonnaTool, ToolContext, ToolResult


DEFAULT_TTL = timedelta(hours=24)


class QuestionOption(BaseModel):
    label: str = Field(description="User-visible label.")
    value: str = Field(description="Machine value returned in the answer payload.")
    description: str = Field(default="", description="Optional hover/help text.")


class AskUserQuestionArgs(BaseModel):
    """Arguments for AskUserQuestionTool.

    ``options`` is required even for free-text questions — pass a single
    option ``{label: "Reply", value: "free_text"}`` to signal that any
    text answer is acceptable. The frontend collapses single-option
    questions to a textarea automatically.
    """

    prompt: str = Field(description="The question to ask the user (≤ 280 chars).")
    options: List[QuestionOption] = Field(
        default_factory=list,
        description="Picker options. Empty = free-text only.",
    )
    expires_in_minutes: Optional[int] = Field(
        default=None,
        description=(
            "Override default 24h TTL. None = use default. Past expiry "
            "the cleanup cron retires the question."
        ),
    )


class AskUserQuestionTool(DonnaTool):
    """Suspend the turn on a user-facing question.

    Returns ``ToolResult`` with the new ``Message.id`` and a marker the
    runner uses to know the turn must wait. Does NOT itself raise the
    suspend signal — that's the runner's job; here we just persist.
    """

    name: ClassVar[str] = "ask_user_question"
    description: ClassVar[str] = (
        "Ask the user a clarifying question and pause the turn until they "
        "answer. Use when an action is ambiguous and the wrong default "
        "carries social cost. Returns the question_id; the runner pauses "
        "and resumes when the user replies."
    )
    args_model: ClassVar[type[BaseModel]] = AskUserQuestionArgs
    timeout_s: ClassVar[int] = 10  # only writes a DB row

    def announce(self, args: AskUserQuestionArgs) -> str:
        return "Waiting for your answer…"

    def run(self, args: AskUserQuestionArgs, ctx: ToolContext) -> ToolResult:
        # Local imports — avoids module-level Django coupling at import
        # time and keeps the tool unit-testable with a stub Message
        # manager.
        from donna.chat.models import Message

        ttl = (
            timedelta(minutes=args.expires_in_minutes)
            if args.expires_in_minutes
            else DEFAULT_TTL
        )
        msg = Message.objects.create(
            channel=ctx.channel,
            author_agent=ctx.agent_session,
            body=args.prompt,
            kind=Message.Kind.QUESTION,
            question_options=[o.model_dump() for o in args.options],
            expires_at=timezone.now() + ttl,
        )
        # Plan 13 §8.2 — surface the wait state to the channel chip.
        try:
            from donna.chat.services import broadcast_agent_status
            broadcast_agent_status(
                channel=ctx.channel,
                agent_session=ctx.agent_session,
                state="waiting_on_user",
                detail=args.prompt[:120],
            )
        except Exception:  # noqa: BLE001
            pass
        return ToolResult(payload={
            "question_id": str(msg.id),
            "status": "awaiting_user",
            "expires_at": msg.expires_at.isoformat(),
            "hint": (
                "The turn will pause here. When the user answers, "
                "chat.resume_turn fires and the answer_payload reads off "
                "this question row."
            ),
        })
