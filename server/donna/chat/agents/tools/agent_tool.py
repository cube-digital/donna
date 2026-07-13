"""Plan 13 §5.1 — AgentTool spawn primitive.

The parent agent calls ``agent(subagent_type=..., prompt=..., mode=...)``
to fan out a sub-task. The dispatcher executes the spawn:

- ``mode="sync"`` (default): the sub-task runs inline; the parent waits
  for the final synthesized text and reads it as the tool result.
- ``mode="async"``: the sub-task is enqueued as a Celery task; the parent
  receives an immediate acknowledgement (with a job id) and the result
  arrives later via a ``<task-notification>`` message in channel history.

Mailbox mode (long-lived addressable named subagent, §5.2) is deferred
to v2; the args model carries an ``name`` field for forward compat but
the dispatcher rejects spawns that try to use it.

Hooks fire on ``subagent_stop`` when a spawn terminates (§2.3 contract).
"""
from __future__ import annotations

import logging
from typing import ClassVar, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from donna.chat.agents.hooks import HookContext, fire as fire_hook
from donna.chat.agents.subagents import BUNDLED_SUBAGENT_DEFS, resolve
from donna.chat.agents.tools.base import DonnaTool, ToolContext, ToolResult

logger = logging.getLogger(__name__)


class AgentToolArgs(BaseModel):
    subagent_type: str = Field(
        description=(
            "Which subagent to spawn. One of: "
            + ", ".join(sorted(BUNDLED_SUBAGENT_DEFS))
        ),
    )
    prompt: str = Field(description="The task description for the subagent.")
    mode: Literal["sync", "async"] = Field(
        default="sync",
        description=(
            "sync = wait for the subagent's synthesized text and use it "
            "this round. async = fire-and-forget; result arrives later "
            "as a separate notification."
        ),
    )
    name: Optional[str] = Field(
        default=None,
        description=(
            "(v2-only) Pin this subagent under a name so follow-ups via "
            "send_message can address it. Rejected today — mailbox mode "
            "ships in a future plan."
        ),
    )


def run_subagent_sync(
    *,
    defn,
    prompt: str,
    parent_ctx: ToolContext,
    llm_factory=None,
) -> dict:
    """Run a subagent inline and return ``{text, rounds, subagent_id}``.

    The forked graph is intentionally simple in v1: a single LLM call
    with the def's system prompt + the parent's tool context (so cortex
    reads keep working). Iterative multi-round loops + abort cascade
    land in v2 alongside Plan 13.3.x runtime hygiene.
    """
    from donna.core.llm.factory import LLMFactory

    subagent_id = str(uuid4())
    factory = llm_factory or LLMFactory
    provider = factory.create(model=defn.default_model)
    try:
        resp = provider.get_answer(
            prompt=prompt,
            system_prompt=defn.system_prompt,
            temperature=0.3,
            max_tokens=1500,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("subagent_sync_failed", extra={
            "subagent_type": defn.name, "subagent_id": subagent_id,
        })
        return {"text": "", "rounds": 0, "subagent_id": subagent_id, "error": str(exc)}

    content = getattr(resp, "content", None) or getattr(resp, "text", None) or ""

    # Plan 13 §2.3 — fire subagent_stop hook for audit + post-stop work.
    hook_ctx = HookContext(
        event="subagent_stop",
        workspace=getattr(parent_ctx, "workspace", None),
        session_id=str(getattr(getattr(parent_ctx, "agent_session", None), "id", "")),
        channel_id=str(getattr(getattr(parent_ctx, "channel", None), "id", "")) or None,
        subagent_id=subagent_id,
        subagent_transcript=[{"role": "assistant", "content": content}],
    )
    fire_hook("subagent_stop", hook_ctx)
    return {"text": content, "rounds": 1, "subagent_id": subagent_id}


class AgentTool(DonnaTool):
    """Spawn a focused subagent for a sub-task."""

    name: ClassVar[str] = "agent"
    description: ClassVar[str] = (
        "Spawn a focused subagent for a sub-task. Use when the work "
        "needs a separate working context (long research, multi-step "
        "drafting) or when you want a fact verified by an independent "
        "skeptic. Returns the subagent's final text (sync mode) or an "
        "acknowledgement (async)."
    )
    args_model: ClassVar[type[BaseModel]] = AgentToolArgs
    # Sub-spawns can run long — cortex reads + Sonnet roundtrip.
    timeout_s: ClassVar[int] = 240
    taint_safe: ClassVar[bool] = True

    def announce(self, args: AgentToolArgs) -> str:
        return f"Spawning {args.subagent_type} subagent…"

    def run(self, args: AgentToolArgs, ctx: ToolContext) -> ToolResult:
        defn = resolve(args.subagent_type)
        if defn is None:
            return ToolResult.fail(
                f"Unknown subagent_type '{args.subagent_type}'. "
                f"Available: {', '.join(sorted(BUNDLED_SUBAGENT_DEFS))}."
            )
        if args.name:
            return ToolResult.fail(
                "Named (mailbox) subagents are not enabled in this build. "
                "Drop the ``name`` argument or call again without it."
            )

        if args.mode == "async":
            # v1 ships an immediate ack — the actual async runner is the
            # same Celery task that runs the parent turn, called with the
            # subagent's def. Wiring lives in chat/tasks.py.
            try:
                from donna.chat.tasks import run_subagent_async

                job_id = str(uuid4())
                run_subagent_async.delay(
                    subagent_type=defn.name,
                    prompt=args.prompt,
                    parent_session_id=str(ctx.agent_session.id),
                    parent_channel_id=str(ctx.channel.id),
                    job_id=job_id,
                )
                return ToolResult(payload={
                    "status": "async_launched",
                    "subagent_type": defn.name,
                    "job_id": job_id,
                })
            except Exception as exc:  # noqa: BLE001
                logger.warning("subagent_async_dispatch_failed")
                return ToolResult.fail(f"failed to enqueue async subagent: {exc}")

        # Sync mode — run inline + return the synthesized text.
        out = run_subagent_sync(defn=defn, prompt=args.prompt, parent_ctx=ctx)
        if out.get("error"):
            return ToolResult.fail(out["error"])
        return ToolResult(payload={
            "status": "completed",
            "subagent_type": defn.name,
            "subagent_id": out["subagent_id"],
            "text": out["text"],
        })
