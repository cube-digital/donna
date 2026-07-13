# Plan — Agent runtime maturity: drafting, memory, multi-agent, automation

> Source of architecture decisions: [`docs/important-docs/00n - claude-code-patterns-for-donna.md`](../../docs/important-docs/00n%20-%20claude-code-patterns-for-donna.md) (original pattern catalogue) + planning notes from the 2026-06-25 Cowork-framing review (see [`gleaming-wibbling-kurzweil.md`](https://example.invalid) — local planning doc; not in repo).
> Source of current Donna shape: 2026-06-21 verification pass + 2026-06-25 refresh on Cowork primitives (see "Current state" below).
> Out of scope: cortex Phase 6 (eval harness + maintenance workers) — separate plan, see [`docs/important-docs/00f - silver-completion-plan.md`](../../docs/important-docs/00f%20-%20silver-completion-plan.md).

---

## Context

### Why this work

Donna's product framing is **Claude-Cowork-style** (channel-resident teammates, ambient agents, human-in-loop approval, multi-app surface) — not Claude-Code-style dev tooling. A1 (Q&A runtime) and A2 (drafting layer) are shipped. The agent functions but feels generic: no per-channel agent specialization, no long-term memory across sessions, no multi-agent orchestration, no automation/policy layer, no compliance hooks.

This plan converts the patterns surfaced in `00n` (originally extracted from reading Claude Code source) into concrete Donna changes — but every adoption is motivated by Cowork goals, not Code mimicry. Memory loop is here because Cowork relationships compound; multi-agent is here because the Cowork pitch is "team of teammates"; automation app is here because Cowork agents are ambient, not synchronous.

The goal is **production-grade drafting + multi-agent orchestration + ambient automation** without re-architecting the chat layer. Every change is additive: new fields on existing models, new tools in the registry, new Celery tasks, plus one new app (`donna/automation/`). The current Q&A flow keeps working unchanged through every phase.

### Current state (verified 2026-06-21, refreshed 2026-06-25)

| Subsystem | File | What exists | What's missing | Lands in |
|---|---|---|---|---|
| `DonnaTool` ABC | [`chat/agents/tools/base.py:49`](../donna/chat/agents/tools/base.py) | name, description, args_model, timeout_s, taint_safe | is_concurrency_safe, should_defer, requires_user_interaction, structured permission result | 3.3 |
| Tool dispatcher | [`chat/agents/nodes/tool_dispatcher.py:208`](../donna/chat/agents/nodes/tool_dispatcher.py) | ThreadPoolExecutor(max_workers=1), sequential, taint check | concurrent partitioning, abort-cascade, hook dispatch | 2.3, 3.3 |
| Graph loop | [`chat/agents/graph.py:24`](../donna/chat/agents/graph.py) | MAX_ROUNDS=6, defensive fallback | output-cap recovery, stop_reason handling | 3.1 |
| State builder | [`chat/agents/state/builder.py:29`](../donna/chat/agents/state/builder.py) | message-count trigger (60), branch-aware buckets, Haiku digest | token-based trigger, structured compaction prompt | 3.2, 4.3 |
| `AgentSession` | [`chat/models.py:140`](../donna/chat/models.py) | memory + config JSONFields, **channel FK present** | no `mode` field, no SessionMemory model, no `is_channel_resident` flag | 2.1, 4.1, 5.2.2 |
| `Artifact` (A2; renamed from `Document` 2026-06-25) | [`chat/models.py:274`](../donna/chat/models.py) | status, version, target_doc_type, finalized_entity_id, partial unique | — (shipped) | — |
| Tool registry | [`chat/agents/tools/factory.py`](../donna/chat/agents/tools/factory.py) | GLOBAL_REGISTRY frozen, draft_enabled gate | no output-style registry, no hook registry, no MCP proxy | 1.1, 2.3, 5.5 |
| Celery runner | [`chat/tasks.py:68`](../donna/chat/tasks.py) | turn_lock, build_state→registry→graph→persist | no post-turn memory extraction hook, single-pool topology | 3.4, 4.1 |
| WS broadcast | [`chat/services.py:42`](../donna/chat/services.py) + [`runner.py:84`](../donna/chat/agents/runner.py) | channel_group, channel_typing_group, agent_run_group | sub-agent transcript fan-out, status events | 5.3.2, 8.2 |
| Mention parser | [`chat/mentions.py:34`](../donna/chat/mentions.py) | `@user` / `@donna` / `@channel` / `@everyone`, `Message.mention_flags` | no agent-dispatch routing for `@<agent_name>` | 5.2.2 |
| Notifications | [`notifications/models.py:40`](../donna/notifications/models.py) | `Notification` model, SSE via `NotificationService` | — (sufficient for v1; policy gate deferred) | — |
| Reactions | [`chat/models.py:365`](../donna/chat/models.py) | `MessageReaction` (emoji, user, unique on message+emoji+author) | no on-read polarity classifier, no aggregator-to-`AgentSession.config` | 7.3 |
| Celery beat / cron | [`donna/celery.py:23`](../donna/celery.py) | autodiscover enabled | no `CELERY_BEAT_SCHEDULE`, no `Schedule` model | 7.1 |
| Hooks / extension points | — | nothing | PreToolUse / PostToolUse / SubagentStop / SessionStart hooks | 2.3 |
| MCP integration | — | nothing | per-workspace MCP server registry + `MCPTool` proxy | 5.5 |
| Slash commands | — | nothing | parser + registry + dispatcher | 8.1 |
| Multi-recipient drafts | — | single Artifact instance per channel | drafter behavior emitting N Artifact rows w/ `metadata.audience` | 6.3 |

### Plan shape

Eight phases, sequenced by ROI per day. Each phase is independently shippable. Phase 1 lifts perceived quality immediately; later phases compound. Total ≈ 21d.

### v1 scope (locked 2026-06-26): S+A tier only — ~11.5d

Decision after value-ranking pass: ship the **S tier** (foundation) + **A tier** (high-value) sub-sections in v1. **B + C tier** sub-sections defer to v2 (re-ranked then). All cuts are reversible — no architectural lock-in.

**v1 sub-sections (15 of 30):**

| Tier | Phase.# | Sub-section | Effort |
|---|---|---|---|
| S | 1.3 | AskUserQuestion | 0.5d |
| S | 1.5 | HIL multi-step | 0.25d |
| S | 2.1 | Drafting / plan mode | 0.5d |
| S | 4.1 | SessionMemory per-turn | 1d |
| S | 4.2 | AutoDream consolidation | 1d |
| S | 5.2.2 | Channel-resident agents | 0.5d |
| A | 1.1 | Output styles | 0.5d |
| A | 1.2 | Haiku tool summaries | 0.5d |
| A | 2.3 | Hook registry | 1d |
| A | 4.4 | Relationship-sharded memory | 0.25d |
| A | 5.1 | AgentTool spawn (sync/async, no mailbox) | 1.5d |
| A | 5.4 | Adversarial verify | 0.5d |
| A | 6.1 | MagicDocs status sibling | 1d |
| A | 7.1 | Schedule worker | 1d |
| A | 8.2 | Presence/status UX | 1.5d |

**v2 deferred (B + C tier, plus already-deferred):** 1.4 TodoWrite, 3.1/3.2/3.3/3.4 runtime hygiene + worker split, 4.3 structured compaction, 5.1.2 FS subagent defs, 5.2 mailbox, 5.3 coordinator, 5.3.2 cross-agent visibility, 5.5 MCP proxy, 6.2 PromptSuggestion (already deferred), 6.3 multi-audience draft, 7.3 feedback aggregator, 8.3 channel-agent install UX, 8.4 schedule UX.

**Known v1 gaps (intentional):**
- Channel-resident agent install via API only (no admin panel — 8.3 deferred).
- Schedules editable via API only (no UI — 8.4 deferred).
- Single Celery pool (3.4 split deferred — works at low load; revisit when ambient traffic hurts).
- No multi-audience draft (re-prompt per audience — 6.3 deferred).
- No MCP plug-in tools (5.5 deferred).
- Mailbox-mode subagent spawn disabled (5.2 deferred; 5.1 ships sync/async only).
- No coordinator mode (5.3 deferred — multi-agent fan-out works but no orchestrated synthesis prompt).
- 👍/👎 not captured as labeled signal (7.3 deferred).
- No runtime robustness layer (output-cap recovery, token compaction, concurrency partition all deferred to v2).

Full 8-phase table below stays for reference; sub-sections without S/A tier marker = v2.

| Phase | Scope | Effort |
|---|---|---|
| 1 | Drafting UX polish: output styles, Haiku tool-use summaries, AskUserQuestion (+ multi-step HIL), TodoWrite | ~2.25d |
| 2 | Drafter modes + **hook registry** (skills layer dropped 2026-06-26) | ~1.5d |
| 3 | Robust runtime: output-cap recovery, token-based compaction, concurrency-safe tools, **Celery worker split (gevent I/O + prefork CPU)** | ~2d |
| 4 | Memory loop: SessionMemory + AutoDream + structured compaction prompt + **relationship sharding** | ~2.75d |
| 5 | Multi-agent: AgentTool spawn (+ FS-loaded defs), named-agent mailbox (+ channel-resident), coordinator mode (+ cross-agent visibility), **adversarial verify**, **MCP proxy** | ~5.25d |
| 6 | Long-tail polish: MagicDocs auto-updater, multi-audience drafter behavior (PromptSuggestion deferred-last) | ~2.5d |
| 7 | **NEW** — Automation app (`donna/automation/`): `Schedule` model + worker; reaction-derived feedback aggregator (NotificationPolicy dropped 2026-06-26) | ~1.5d |
| 8 | **NEW** — Cowork surface: presence/status UX, channel-agent install UX, schedule UX (slash commands + notification policy UI dropped 2026-06-26) | ~3.5d |

---

## Phase 1 — Drafting UX polish (~2d)

**Goal:** A1+A2 chat feels measurably more polished without new infrastructure. Four small wins.

### 1.1 Output styles (~0.5d)

External markdown files swap the drafter's tone overlay per channel.

**New dir:** `server/donna/chat/agents/styles/bundled/`

Bundled styles (one each):
- `concise.md` — bullet-points, ≤300 words
- `detailed.md` — full prose with examples + headings
- `technical.md` — API-docs style with code blocks
- `customer.md` — friendly tone, no jargon
- `legal.md` — formal, defined terms in CAPS

Each file:

```markdown
---
name: customer
description: Friendly tone for client-facing drafts; no jargon
keep-base-instructions: true
---

When producing drafts, use plain language a non-technical customer can
follow. Avoid acronyms unless defined. Lead with what matters to the
reader. Keep paragraphs short. Use second-person ("you") where natural.
```

**New file:** `server/donna/chat/agents/styles/__init__.py` — loader.

```python
"""Output styles — swappable system-prompt overlays for the drafter.

Bundled styles live under ``styles/bundled/``. Workspace-scoped
styles will live under ``cortex/<ws>/agent-styles/`` (Phase 7).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml


_BUNDLED_DIR = Path(__file__).parent / "bundled"


@dataclass(frozen=True)
class OutputStyle:
    name: str
    description: str
    body: str
    keep_base_instructions: bool = True


def load_bundled_styles() -> Mapping[str, OutputStyle]:
    styles: dict[str, OutputStyle] = {}
    for path in _BUNDLED_DIR.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        if text.startswith("---\n"):
            _, frontmatter, body = text.split("---\n", 2)
            meta = yaml.safe_load(frontmatter) or {}
        else:
            meta, body = {}, text
        name = meta.get("name") or path.stem
        styles[name] = OutputStyle(
            name=name,
            description=meta.get("description", ""),
            body=body.strip(),
            keep_base_instructions=bool(meta.get("keep-base-instructions", True)),
        )
    return styles
```

**Edit:** [`chat/agents/nodes/drafter.py`](../donna/chat/agents/nodes/drafter.py) — accept `output_style` arg, prepend body to working prompt:

```python
def revise(
    self,
    *,
    current: str,
    instruction: str,
    context: list[dict] | None = None,
    title: str = "",
    target_doc_type: str = "",
    output_style: OutputStyle | None = None,   # NEW
) -> DraftOutput:
    ...
    style_block = (
        f"# Style overlay\n{output_style.body}\n\n"
        if output_style else ""
    )
    user_prompt = (
        style_block
        + f"# Title\n{title or '(untitled)'}\n\n"
        ...
    )
```

**Edit:** `UpdateDraftSectionTool.run()` in [`draft_tools.py`](../donna/chat/agents/tools/draft_tools.py) reads `ctx.agent_session.config.get("output_style")`, looks up `OutputStyle`, passes to `self._drafter.revise(...)`.

**Verify:**
```bash
docker exec donna-server bash -lc "cd /opt/donna && uv run python -c \
  'from donna.chat.agents.styles import load_bundled_styles; print(list(load_bundled_styles().keys()))'"
# expect: ['concise', 'detailed', 'technical', 'customer', 'legal']
```

### 1.2 Haiku tool-use summaries (~0.5d)

After each tool batch, generate a 1-line summary via Haiku. Replaces the static `announce()` broadcasts in the chat-run group.

**New file:** `server/donna/chat/agents/nodes/tool_summary.py`

```python
"""Haiku-summarized tool-use labels.

Claude Code pattern (00n §6.5): after tool batches complete, a Haiku
call generates a git-commit-style label that replaces verbose
tool-call/tool-result pairs in the UI. Cheap (one Haiku call per
batch), high signal density.
"""
from __future__ import annotations

import logging

from donna.core.llm.factory import LLMFactory


logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """\
Write a short label (max 30 chars) summarizing tool activity. Use:
- past-tense verb
- most distinctive noun
- drop articles, connectors, location context

Examples:
- "Pulled 4 emails about Acme"
- "Searched cortex for renewals"
- "Read meeting transcript"
- "Drafted client update v2"

Return ONLY the label. No quotes. No periods. No extra prose.\
"""


def summarize_tool_batch(tools: list[dict]) -> str:
    """tools = [{"name": str, "input": dict, "output_preview": str}, ...]"""
    if not tools:
        return ""
    body_lines: list[str] = []
    for t in tools:
        inp = _truncate(repr(t.get("input", {})), 300)
        out = _truncate(t.get("output_preview", ""), 300)
        body_lines.append(f"Tool: {t['name']}\nInput: {inp}\nOutput: {out}\n")
    try:
        llm = LLMFactory.create(model="anthropic/claude-haiku-4-5-20251001")
        resp = llm.chat(
            messages=[{"role": "user", "content": "\n".join(body_lines) + "\n\nLabel:"}],
            system_prompt=_SYSTEM_PROMPT,
            temperature=0.2,
        )
        label = (resp.content or "").strip().strip('"').strip("'")
        return label[:60]  # hard cap
    except Exception:  # noqa: BLE001
        logger.exception("tool_summary_failed", extra={"tools": [t["name"] for t in tools]})
        return ""


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n] + "…"
```

**Edit:** [`tool_dispatcher.py`](../donna/chat/agents/nodes/tool_dispatcher.py) — after dispatching the batch, build a `tools` list of `{name, input, output_preview}`, call `summarize_tool_batch`, broadcast a single `agent.summary` event:

```python
# at end of dispatch loop
summary = summarize_tool_batch([
    {"name": call.function["name"],
     "input": call_args[call.id],
     "output_preview": str(call_results[call.id])[:300]}
    for call in batch
])
if summary:
    _broadcast_agent_summary(ctx.channel.id, summary, run_id=state.run_id)
```

**Verify:** drive a chat turn, watch worker logs:
```bash
docker compose logs -f worker | grep agent_summary
```

### 1.3 AskUserQuestion tool (~0.5d)

Interactive mid-turn prompting. Agent emits structured question → frontend renders chips → user reply → tool_result.

**New file:** `server/donna/chat/agents/tools/ask_user.py`

```python
"""AskUserQuestion — mid-turn structured prompting (00n §3.3).

Pauses the agent loop, surfaces 1-4 multiple-choice questions to the
user via WS event, awaits reply via tool_result protocol.

requires_user_interaction=True; dispatcher skips when
session.config.get('headless') is True (background agents, scheduled
jobs).
"""
from __future__ import annotations

import asyncio
from typing import ClassVar

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from pydantic import BaseModel, Field

from donna.chat.agents.tools.base import DonnaTool, ToolContext, ToolResult
from donna.chat.services import channel_group


class QuestionOption(BaseModel):
    label: str = Field(description="Display text for the option")
    description: str = Field(default="", description="Hover/clarification text")


class Question(BaseModel):
    question: str
    header: str = Field(description="Short chip label (≤12 chars)")
    options: list[QuestionOption] = Field(min_length=2, max_length=4)
    multi_select: bool = False


class AskUserQuestionArgs(BaseModel):
    questions: list[Question] = Field(min_length=1, max_length=4)


class AskUserQuestionTool(DonnaTool):
    name: ClassVar[str] = "ask_user_question"
    description: ClassVar[str] = (
        "Pause and ask the user a structured question with bounded options. "
        "Use ONLY when clarification is genuinely needed and would shortcut "
        "multiple back-and-forth turns. Never use for confirmations."
    )
    args_model: ClassVar[type[BaseModel]] = AskUserQuestionArgs
    taint_safe: ClassVar[bool] = True
    timeout_s: ClassVar[int] = 600  # 10 min for user to answer

    # NEW field — see §3.3 of plan
    requires_user_interaction: ClassVar[bool] = True

    def run(self, args: AskUserQuestionArgs, ctx: ToolContext) -> ToolResult:
        layer = get_channel_layer()
        run_id = getattr(ctx.agent_session, "current_run_id", None) or "n/a"
        future = asyncio.get_event_loop().create_future()

        # Frontend posts answers back via a dedicated DRF endpoint that
        # resolves the future keyed on run_id.
        # (Future resolution mechanism shipped in §1.3.2 below.)
        _register_pending_question(run_id, future)
        async_to_sync(layer.group_send)(
            channel_group(ctx.channel.id),
            {
                "type": "chat.agent.question",
                "data": {"run_id": run_id, "questions": [q.model_dump() for q in args.questions]},
            },
        )
        try:
            answers = async_to_sync(asyncio.wait_for)(future, timeout=self.timeout_s)
        except asyncio.TimeoutError:
            _clear_pending_question(run_id)
            return ToolResult.fail("User did not respond within 10 minutes.")
        return ToolResult(payload={"answers": answers})


# In-memory pending-question store keyed by run_id.
# For multi-worker setups: switch to Redis pub/sub (Phase 5 mailbox lays groundwork).
_PENDING: dict[str, asyncio.Future] = {}


def _register_pending_question(run_id: str, future) -> None:
    _PENDING[run_id] = future


def _clear_pending_question(run_id: str) -> None:
    _PENDING.pop(run_id, None)


def resolve_pending_question(run_id: str, answers: dict[str, str]) -> bool:
    """Called from the DRF answer endpoint."""
    future = _PENDING.pop(run_id, None)
    if future and not future.done():
        future.set_result(answers)
        return True
    return False
```

**Edit:** `DonnaTool` base to add the new field (also covers §1.4):

```python
# chat/agents/tools/base.py
class DonnaTool(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    args_model: ClassVar[type[BaseModel]]
    timeout_s: ClassVar[int] = 120
    taint_safe: ClassVar[bool] = True

    # NEW (Phase 1):
    requires_user_interaction: ClassVar[bool] = False
    is_concurrency_safe: ClassVar[bool] = True
    should_defer: ClassVar[bool] = False  # reserved for ToolSearch (Phase 7)
```

**Edit:** [`tool_dispatcher.py`](../donna/chat/agents/nodes/tool_dispatcher.py) — skip tool when `tool.requires_user_interaction and ctx.agent_session.config.get("headless")`.

**New DRF view:** `chat/api/v1/views.py` — `POST /api/v1/chat/runs/<run_id>/answer/` with body `{answers: {...}}` calls `resolve_pending_question(run_id, answers)`.

**Verify:** unit test stubs the channel layer + DRF endpoint, simulates user answer, asserts tool returns the answers.

### 1.4 TodoWrite tool (~0.5d)

Persistent agent todo list stored on `AgentSession.memory["todos"]`. Visible to user via WS event.

**New file:** `server/donna/chat/agents/tools/todo_tools.py`

```python
"""Agent todo list — persistent across rounds (00n §3.4).

The agent uses this to plan multi-step work and keep itself honest.
Items live in AgentSession.memory["todos"]; UI renders as a checklist
that updates live via chat.agent.todos event.

Three tools to keep the surface tight:
- todo_write    : replace the whole list (initial planning)
- todo_update   : mark single item complete / change subject
- todo_list     : read current state (cheap, idempotent)
"""
from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from donna.chat.agents.tools.base import DonnaTool, ToolContext, ToolResult


class TodoItem(BaseModel):
    id: str
    subject: str
    status: Literal["pending", "in_progress", "completed"] = "pending"


class TodoWriteArgs(BaseModel):
    todos: list[TodoItem] = Field(max_length=20)


class TodoWriteTool(DonnaTool):
    name: ClassVar[str] = "todo_write"
    description: ClassVar[str] = (
        "Replace the agent's todo list for this conversation. Use when "
        "starting multi-step work (3+ steps). Max 20 items. Subsequent "
        "single-item updates should use todo_update."
    )
    args_model: ClassVar[type[BaseModel]] = TodoWriteArgs
    is_concurrency_safe: ClassVar[bool] = False  # writes session.memory

    def run(self, args: TodoWriteArgs, ctx: ToolContext) -> ToolResult:
        session = ctx.agent_session
        memory = session.memory or {}
        memory["todos"] = [t.model_dump() for t in args.todos]
        session.memory = memory
        session.save(update_fields=["memory", "updated_at"])
        _broadcast_todos(ctx.channel.id, memory["todos"])
        return ToolResult(payload={"todos": memory["todos"]})


class TodoUpdateArgs(BaseModel):
    id: str
    status: Literal["pending", "in_progress", "completed"] | None = None
    subject: str | None = None


class TodoUpdateTool(DonnaTool):
    name: ClassVar[str] = "todo_update"
    description: ClassVar[str] = (
        "Update one todo item's status or subject. Mark items completed "
        "as soon as they're done — don't batch."
    )
    args_model: ClassVar[type[BaseModel]] = TodoUpdateArgs
    is_concurrency_safe: ClassVar[bool] = False

    def run(self, args: TodoUpdateArgs, ctx: ToolContext) -> ToolResult:
        session = ctx.agent_session
        memory = session.memory or {}
        todos = memory.get("todos", [])
        hit = next((t for t in todos if t["id"] == args.id), None)
        if hit is None:
            return ToolResult.fail(f"No todo with id={args.id}.")
        if args.status:
            hit["status"] = args.status
        if args.subject:
            hit["subject"] = args.subject
        session.memory = memory
        session.save(update_fields=["memory", "updated_at"])
        _broadcast_todos(ctx.channel.id, todos)
        return ToolResult(payload={"todo": hit})


class TodoListArgs(BaseModel):
    pass


class TodoListTool(DonnaTool):
    name: ClassVar[str] = "todo_list"
    description: ClassVar[str] = "Return the agent's current todo list."
    args_model: ClassVar[type[BaseModel]] = TodoListArgs

    def run(self, args: TodoListArgs, ctx: ToolContext) -> ToolResult:
        memory = ctx.agent_session.memory or {}
        return ToolResult(payload={"todos": memory.get("todos", [])})


def _broadcast_todos(channel_id, todos):
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer
    from donna.chat.services import channel_group
    layer = get_channel_layer()
    if layer:
        async_to_sync(layer.group_send)(
            channel_group(channel_id),
            {"type": "chat.agent.todos", "data": {"channel_id": str(channel_id), "todos": todos}},
        )
```

**Edit:** [`factory.py`](../donna/chat/agents/tools/factory.py) — register both new tools at boot, add to `QA_TOOL_NAMES`:

```python
QA_TOOL_NAMES = (
    "cortex_query", "read_entity", "get_context", "prepare_context",
    "ask_user_question", "todo_write", "todo_update", "todo_list",  # NEW
)
```

### 1.5 Human-in-loop multi-step state machine (~0.25d)

**Why this exists separately from 1.3:** Cowork agents routinely run flows where the human is a participant at multiple points — draft → human edits two lines → agent re-drafts → human approves → agent sends. Plan 13.1.3 ships `AskUserQuestion` as a single-turn prompt; this sub-section makes it work across worker boundaries and across multiple gates per turn.

**Resolves Plan 13 open Q2** by picking the durable mechanism up front.

**Model decision (2026-06-26 revision):** *no new model.* A question IS a message in the channel; the answer IS a user reply. Reuse the existing `Message` model with a kind discriminator. Cowork-native: the question + answer thread is visible in chat history without a side table.

**Edit:** `chat.models.Message`

```python
class Message(...):
    class Kind(models.TextChoices):
        CHAT     = "chat", "chat"
        QUESTION = "question", "question"          # agent-asked, awaiting user
        ANSWER   = "answer", "answer"              # user's reply to a question

    kind            = models.CharField(max_length=16, choices=Kind.choices, default=Kind.CHAT)
    question_options = models.JSONField(default=list, blank=True)  # [{label,value,description}]
    answer_payload   = models.JSONField(null=True, blank=True)     # written when ANSWER message lands
    answered_message = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="answers", limit_choices_to={"kind": "question"},
    )
    expires_at       = models.DateTimeField(null=True, blank=True)  # QUESTION only; cleanup cron

    class Meta:
        indexes = [
            *Message._meta.indexes,
            models.Index(
                fields=["channel", "kind", "expires_at"],
                condition=Q(kind="question", answer_payload__isnull=True),
                name="msg_open_question_idx",
            ),
        ]
```

**Suspend/resume:**

- **Suspend.** `AskUserQuestionTool` writes a `Message(kind=QUESTION, ...)` to the channel + raises `AwaitingUser(message_id)`. Runner catches, persists graph state to `AgentSession.memory["pending_graph_state"][message_id]`, returns cleanly. Multi-step naturally supported — each suspend writes a new question message; runner tracks open count via `Message.objects.filter(channel=ch, kind=QUESTION, answer_payload__isnull=True).count()`.
- **Answer landing.** Frontend `POST /api/v1/chat/messages/<question_id>/answer` writes a child `Message(kind=ANSWER, answered_message_id=<question_id>, answer_payload=...)` + sets `answer_payload` on the QUESTION row + fires `chat.resume_turn` (Phase 1.5 routed `agents` queue → `donna-cpu`).
- **Why Redis pub/sub still matters:** if the worker mid-flight already suspended is still alive, it can race the answer. `chat:question:<id>` channel wakes it; otherwise resume_turn picks up cold from the persisted graph state. Reuses the same broker as `turn_lock`.

**Edit:** `chat/agents/tools/ask_user_question.py` — `Message.objects.create(kind=QUESTION, ...)` + raise `AwaitingUser(msg.id)`.

**Edit:** `chat/agents/runner.py` — catch `AwaitingUser`, persist graph state under `AgentSession.memory["pending_graph_state"][str(msg_id)]`, return cleanly.

**Edit:** `chat/services.py:resume_from_answer(question_id)` — load session, pop the persisted graph state, replay from suspended node.

**New endpoint:** `POST /api/v1/chat/messages/<uuid>/answer` (workspace + auth scoped) — atomically write answer message + enqueue `chat.resume_turn`.

**Cleanup cron:** beat job `chat.expire_open_questions` (every 5 min) marks questions w/ `expires_at < now` as expired (clears their `pending_graph_state` slot, posts a system reply "Question timed out"). Routed `agents` queue.

**Verification:** test in `chat/tests/test_hil_multistep.py` — fire a turn that calls `ask_user_question` twice; assert two `Message(kind=QUESTION)` rows; POST answers in order; assert each ANSWER child links via `answered_message`; assert graph completes after the second answer.

---

## Phase 2 — Drafter modes + hook registry (~1.5d)

**Goal:** make drafts feel calibrated to the workspace's templates without shipping 20 hardcoded variants.

### 2.1 Drafting mode (~0.5d)

`AgentSession.mode` enum field, gates `build_registry()`.

**Migration:** new field on `AgentSession`:

```python
# chat/models.py
class AgentSession(TimestampsMixin):
    class Mode(models.TextChoices):
        CHAT = "chat", "Chat"
        DRAFTING = "drafting", "Drafting"
        PLANNING = "planning", "Planning"

    # ...
    mode = models.CharField(
        max_length=16, choices=Mode.choices, default=Mode.CHAT,
    )
```

**Edit:** [`factory.py:build_registry`](../donna/chat/agents/tools/factory.py) — replace the `draft_enabled` bool with mode-based gating:

```python
DRAFTING_TOOLS = QA_TOOL_NAMES + DRAFT_TOOL_NAMES
CHAT_TOOLS = QA_TOOL_NAMES
PLANNING_TOOLS = QA_TOOL_NAMES + ("todo_write", "todo_update", "todo_list")

def build_registry(*, channel, agent_session) -> ToolRegistry:
    mode = agent_session.mode
    if mode == AgentSession.Mode.DRAFTING:
        wanted = list(DRAFTING_TOOLS)
    elif mode == AgentSession.Mode.PLANNING:
        wanted = list(PLANNING_TOOLS)
    else:
        wanted = list(CHAT_TOOLS)
    return GLOBAL_REGISTRY.subset(wanted)
```

**Edit:** [`tasks.py:run_agent_turn`](../donna/chat/tasks.py) — drop the `draft_enabled` config flag, pass session:

```python
registry = build_registry(channel=channel, agent_session=session)
```

**Edit:** [`prompts.py:build_system_prompt`](../donna/chat/agents/prompts.py) — append mode-specific guidance:

```python
MODE_GUIDANCE = {
    "chat":     CHAT_MODE_GUIDANCE,        # default behaviour
    "drafting": DRAFTING_MODE_GUIDANCE,    # focus on iterating draft
    "planning": PLANNING_MODE_GUIDANCE,    # plan first, no execution
}

def build_system_prompt(ctx):
    parts = [IDENTITY, CITATION_RULES, TOOL_ROUTING_HINTS, ORG_TAXONOMY]
    parts.append(MODE_GUIDANCE.get(ctx.agent_session.mode, ""))
    # ...
```

`DRAFTING_MODE_GUIDANCE` etc are short prose blocks.

### 2.2 ~~Skills layer~~ — dropped 2026-06-26

> Original sub-section sized a markdown-skill loader + `load_skill` tool + 1%-budget system-prompt listing. **Dropped under Cowork-framing review**: at Donna's current scale the system prompt isn't bloated, so the "load expertise on demand" optimization has no payoff. Overlaps with (1.1 output styles for tone, 2.1 drafting mode for tool gating, 5.1.2 FS-loaded subagent defs for per-workspace customization, 2.3 hooks for policy injection). Defer until system-prompt budget hits real pain. The Code-shaped pattern doesn't earn its 1.5d.

> Knock-on effects already applied: 6.3 multi-audience reshaped as inline drafter behavior (no skill load); 8.1 slash commands map handlers directly to Python callables or Workflow scripts (no skill resolver). See those sub-sections.

### 2.3 Hook registry (~1d)

**Why:** Cowork workspaces want admin-controlled extension points without forking Donna code. Compliance, audit, PII redaction, policy enforcement, and learned-fact persistence all want to fire at well-defined moments in the agent loop. Phase 2 is already touching the dispatcher to mode-gate the registry — adding hook dispatch at the same touch points keeps the change cohesive.

**Four hook events ship in this sub-section:**

| Event | Fires | Use cases |
|---|---|---|
| `pre_tool_use` | Before each tool's `run()` | Audit log, PII redaction of args, deny-listing, dry-run preview |
| `post_tool_use` | After each tool's `run()` returns or raises | Audit log w/ result hash, side-effect mirroring, learning extraction |
| `session_start` | At graph entry per turn | Inject workspace policy reminders into system prompt; populate scoped memory |
| `subagent_stop` | When a spawned subagent terminates (Phase 5) | Persist learnings, dump transcript to audit, decrement budget counters |

**New file:** `server/donna/chat/agents/hooks/__init__.py`

```python
"""Hook registry — workspace-global extension points fired by the
agent loop. Hooks are pure-Python callables registered at startup
(via app config) or loaded from `chat_agent_hooks` rows for
workspace-scoped admin hooks (Phase 8 admin UI)."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Literal, Protocol
from donna.workspaces.models import Workspace

HookEvent = Literal["pre_tool_use", "post_tool_use", "session_start", "subagent_stop"]

class Hook(Protocol):
    name: str
    event: HookEvent
    def __call__(self, ctx: "HookContext") -> "HookResult": ...

@dataclass
class HookContext:
    event: HookEvent
    workspace: Workspace
    session_id: str
    channel_id: str | None
    tool_name: str | None = None         # pre/post_tool_use only
    tool_args: dict | None = None
    tool_result: dict | None = None      # post_tool_use only
    subagent_id: str | None = None       # subagent_stop only
    subagent_transcript: list | None = None

@dataclass
class HookResult:
    allow: bool = True                   # pre_tool_use can deny
    deny_reason: str | None = None
    mutated_args: dict | None = None     # pre_tool_use can rewrite args
    mutated_result: dict | None = None   # post_tool_use can rewrite result
    side_effects: list[str] = ()         # informational, surfaced in audit log

_REGISTRY: dict[HookEvent, list[Hook]] = {e: [] for e in HookEvent.__args__}

def register(hook: Hook) -> None:
    _REGISTRY[hook.event].append(hook)

def fire(event: HookEvent, ctx: HookContext) -> HookResult:
    """Fire all hooks for `event`, accumulate result. First deny wins."""
    final = HookResult()
    for h in _REGISTRY[event]:
        r = h(ctx)
        if not r.allow:
            return r
        if r.mutated_args is not None:
            ctx.tool_args = r.mutated_args
            final.mutated_args = r.mutated_args
        if r.mutated_result is not None:
            ctx.tool_result = r.mutated_result
            final.mutated_result = r.mutated_result
        final.side_effects = (*final.side_effects, *r.side_effects)
    return final
```

**New file:** `server/donna/chat/agents/hooks/bundled/audit.py`

```python
"""Built-in audit hook — logs every tool call to structlog with
session/channel/workspace + arg hash + result hash."""
from donna.core.logging import get_logger
from donna.chat.agents.hooks import register, HookContext, HookResult
import hashlib, json

log = get_logger(__name__)

def _hash(d: dict | None) -> str:
    if d is None:
        return ""
    return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()[:12]

def audit_pre(ctx: HookContext) -> HookResult:
    log.info("tool.start", tool=ctx.tool_name, args=_hash(ctx.tool_args),
             ws=ctx.workspace.id, session=ctx.session_id, channel=ctx.channel_id)
    return HookResult()

def audit_post(ctx: HookContext) -> HookResult:
    log.info("tool.end", tool=ctx.tool_name, result=_hash(ctx.tool_result),
             ws=ctx.workspace.id, session=ctx.session_id)
    return HookResult()

audit_pre.name = "audit_pre"; audit_pre.event = "pre_tool_use"
audit_post.name = "audit_post"; audit_post.event = "post_tool_use"
register(audit_pre); register(audit_post)
```

**Edit:** `chat/agents/nodes/tool_dispatcher.py` — call `fire("pre_tool_use", ctx)` before each `tool.run()`; deny → tool returns `{"error": "denied", "reason": r.deny_reason}`. Call `fire("post_tool_use", ctx)` after each `run()`. Both fires happen inside the existing exception-handling block.

**Edit:** `chat/agents/runner.py` — call `fire("session_start", ctx)` at graph entry; merge `result.mutated_args["system_addendum"]` into the system prompt (if any).

**Edit:** `chat/agents/apps.py` — `ready()` recursively imports `hooks/bundled/*.py` so built-in hooks register at startup (matches the connector discovery pattern in `donna/integrations/apps.py`).

**Scope decision:** workspace-global hooks ship in this sub-section. Per-channel hook filtering is parametric (read `ctx.channel_id` inside the hook). A `WorkspaceHook` model for admin-installed hooks ships in Phase 8 (admin UI); the registry already supports it via `register()`.

**Verification:** `chat/tests/test_hook_registry.py` — register a deny hook for `send_email`, run a turn that tries to send, assert the tool result is `{"error": "denied", ...}` and no email is dispatched.

---

## Phase 3 — Robust runtime (~2d)

**Goal:** stop hitting `agent_round_cap_exhausted` on output-cap failures; let tool batches run concurrently safely.

### 3.1 Output-cap recovery, 3-layer (~0.5d)

**Edit:** [`chat/agents/graph.py`](../donna/chat/agents/graph.py) — wrap the agent call with recovery logic.

```python
from donna.chat.agents.state.builder import AgentState

MAX_ROUNDS = 6
MAX_OUTPUT_TOKEN_RECOVERIES = 3


def run_graph(state, ctx, registry, *, agent=None, dispatcher=None,
              max_rounds=MAX_ROUNDS):
    state.output_token_recovery_count = 0
    state = _agent_with_recovery(agent, state, ctx, registry)

    while state.pending_tool_calls and state.rounds < max_rounds:
        state.rounds += 1
        state = dispatcher(state, ctx, registry)
        state = _agent_with_recovery(agent, state, ctx, registry)

    # ... existing fallback path unchanged
    return state


def _agent_with_recovery(agent, state, ctx, registry):
    state = agent(state, ctx, registry)
    while _hit_output_cap(state) and state.output_token_recovery_count < MAX_OUTPUT_TOKEN_RECOVERIES:
        state.output_token_recovery_count += 1
        if state.output_token_recovery_count == 1:
            # Layer 1: silent retry at higher cap
            state.max_output_tokens_override = 64_000
        else:
            # Layer 2: inject "resume" message
            state.messages.append({
                "role": "user",
                "content": (
                    "Output token limit hit. Resume directly — no recap, "
                    "no apology. Continue from where you stopped."
                ),
            })
        state = agent(state, ctx, registry)
    return state


def _hit_output_cap(state) -> bool:
    last = state.messages[-1] if state.messages else None
    if not last or last.get("role") != "assistant":
        return False
    return state.last_stop_reason == "max_tokens"
```

**Edit:** [`AgentState`](../donna/chat/agents/state/builder.py) — add fields `output_token_recovery_count: int = 0`, `last_stop_reason: str | None = None`, `max_output_tokens_override: int | None = None`.

**Edit:** [`conversation_agent.py`](../donna/chat/agents/nodes/conversation_agent.py) — pass `max_output_tokens=state.max_output_tokens_override` to `llm.chat`, capture `resp.stop_reason` → `state.last_stop_reason`.

### 3.2 Token-based compaction trigger (~0.5d)

**Edit:** [`state/builder.py`](../donna/chat/agents/state/builder.py) — replace the 30/60 message thresholds with token-based:

```python
COMPACTION_BUFFER_TOKENS = 13_000
KEEP_VERBATIM_RECENT_RATIO = 0.25  # keep recent 25% verbatim


def _model_context_window(model: str) -> int:
    # Pulled from settings; per-model dict.
    return settings.MODEL_CONTEXT_WINDOWS.get(model, 200_000)


def _estimate_tokens(messages: list[dict]) -> int:
    # Cheap heuristic: total chars / 4. Good enough for trigger logic.
    return sum(len(str(m.get("content", ""))) for m in messages) // 4


def build_state(channel, session) -> AgentState:
    model = (session.config or {}).get("model", DEFAULT_MODEL)
    ctx_window = _model_context_window(model)
    qs = (Message.objects
          .filter(channel=channel, parent__isnull=True)
          .select_related("author_user", "author_agent", "parent")
          .order_by("-created_at")[:200])
    rows = list(reversed(qs))
    messages = [_to_litellm(r) for r in rows]

    used = _estimate_tokens(messages)
    if used < ctx_window - COMPACTION_BUFFER_TOKENS:
        return AgentState(messages=messages, ...)

    # Compaction needed — keep verbatim recent, summarize older.
    cutoff = int(len(rows) * (1 - KEEP_VERBATIM_RECENT_RATIO))
    older, recent = rows[:cutoff], rows[cutoff:]
    summary_msg = _branch_summary_msg(older, channel, session)
    messages = [summary_msg] + [_to_litellm(r) for r in recent]
    return AgentState(messages=messages, ...)
```

**New setting:**

```python
# settings.py
MODEL_CONTEXT_WINDOWS = {
    "anthropic/claude-sonnet-4-5": 200_000,
    "anthropic/claude-opus-4-8": 200_000,
    "anthropic/claude-haiku-4-5-20251001": 200_000,
}
```

### 3.3 Concurrency-safe tool partitioning (~0.5d)

**Edit:** [`tool_dispatcher.py`](../donna/chat/agents/nodes/tool_dispatcher.py) — partition calls before dispatch:

```python
def _dispatch_batch(self, state, ctx, registry):
    safe_calls, unsafe_calls = [], []
    for call in state.pending_tool_calls:
        tool = registry.get(call.function["name"])
        if tool and tool.is_concurrency_safe:
            safe_calls.append(call)
        else:
            unsafe_calls.append(call)

    # Run safe calls in parallel
    with ThreadPoolExecutor(max_workers=min(8, len(safe_calls) or 1)) as pool:
        futures = {pool.submit(self._dispatch_one, c, registry, ctx, state): c
                   for c in safe_calls}
        for fut in as_completed(futures):
            state.messages.append(fut.result())

    # Run unsafe (mutating) calls serially
    for call in unsafe_calls:
        state.messages.append(self._dispatch_one(call, registry, ctx, state))

    state.pending_tool_calls = []
```

**Default per tool:**
- cortex read tools: `is_concurrency_safe = True` (default)
- draft tools: `is_concurrency_safe = False` (mutate Artifact)
- todo tools: `is_concurrency_safe = False` (mutate session.memory)
- ask_user_question: `is_concurrency_safe = False` (blocks the user)

### 3.4 Celery worker split: gevent I/O + prefork CPU (~0.5d)

**Why now:** Phase 4 (memory loop) adds Haiku-driven per-turn extraction + Sonnet AutoDream. Phase 7 (Schedule worker) fans out cron-driven agent kickoffs. Existing webhook + integration polls are already I/O-heavy. A single prefork pool starves CPU-bound LLM work behind blocked HTTP waits — and a single gevent pool can't run CPU work (cooperative scheduling means token-processing loops block the event loop). Split into two workers with explicit queue routing.

**Two-worker topology:**

| Worker | Pool | Concurrency | Queues | Examples |
|---|---|---|---|---|
| `donna-io` | `gevent` | 1000 | `webhooks`, `notifications`, `integrations`, `schedules` | Webhook delivery, SSE notification fanout, integration polls, schedule firing → message enqueue, OAuth refresh, MCP proxy calls |
| `donna-cpu` | `prefork` | `cpu_count` | `agents`, `memory`, `dreams`, `feedback` | `chat.run_turn`, `chat.update_memory` (4.1), `chat.autodream` (4.2), MagicDocs updaters (6.1), `feedback_aggregate` (7.3) |

**Routing:** centralized in a new module so every task knows where it ends up.

**New file:** `server/donna/celery_routes.py`

```python
"""Single source of truth for Celery task → queue routing.

Two queues per pool to keep `donna-io` (gevent monkey-patch) strictly
isolated from `donna-cpu` (prefork). Mixing causes psycopg2 + LLM SDK
crashes under gevent.
"""
from __future__ import annotations

TASK_ROUTES: dict[str, dict[str, str]] = {
    # I/O pool — gevent
    "chat.send_notification":       {"queue": "notifications"},
    "chat.deliver_webhook":         {"queue": "webhooks"},
    "integrations.poll_provider":   {"queue": "integrations"},
    "integrations.refresh_oauth":   {"queue": "integrations"},
    "automation.schedule_tick":     {"queue": "schedules"},
    "automation.fire_schedule":     {"queue": "schedules"},
    # CPU pool — prefork
    "chat.run_turn":                {"queue": "agents"},
    "chat.resume_turn":             {"queue": "agents"},   # 1.5 HIL resume
    "chat.update_memory":           {"queue": "memory"},   # 4.1
    "chat.autodream":               {"queue": "dreams"},   # 4.2
    "chat.update_draft_status_doc": {"queue": "agents"},   # 6.1
    "automation.feedback_aggregate":{"queue": "feedback"}, # 7.3
}

# Tasks default to `agents` if unrouted (safe default — CPU pool can
# handle stray I/O work; the reverse blows up under gevent monkey-patch).
DEFAULT_QUEUE = "agents"
```

**Edit:** `server/donna/celery.py` — import `TASK_ROUTES` and set `app.conf.task_routes`, `app.conf.task_default_queue = DEFAULT_QUEUE`. Add gevent monkey-patch *only* when started under the gevent pool, detected via `CELERY_WORKER_POOL=gevent` env var. Patch *before* any Django app load:

```python
# server/donna/celery.py — top of file, before django.setup()
import os
if os.environ.get("CELERY_WORKER_POOL") == "gevent":
    from gevent import monkey
    monkey.patch_all()
```

**Edit:** `server/docker-compose.yml` and (when Plan 12 ships) `server/deploy/self_host/docker-compose.yml` — replace the single `worker` service with two:

```yaml
worker-io:
  image: donna:dev
  command: ["worker"]
  environment:
    CELERY_WORKER_POOL: gevent
    CELERY_WORKER_CONCURRENCY: "1000"
    CELERY_WORKER_QUEUES: "webhooks,notifications,integrations,schedules"
  depends_on: [postgres, redis]

worker-cpu:
  image: donna:dev
  command: ["worker"]
  environment:
    CELERY_WORKER_POOL: prefork
    CELERY_WORKER_QUEUES: "agents,memory,dreams,feedback"
  depends_on: [postgres, redis]
```

**Edit:** `server/deploy/entrypoint.sh` — dispatch by role, read `CELERY_WORKER_POOL` + `CELERY_WORKER_QUEUES` env vars when role is `worker`.

**Edit:** `donna/core/health.py` — each worker writes `donna:worker:io:heartbeat` / `donna:worker:cpu:heartbeat` to Redis w/ 30s TTL; health endpoint reports both. (Phase 4 + 7 schedules depend on both pools being live.)

**Cross-link to Plan 12:** Plan 12 Phase 2 (compose split into dev vs `deploy/self_host/`) MUST land `worker-io` + `worker-cpu` from the start; do not ship a single-worker self-host compose. Add a note in `12-deployment-pipelines.md` Phase 2.

**Verification:**
- `pytest server/donna/chat/tests/test_celery_routing.py` — assert every registered task name resolves to its expected queue via `app.amqp.router.route()`.
- Load test: trigger 100 concurrent webhook deliveries while a 60s `chat.run_turn` is mid-flight. Assert all 100 complete on `donna-io` without queueing `run_turn`.
- Kill `donna-cpu` mid-turn → SSE fanout from `donna-io` keeps flowing; `run_turn` resumes from `turn_lock` on `donna-cpu` restart.

---

## Phase 4 — Memory loop (~2.75d)

**Goal:** durable per-session learnings + cross-session consolidation.

### 4.1 SessionMemory per-turn extraction (~1d)

Background Celery task fires after each completed turn (no pending tool_calls). Forked Haiku with a small turn budget writes a structured note to `AgentSession.memory["session_notes"]`.

**New file:** `server/donna/chat/agents/memory/session_memory.py`

```python
"""SessionMemory — background per-turn memory extraction (00n §5.3).

Forks a small Haiku agent that scans the last turn and updates
AgentSession.memory['session_notes'] with structured observations.
Trigger: after every committed assistant message; gated on token-count
threshold to avoid running on trivial turns.
"""
from __future__ import annotations

import logging
from typing import Any

from celery import shared_task
from pydantic import BaseModel, Field

from donna.chat.models import AgentSession
from donna.core.llm.factory import LLMFactory


logger = logging.getLogger(__name__)


INIT_TOKEN_THRESHOLD = 4_000
UPDATE_TOKEN_THRESHOLD = 2_000


class SessionNotes(BaseModel):
    user_goal: str = Field(description="What the user is currently trying to do (1-2 sentences)")
    entities_mentioned: list[str] = Field(default_factory=list)
    cortex_queries_run: list[str] = Field(default_factory=list)
    drafts_in_progress: list[str] = Field(default_factory=list)
    decisions_made: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    stated_preferences: list[str] = Field(default_factory=list)


@shared_task(name="chat.extract_session_memory")
def extract_session_memory(session_id: str, run_id: str) -> dict[str, Any]:
    try:
        session = AgentSession.objects.get(id=session_id)
    except AgentSession.DoesNotExist:
        return {"skipped": "session_missing"}

    memory = session.memory or {}
    prior = memory.get("session_notes") or {}
    new_tokens = _estimate_recent_tokens(session)
    cumulative = (memory.get("_session_memory_token_count") or 0)

    if cumulative + new_tokens < INIT_TOKEN_THRESHOLD:
        return {"skipped": "below_init_threshold"}
    if new_tokens < UPDATE_TOKEN_THRESHOLD:
        return {"skipped": "below_update_threshold"}

    try:
        notes = _extract(session, prior)
    except Exception:
        logger.exception("session_memory_extract_failed", extra={"session_id": session_id})
        return {"skipped": "extraction_failed"}

    memory["session_notes"] = notes.model_dump()
    memory["_session_memory_token_count"] = cumulative + new_tokens
    session.memory = memory
    session.save(update_fields=["memory", "updated_at"])
    return {"ok": True, "fields": list(notes.model_dump().keys())}


def _extract(session, prior: dict) -> SessionNotes:
    # ... fork Haiku with the recent transcript + prior notes, return SessionNotes
    ...


def _estimate_recent_tokens(session) -> int:
    # ... cheap estimate of messages since last extraction
    ...
```

**Edit:** [`chat/tasks.py:run_agent_turn`](../donna/chat/tasks.py) — after `persist_agent_message`, dispatch:

```python
extract_session_memory.delay(str(session.id), state.run_id)
```

### 4.2 AutoDream daily consolidation (~1d)

Beat task per workspace, merges last N sessions' notes into a person-scoped cortex entity.

**New beat task:** `server/donna/chat/agents/memory/auto_dream.py`

```python
"""AutoDream — daily memory consolidation (00n §5.4).

Per workspace (per user), merges last 5+ session notes into a durable
person-scoped CortexEntity (type='person', author=self).
Gates: 24h since last run, ≥5 new sessions, Redis lock for concurrency.
"""
from __future__ import annotations

import logging
from datetime import timedelta

import redis
from celery import shared_task
from django.utils import timezone

from donna.chat.models import AgentSession
from donna.workspaces.models import Workspace


logger = logging.getLogger(__name__)

MIN_HOURS_BETWEEN_RUNS = 24
MIN_SESSIONS_SINCE_LAST = 5
LOCK_KEY = "auto_dream:lock:{workspace_id}"
LOCK_TTL_SEC = 600  # 10 min


@shared_task(name="chat.auto_dream_workspace")
def auto_dream_workspace(workspace_id: str) -> dict:
    r = redis.from_url(...)
    lock_key = LOCK_KEY.format(workspace_id=workspace_id)
    if not r.set(lock_key, "1", nx=True, ex=LOCK_TTL_SEC):
        return {"skipped": "lock_held"}
    try:
        ws = Workspace.objects.get(id=workspace_id)
        last_run = _last_run_at(ws)
        if last_run and (timezone.now() - last_run) < timedelta(hours=MIN_HOURS_BETWEEN_RUNS):
            return {"skipped": "time_gate"}

        sessions = (AgentSession.objects
                    .filter(channel__workspace=ws, last_active_at__gt=last_run or timezone.now() - timedelta(days=90))
                    .order_by("-last_active_at")[:20])
        if len(sessions) < MIN_SESSIONS_SINCE_LAST:
            return {"skipped": "session_count_gate"}

        consolidated = _consolidate([s.memory.get("session_notes", {}) for s in sessions])
        _persist_to_cortex(ws, consolidated)
        _mark_run(ws)
        return {"ok": True, "sessions": len(sessions)}
    finally:
        r.delete(lock_key)


def _consolidate(notes_list: list[dict]) -> dict:
    """Call Sonnet with the 4-phase consolidation prompt (00n §5.4)."""
    ...


def _persist_to_cortex(workspace, consolidated):
    """Write to CortexEntity(type='person', author='self', source='donna://auto-dream')."""
    ...
```

**Beat schedule:** add to [`settings.py:CELERY_BEAT_SCHEDULE`](../donna/settings.py):

```python
"chat-auto-dream-fanout": {
    "task": "chat.fanout_auto_dream",
    "schedule": env.int("CHAT_AUTO_DREAM_FANOUT_SECONDS", 3_600),
},
```

`fanout_auto_dream` iterates active workspaces and dispatches `auto_dream_workspace.delay(id)`.

### 4.3 Structured compaction prompt (~0.5d)

**Edit:** [`state/builder.py:_branch_summary_msg`](../donna/chat/agents/state/builder.py) — replace the single-sentence summary with a 7-section structured prompt adapted to Donna's domain:

```python
COMPACTION_SYSTEM_PROMPT = """\
Summarize the conversation in EXACTLY these sections. Wrap your
working analysis in <analysis>...</analysis> (will be stripped before
delivery). Then produce the final summary in plain markdown.

Sections (all required, even if empty):

## User goal
The user's current intent in 1-2 sentences. Verbatim if possible.

## Entities mentioned
- Org/person/project names that came up

## Cortex queries run
- The agent's notable searches + what they returned (1 line each)

## Drafts in progress
- Document title + current version + status

## Decisions made
- Explicit user decisions ("yes do X", "skip Y")

## Open questions
- Things asked that weren't answered

## All user messages (verbatim, in order)
- One bullet per message, verbatim text

Do NOT paraphrase user messages — copy them. Do NOT skip any user
message. Other sections may be empty if the conversation didn't
include them.\
"""
```

**Edit:** the `_haiku_compact()` call to pass this as `system_prompt`.

### 4.4 Relationship-sharded memory (~0.25d)

**Why:** Cowork agents accumulate facts across long-running relationships — what's the history with Alice, what does this channel work on, what does the Acme project care about. A flat `SessionMemory` table (per-turn extraction without scope) is queryable only by session, which doesn't compose. Add a `scope` discriminator at write time so reads can filter by relationship.

**Edit:** `chat/models.py:SessionMemory` (created in 4.1) — add `scope` and `scope_ref` fields:

```python
SCOPE_CHOICES = [
    ("user", "user"),               # facts about the active user
    ("channel", "channel"),         # facts about the channel itself
    ("peer", "peer"),               # facts about another participant
    ("project", "project"),         # facts about a cortex project
    ("org", "org"),                 # facts about a client/vendor/peer org
    ("self", "self"),               # facts the agent learned about its own behavior
]

class SessionMemory(TimestampsMixin, models.Model):
    session = models.ForeignKey(AgentSession, on_delete=models.CASCADE, related_name="memory_entries")
    turn_id = models.CharField(max_length=40)
    scope = models.CharField(max_length=16, choices=SCOPE_CHOICES, default="user")
    scope_ref = models.CharField(max_length=80, blank=True, default="")  # user_id / channel_id / project_id / org_id
    body = models.TextField()
    confidence = models.FloatField(default=0.7)

    class Meta:
        db_table = "chat_session_memory"
        indexes = [
            models.Index(fields=["session", "scope"]),
            models.Index(fields=["scope", "scope_ref"]),  # cross-session lookups
        ]
```

**Edit:** `chat/agents/memory/extract.py` (4.1) — the extraction prompt asks Haiku to emit JSON entries each tagged `{scope, scope_ref, body, confidence}`. Default `scope="user"` if Haiku omits it.

**Edit:** `chat/agents/state/builder.py` — when loading memory into the system prompt, filter by relevant `(scope, scope_ref)` to the current channel/user/project. Don't dump all entries.

**Edit:** `chat/agents/memory/autodream.py` (4.2) — daily consolidation runs per `(scope, scope_ref)` group, not per session. So Acme-related notes from 5 different sessions get merged into one Acme-scoped CortexEntity.

**Verification:** test in `chat/tests/test_memory_sharding.py` — write 3 entries scoped `user`, `channel`, `project=Acme` in one session. Start a new session in a different channel that mentions Acme. Assert only the `user` + `project=Acme` entries get loaded into the system prompt, not the unrelated channel notes.

---

## Phase 5 — Multi-agent (~5.25d)

**Goal:** AgentTool spawn primitive (+ filesystem-loaded defs) + named-agent mailbox (+ channel-resident) + coordinator mode (+ cross-agent visibility) + adversarial verify helper + MCP proxy.

### 5.1 AgentTool spawn primitive (~1.5d)

**New file:** `server/donna/chat/agents/tools/agent_tool.py`

```python
"""AgentTool — spawn a specialist subagent (00n §4.1, §4.2).

Three execution modes mapped to Donna's stack:
- sync       : run inline, parent waits (fast specialists)
- background : Celery task, returns task_id, parent polls / receives notification
- mailbox    : long-lived named agent, addressable via send_message (5.2)

subagent_type ∈ {websearch, planner, drafter, summarizer} for v1.
Each has its own system prompt + tool subset + model.
"""
from __future__ import annotations

from typing import ClassVar, Literal

from celery.result import AsyncResult
from pydantic import BaseModel, Field

from donna.chat.agents.subagents import SUBAGENT_DEFS
from donna.chat.agents.tools.base import DonnaTool, ToolContext, ToolResult
from donna.chat.tasks import run_subagent_task


class AgentToolArgs(BaseModel):
    subagent_type: Literal["websearch", "planner", "drafter", "summarizer"]
    prompt: str = Field(description="Task for the child agent")
    name: str = Field(default="", description="Optional mailbox handle for follow-up messages")
    run_in_background: bool = False


class AgentTool(DonnaTool):
    name: ClassVar[str] = "agent"
    description: ClassVar[str] = (
        "Spawn a specialist agent to handle a focused task. "
        "Use for: research (websearch), planning multi-step work, "
        "drafting longer artifacts, or summarizing dense material."
    )
    args_model: ClassVar[type[BaseModel]] = AgentToolArgs
    is_concurrency_safe: ClassVar[bool] = True  # children run isolated
    timeout_s: ClassVar[int] = 600

    def run(self, args: AgentToolArgs, ctx: ToolContext) -> ToolResult:
        defn = SUBAGENT_DEFS[args.subagent_type]
        kwargs = {
            "subagent_type": args.subagent_type,
            "prompt": args.prompt,
            "channel_id": str(ctx.channel.id),
            "agent_session_id": str(ctx.agent_session.id),
            "parent_run_id": getattr(ctx.agent_session, "current_run_id", None),
            "name": args.name or "",
        }
        if args.run_in_background:
            async_result = run_subagent_task.delay(**kwargs)
            return ToolResult(payload={
                "status": "async_launched",
                "task_id": async_result.id,
                "agent_name": args.name,
            })
        # sync — block on Celery result
        result = run_subagent_task.apply(kwargs=kwargs).get(timeout=self.timeout_s)
        return ToolResult(payload=result)
```

**New file:** `server/donna/chat/agents/subagents/__init__.py`

```python
"""Subagent definitions — system prompt + tool subset + model per type."""
from dataclasses import dataclass


@dataclass(frozen=True)
class SubagentDef:
    name: str
    system_prompt: str
    allowed_tools: tuple[str, ...]
    default_model: str


SUBAGENT_DEFS = {
    "websearch": SubagentDef(
        name="websearch",
        system_prompt=WEBSEARCH_SYSTEM,
        allowed_tools=("web_search", "web_fetch"),       # to be added
        default_model="anthropic/claude-haiku-4-5-20251001",
    ),
    "planner": SubagentDef(
        name="planner",
        system_prompt=PLANNER_SYSTEM,
        allowed_tools=("cortex_query", "read_entity"),
        default_model="anthropic/claude-sonnet-4-5",
    ),
    "drafter": SubagentDef(
        name="drafter",
        system_prompt=DRAFTER_SUBAGENT_SYSTEM,
        allowed_tools=("cortex_query", "read_entity",
                       "update_draft_section", "finalize_draft"),
        default_model="anthropic/claude-sonnet-4-5",
    ),
    "summarizer": SubagentDef(
        name="summarizer",
        system_prompt=SUMMARIZER_SYSTEM,
        allowed_tools=(),
        default_model="anthropic/claude-haiku-4-5-20251001",
    ),
}
```

**New Celery task:** `server/donna/chat/tasks.py`

```python
@shared_task(name="chat.run_subagent")
def run_subagent_task(*, subagent_type, prompt, channel_id, agent_session_id,
                      parent_run_id, name) -> dict:
    defn = SUBAGENT_DEFS[subagent_type]
    # Build isolated ToolUseContext
    # Build subset registry from defn.allowed_tools
    # Run a forked graph loop with defn.system_prompt + prompt
    # Return synthesized result (final_text + structured payload if any)
    ...
```

**Add to registry:** `agent` tool registered in `register_qa_tools` (or new `register_meta_tools`).

### 5.1.2 Filesystem-loaded subagent definitions (~0.5d)

**Why:** Cowork sells "build your own teammate." Workspace admins should define `ContractBot` / `OnboardingBuddy` / `WeeklyDigest` agents without engineering. Phase 5.1 ships static `SUBAGENT_DEFS` as a Python dataclass — extend the loader to scan a bundled directory + a per-workspace S3/filesystem path.

**Structure:** subagent defs are markdown files with frontmatter (similar to the output-style files from 1.1, but extended w/ `allowed_tools` + `model` + `max_rounds`).

**New dir:** `server/donna/chat/agents/subagents/bundled/`

Bundled defs (one each):
- `websearch.md` — see `00n §4.1`
- `planner.md` — produces a TodoWrite list from a goal
- `drafter.md` — single-shot drafter w/ allowed-tools = draft tools
- `summarizer.md` — produces a concise digest of supplied context

Example frontmatter:

```markdown
---
name: websearch
description: Web search subagent for one-shot fact lookups.
model: claude-sonnet-4-6
allowed_tools: [cortex_query, read_entity, web_search]
max_rounds: 4
mode: chat
---
You are a focused research agent. Cite every fact with the URL it came from...
```

**New file:** `server/donna/chat/agents/subagents/__init__.py`

```python
"""Subagent definition loader.

Two sources:
  1. `bundled/*.md` — shipped with Donna, always available.
  2. `workspace.config["subagents_path"]` — per-workspace overrides;
     scanned at session start, cached in process for the session.

Hot reload is intentionally absent. Restart the worker (or wait for
the next session start) to pick up edits."""
from __future__ import annotations
import frontmatter
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class SubagentDef:
    name: str
    description: str
    model: str
    allowed_tools: tuple[str, ...]
    max_rounds: int
    mode: str
    system_prompt: str

_BUNDLED_DIR = Path(__file__).parent / "bundled"

def load_bundled() -> dict[str, SubagentDef]:
    defs: dict[str, SubagentDef] = {}
    for path in _BUNDLED_DIR.glob("*.md"):
        post = frontmatter.load(path)
        defs[post["name"]] = SubagentDef(
            name=post["name"],
            description=post["description"],
            model=post.get("model", "claude-sonnet-4-6"),
            allowed_tools=tuple(post["allowed_tools"]),
            max_rounds=int(post.get("max_rounds", 6)),
            mode=post.get("mode", "chat"),
            system_prompt=post.content,
        )
    return defs

BUNDLED_SUBAGENT_DEFS: dict[str, SubagentDef] = load_bundled()
```

**Edit:** `chat/agents/tools/agent_tool.py` (5.1) — replace the hardcoded dict with `_resolve_subagent(name, workspace)`:

```python
def _resolve_subagent(name: str, workspace) -> SubagentDef | None:
    if hit := BUNDLED_SUBAGENT_DEFS.get(name):
        return hit
    ws_path = (workspace.config or {}).get("subagents_path")
    if ws_path:
        candidate = Path(ws_path) / f"{name}.md"
        if candidate.exists():
            post = frontmatter.load(candidate)
            return SubagentDef(...)
    return None
```

**Verification:** drop a custom `subagents/contract_bot.md` into a workspace's directory; spawn it via `agent(name="contract_bot", ...)`; assert it runs with the declared allowed_tools subset.

### 5.2 Named agents + mailbox (~1d)

Redis stream per `agent_name`. SendMessageTool writes to it; subagent worker drains it.

**New file:** `server/donna/chat/agents/tools/send_message_tool.py`

```python
"""SendMessageTool — deliver a follow-up to a named subagent (00n §4.1).

Named agents (spawned with AgentTool(name="researcher")) sit in a
mailbox awaiting work. SendMessage delivers a new instruction.
Useful for long-lived research/triage agents in one conversation.
"""
from typing import ClassVar
from pydantic import BaseModel, Field
from redis import Redis

from donna.chat.agents.tools.base import DonnaTool, ToolContext, ToolResult


class SendMessageArgs(BaseModel):
    to: str = Field(description="Subagent name (the 'name' arg used when spawning).")
    message: str


class SendMessageTool(DonnaTool):
    name: ClassVar[str] = "send_message"
    description: ClassVar[str] = (
        "Send a follow-up message to a named subagent you spawned earlier. "
        "Use to continue work without re-spawning."
    )
    args_model: ClassVar[type[BaseModel]] = SendMessageArgs

    def run(self, args: SendMessageArgs, ctx: ToolContext) -> ToolResult:
        r = Redis.from_url(...)
        stream_key = f"agent_mailbox:{ctx.agent_session.id}:{args.to}"
        r.xadd(stream_key, {"from": "parent", "message": args.message})
        return ToolResult(payload={"delivered": True, "to": args.to})
```

Subagent worker (per long-lived agent name) blocks on `XREAD` until a message arrives.

### 5.2.2 Channel-resident named agents (~0.5d)

**Why:** Plan 5.2 makes named agents live for one parent session. Cowork wants them to live in a *channel* — `ContractBot` installed in `#legal` answers `@ContractBot` queries forever, accumulating channel-scoped memory (4.4) across sessions. The mailbox primitive already works; just key it on `(channel_id, name)` instead of `(parent_session_id, name)` for resident agents.

**Schema change:** add a flag to `AgentSession` to mark resident agents:

```python
class AgentSession(...):
    is_channel_resident = models.BooleanField(default=False)
    resident_handle = models.SlugField(max_length=40, blank=True, default="")  # e.g. "contract_bot"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["channel", "resident_handle"],
                condition=Q(is_channel_resident=True),
                name="uniq_resident_agent_per_channel",
            ),
        ]
```

**Mention dispatch:** extend `chat/mentions.py:parse()` — when `@<handle>` matches a `resident_handle` in the channel, dispatch the message to that `AgentSession` instead of (or in addition to) the channel's default agent. This is the only place mention routing changes.

**Edit:** `chat/agents/tools/send_message_tool.py` (5.2) — when `to` matches a `resident_handle` in the current channel, route via channel mailbox key `agent_mailbox:channel:{channel_id}:{handle}` instead of session-scoped key. Resident agents read from both keys.

**Install/uninstall:** Phase 8.3 ships the UX. Backend exposes `POST /api/v1/chat/channels/<id>/agents/install` (creates a resident `AgentSession`), `DELETE .../uninstall/<handle>`.

**Memory scope:** resident agents default new `SessionMemory` writes to `scope="channel", scope_ref=channel_id` (overrides the user-default from 4.4). Encodes the "channel teammate accumulates channel context" intuition.

**Verification:** install `ContractBot` in `#legal`; from another user, post `@ContractBot what's our standard NDA term?`; assert dispatch to the resident agent, response posted under that agent's identity.

### 5.3 Coordinator mode (~0.5d)

**Edit:** `prompts.py` — add COORDINATOR system prompt template. Activated when `session.config.get("coordinator_mode")` is True. Background subagents emit `<task-notification>` XML blocks (via Celery post-success hook) into the parent's message store; parent re-reads and synthesizes.

### 5.3.2 Cross-agent visibility (~0.25d)

**Why:** Cowork users need to see what the team of agents is doing in their channel, not just the coordinator's summary. Audit trail across agents matters for compliance.

**Edit:** subagent runner (the forked graph in 5.1) — after each subagent message, broadcast to the parent channel's WS group with a `subagent_transcript` event:

```python
# inside the forked graph loop, after each LLM message
broadcast_to_channel(parent_channel_id, {
    "type": "chat.subagent.message",
    "payload": {
        "parent_session_id": str(parent_session.id),
        "subagent_type": defn.name,
        "subagent_name": opts.name or defn.name,
        "message_text": msg.text,
        "round": round_idx,
    },
})
```

**Edit:** frontend `web/src/lib/ws.ts` — handle `chat.subagent.message` by rendering as a collapsible thread under the spawning parent message (UX shipped in Phase 8.2 alongside presence/status).

**SubagentStop hook tie-in:** when a subagent terminates, fire `subagent_stop` hook (2.3) with the full transcript so audit logs + learning extraction can consume it.

### 5.4 Adversarial verify helper (~0.5d)

**Why:** Cowork hallucination cost is *social* — "you said Alice agreed to X" → angry Alice. Before the agent commits a factual claim about a person/project to a message it's about to send, fan out N skeptics and majority-vote.

**New subagent def:** `chat/agents/subagents/bundled/verifier.md`

```markdown
---
name: verifier
description: Skeptic — try to refute the supplied claim.
model: claude-haiku-4-5-20251001
allowed_tools: [cortex_query, read_entity]
max_rounds: 3
mode: chat
---
You are a SKEPTIC. The user supplies a claim. Your job is to try to
DISPROVE it using cortex evidence. Default to refuted=true if you
cannot find direct evidence supporting the claim. Return JSON:
`{"refuted": bool, "reason": "..."}`.
```

**New helper:** `chat/agents/verify.py`

```python
"""verify_finding — adversarial majority-vote refutation pass.

Reusable for any pattern where the agent makes a factual claim it
wants to ground before acting. Fans out N skeptics in parallel,
counts non-refuted votes, returns a (verdict, evidence) tuple.

Caller decides what to do on `verdict == "refuted"` — usually
`AskUserQuestion` ("I tried to verify X but couldn't — proceed?").
"""
from concurrent.futures import ThreadPoolExecutor
from donna.chat.agents.tools.agent_tool import spawn_subagent

def verify_finding(claim: str, ctx, n: int = 3) -> tuple[str, list[dict]]:
    def _one(_):
        return spawn_subagent("verifier", prompt=claim, ctx=ctx, structured=True)
    with ThreadPoolExecutor(max_workers=n) as ex:
        votes = list(ex.map(_one, range(n)))
    refuted = sum(1 for v in votes if v.get("refuted"))
    verdict = "refuted" if refuted >= (n // 2 + 1) else "stands"
    return verdict, votes
```

**Edit:** drafting + send-message tool implementations (drafter / send_email / send_slack_message) — when output contains a claim of the form `<entity> <verb> <fact>` (heuristic via Haiku tagger or just allow LLM to call `verify_finding` explicitly as a tool), wrap in a verify step before commit.

**Cost discipline:** Haiku verifiers run in parallel, ~3s end-to-end per round. Per-tool budget: ≤1 verify pass per outbound message.

**Verification:** `chat/tests/test_verify_helper.py` — seed cortex with a contradicting fact; assert `verify_finding("Alice agreed to Q3")` returns `"refuted"` with the contradictory evidence.

### 5.5 MCP tool proxy (~0.5d)

**Why:** Cowork workspaces have weird internal systems (custom CRM, internal Jira) that Donna will never have a hardcoded connector for. Model Context Protocol (MCP) is the open standard for runtime-pluggable tool servers. Add a single `MCPTool` proxy that delegates to a per-workspace MCP server URL — customer hosts their own tool server, Donna agent uses it without a release.

**Workspace config:** new field on `Workspace.config` (existing JSON):

```json
{
  "mcp_servers": [
    {"name": "internal_crm", "url": "https://crm.example.com/mcp", "auth": "bearer:<token>"}
  ]
}
```

**New file:** `chat/agents/tools/mcp_tool.py`

```python
"""MCPTool — proxy to a per-workspace MCP server.

Loaded once at session start (after Workspace fetch), one Tool
instance per configured server. Tool names exposed are
`mcp:<server_name>:<tool_name>` to avoid collisions with native
tools.
"""
import httpx
from typing import ClassVar
from pydantic import BaseModel
from donna.chat.agents.tools.base import DonnaTool, ToolContext, ToolResult

class MCPArgs(BaseModel):
    # Schema inherited from the remote server's tool registration
    pass

class MCPTool(DonnaTool):
    def __init__(self, server_name: str, tool_name: str, schema: dict, server_url: str, auth: str):
        self.name = f"mcp:{server_name}:{tool_name}"
        self.server_url = server_url
        self.auth = auth
        # Dynamically build Pydantic model from schema
        self.args_model = _build_model_from_schema(schema)

    def run(self, args, ctx: ToolContext) -> ToolResult:
        r = httpx.post(
            f"{self.server_url}/tools/{self.name.split(':')[-1]}",
            json={"args": args.model_dump()},
            headers={"Authorization": self.auth},
            timeout=30,
        )
        r.raise_for_status()
        return ToolResult(payload=r.json())
```

**Edit:** `chat/agents/tools/factory.py:build_registry()` — after building the static registry, fetch the workspace's MCP servers, query each for its tool schema via `GET /tools`, instantiate `MCPTool` per remote tool, register w/ namespaced name. Cache schemas in Redis with 5-min TTL.

**Routing:** MCP calls are I/O-bound HTTP → routed via Phase 3.4 to `donna-io` gevent pool. (Concurrency-safe since each call is independent.)

**Per-workspace admin UI:** add/edit MCP servers — ships in Phase 8 admin panel.

**Verification:** stand up a tiny FastAPI MCP-shaped server that exposes `tools/echo`; configure workspace; assert `mcp:test_server:echo` appears in the agent registry and round-trips a call.

---

## Phase 6 — Long-tail polish (~2.5d)

### 6.1 MagicDocs — `DRAFT_STATUS.md` per active draft (~1d)

Background Sonnet maintains a sibling artifact next to each `Document(status=drafting)`. Updates after every `update_draft_section` call.

**New file:** `server/donna/chat/agents/magicdocs/draft_status_updater.py`

```python
"""DraftStatus MagicDocs updater — keeps a sibling status artifact
current as the draft body evolves (00n §6.4).

Triggered via Celery from UpdateDraftSectionTool's post-run hook.
Sonnet reads draft body + last instruction, updates DraftStatus
in-place (preserve header, no append-only history).
"""
from celery import shared_task

from donna.chat.models import Document


@shared_task(name="chat.update_draft_status_doc")
def update_draft_status_doc(document_id: str) -> dict:
    doc = Document.objects.get(id=document_id)
    # Look up or create the sibling status row (stored as DocumentStatus?
    # Or in Document.metadata? — decide during impl)
    # Sonnet call: produce updated status (header preserved, in-place rewrite)
    # Persist
    ...
```

**Edit:** `draft_tools.py:UpdateDraftSectionTool.run` — after the version bump, dispatch `update_draft_status_doc.delay(str(draft.id))`.

### 6.2 PromptSuggestion (~1d, deferred — ship last in Phase 6)

> Cowork reweighting (2026-06-25): solo-developer pattern. Cowork users multitask across channels and don't dwell on a single composer waiting for ghost text. Kept in the plan but moved to bottom of Phase 6 priority — ship 6.1 + 6.3 first, then 6.2 if time remains in the phase.

Haiku-predicted next prompt as ghost text after 2+ assistant turns. Suppressed in plan-pending / ambiguous / non-interactive sessions.

**New file:** `server/donna/chat/agents/prompt_suggestion.py`

```python
"""Predict the user's next likely prompt (00n §6.6).

Background Haiku call after each completed turn. Returns a single
short prompt suggestion the frontend renders as ghost text.

Suppressed when:
- session.mode == 'planning' (focus on the plan)
- last assistant message ended in an error
- session.config.get('prompt_suggestions') == False
"""
@shared_task(name="chat.suggest_next_prompt")
def suggest_next_prompt(channel_id: str, session_id: str) -> dict:
    # Gate checks
    # Haiku call with last 4 turns + instruction
    # Broadcast suggestion via WS event 'chat.agent.suggestion'
    ...
```

### 6.3 Multi-audience draft (~0.5d)

**Why:** Cowork users often need the same content rewritten for multiple audiences in one go — Slack message for the team, polished paragraph for the customer, one-pager for the CEO. Today the user re-prompts the agent N times.

**Approach (revised 2026-06-26):** inline drafter behavior, not a skill. Drafting mode (2.1) already gates the drafter tools; teach the drafter prompt directly to detect multi-audience requests and emit N `update_draft_section` calls per turn — one per audience — each tagging the artifact's `metadata.audience` field.

**Edit:** `chat/agents/prompts.py:DRAFTING_MODE_GUIDANCE` — append a "multi-audience" section:

```text
## Multi-audience requests

When the user asks for the same content across multiple audiences
(team / customer / executive / legal / etc.), emit ONE
`update_draft_section` tool call per audience in the same tool round.
Set each artifact's `metadata.audience` to the audience slug. Tones:

- team       → terse Slack-style, bullets, no formal salutation
- customer   → friendly + polite, no internal jargon
- executive  → 3-sentence one-pager, lead with the ask
- legal      → precise, includes terms + counterparties verbatim

If the audience list is ambiguous, call `ask_user_question` first
to disambiguate before producing any drafts.
```

**Edit:** `chat/models.py:Artifact` — add `metadata` JSONField (if not already present from the rename migration) to carry `{"audience": "..."}`.

**Edit:** `chat/agents/tools/draft_tools.py:UpdateDraftSectionTool.args_model` — accept optional `audience` field; write into `Artifact.metadata`.

**Edit:** drafter UX — frontend `web/src/components/Channel/ArtifactsRail.tsx` groups sibling artifacts by `metadata.audience`, with a single accept/edit/discard per audience.

**Verification:** `chat/tests/test_multi_audience.py` — fire `draft a launch update for the team, customer, and CEO`; assert 3 Artifact rows created, each w/ distinct `metadata.audience`, distinct body.

---

## Phase 7 — Automation app (`donna/automation/`) (~1.5d)

**Goal:** a reusable home for cron-driven agent behavior + feedback aggregation. Follows the mandatory Donna app layout (`server/plans/03-conventions-and-api.md`). **One** new model (`Schedule`); feedback derives from existing `MessageReaction` via on-read classifier.

**New app:** `server/donna/automation/`

```
automation/
├── apps.py
├── models.py              # Schedule
├── services.py            # AutomationService(BaseService)
├── api/v1/{views,serializers,filters}.py
├── tasks.py               # schedule_tick, fire_schedule, feedback_aggregate
├── feedback.py            # polarity() classifier — no model
├── urls.py
└── tests/
```

Register the app in `INSTALLED_APPS` (`server/donna/settings.py`) and include `automation.urls` in `donna/urls.py`.

### 7.1 `Schedule` model + worker (~1d)

**Why:** Cowork agents should fire themselves on cron / inbox event / calendar change. Channel-resident agents (5.2.2) install schedules to publish weekly digests, run morning triage, watch for due reminders.

**Model:**

```python
class Schedule(TimestampsMixin, UserAuditMixin, models.Model):
    workspace = models.ForeignKey("workspaces.Workspace", on_delete=models.CASCADE, related_name="schedules")
    agent_session = models.ForeignKey("chat.AgentSession", on_delete=models.CASCADE, related_name="schedules")
    name = models.CharField(max_length=120)
    cron = models.CharField(max_length=80)              # standard 5-field cron
    timezone = models.CharField(max_length=64, default="UTC")
    payload = models.JSONField(default=dict)            # synthetic message body delivered to the agent
    enabled = models.BooleanField(default=True)
    last_fired_at = models.DateTimeField(null=True, blank=True)
    next_fires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "automation_schedule"
        indexes = [models.Index(fields=["enabled", "next_fires_at"])]
```

**Tasks:**

```python
@shared_task(name="automation.schedule_tick")  # routed to 'schedules' queue → donna-io
def schedule_tick():
    """Beat-driven (every 30s). Enqueues due Schedule rows."""
    now = timezone.now()
    due = Schedule.objects.filter(enabled=True, next_fires_at__lte=now)
    for s in due.only("id")[:100]:
        fire_schedule.delay(str(s.id))

@shared_task(name="automation.fire_schedule")  # 'schedules' queue
def fire_schedule(schedule_id: str):
    s = Schedule.objects.get(id=schedule_id)
    # Synthetic chat message into the bound session's channel.
    # Reuses chat.services.send_message + chat.tasks.run_turn.
    chat_send_synthetic(s.agent_session, s.payload)
    s.last_fired_at = timezone.now()
    s.next_fires_at = _next_cron(s.cron, s.timezone, s.last_fired_at)
    s.save(update_fields=["last_fired_at", "next_fires_at"])
```

**Celery beat entry:** `donna/celery.py` adds `app.conf.beat_schedule["schedule-tick"] = {"task": "automation.schedule_tick", "schedule": 30.0}`.

**API surface (v1):** `GET/POST /api/v1/automation/schedules/`, `PATCH /api/v1/automation/schedules/<id>/`, `DELETE .../`. Filtered by `agent_session` + `workspace` (via header).

### 7.2 ~~NotificationPolicy~~ — dropped 2026-06-26

> Quiet hours + escalation policy isn't load-bearing for the rest of the plan. `NotificationService` keeps firing immediately as it does today; no policy gate, no `NotificationPolicy` model, no admin UI (8.5 dropped as well). If policy lands later, it slots into `automation/` w/o re-architecting upstream callers.

### 7.3 Reaction-derived feedback signals + aggregator (~0.5d)

**Why:** every 👍 / 👎 reaction on an agent message is a labeled training signal. Capture them.

**Model decision (2026-06-26 revision):** *no new model.* `MessageReaction` already records `(message, user, emoji)`. The "signal" is a function of `emoji`, not data — classify on read. Saves a model + a signal hook + write contention on every reaction.

**Classifier:** `automation/feedback.py`

```python
"""Reaction → feedback polarity. Single source of truth.

Used both at aggregation time (this module) and at read time (any
caller that wants per-message polarity)."""
POSITIVE_EMOJI = frozenset({"👍", "✅", "❤️", "🎉", "💯", "+1", "thumbsup"})
NEGATIVE_EMOJI = frozenset({"👎", "❌", "😡", "💩", "-1", "thumbsdown"})

def polarity(emoji: str) -> str | None:
    """Returns 'positive' / 'negative' / None (ignored)."""
    if emoji in POSITIVE_EMOJI:
        return "positive"
    if emoji in NEGATIVE_EMOJI:
        return "negative"
    return None
```

**Aggregator:** `automation.feedback_aggregate` (routed `feedback` → `donna-cpu`, hourly via beat).

```python
@shared_task(name="automation.feedback_aggregate")
def feedback_aggregate():
    """Recompute rolling 7-day per-agent win rate from MessageReaction
    JOIN Message. Writes denormalized stats to AgentSession.config."""
    cutoff = timezone.now() - timedelta(days=7)
    # SQL aggregate: count positives vs negatives per agent_session,
    # filtered to reactions on agent-authored messages within window.
    qs = (
        MessageReaction.objects
        .filter(created_at__gte=cutoff,
                message__author_agent_id__isnull=False,
                emoji__in=POSITIVE_EMOJI | NEGATIVE_EMOJI)
        .values("message__author_agent_id", "emoji")
        .annotate(n=Count("id"))
    )
    by_agent = defaultdict(lambda: {"positive": 0, "negative": 0})
    for row in qs:
        p = polarity(row["emoji"])
        if p:
            by_agent[row["message__author_agent_id"]][p] += row["n"]
    for agent_id, counts in by_agent.items():
        total = counts["positive"] + counts["negative"]
        win_rate = counts["positive"] / total if total else None
        AgentSession.objects.filter(id=agent_id).update(
            config=F("config") | Value({"feedback_stats": {"win_rate_7d": win_rate, **counts}}, JSONField())
        )
```

(The `F("config") | Value(...)` syntax sketches Postgres JSONB `||` concat; implementation uses `JSONField` update via SQL `jsonb_set` to avoid clobbering other config keys.)

**Stats denormalization:** rolling stats live on `AgentSession.config["feedback_stats"]` — small dict, read on every message render to show "85% positive over 7d" chip. No new table.

**Cortex linkage:** *isolated for v1.* No projection to `CortexEntity`. If a consumer needs labeled examples later, write a dataset exporter that reads MessageReaction directly. (Open question #3 resolved by dropping the side table.)

**Verification:**
- `automation/tests/test_polarity.py` — table-driven test of `polarity()` mapping (positive / negative / None).
- `automation/tests/test_aggregator.py` — seed 10 agent-authored messages, react 8 👍 + 2 👎 from different users; run aggregator; assert `AgentSession.config["feedback_stats"]["win_rate_7d"] == 0.8` w/ `positive=8, negative=2`.
- `automation/tests/test_aggregator_excludes_user_messages.py` — react 👍 on a user-authored message; assert aggregator does NOT count it.

---

## Phase 8 — Cowork surface (~3.5d)

**Goal:** Surface the Phase 5–7 backend in the product. Mostly frontend, w/ a thin backend slice per sub-section. Three sub-sections: presence/status UX (8.2), channel-agent install panel (8.3), schedule UX (8.4). Slash commands (8.1) and notification policy UI (8.5) dropped 2026-06-26 — see the strikethrough markers below for context.

### 8.1 ~~Slash commands~~ — dropped 2026-06-26

> User explicitly opted out — `/digest` / `/triage` / `/install` add a discoverability layer but Cowork users in Donna's current flows reach the same outcomes via natural-language requests or admin panels. Drop the composer parser, the `chat/commands.py` registry, and the consumer dispatch. The agent already answers `"summarize this week"` w/o the slash shortcut. Re-add when a real friction point shows up.

> Knock-on: 8.3 channel-agent install ships only via admin panel (no `/install` trigger). The agent itself can still install via natural-language confirmation flow ("install ContractBot in this channel" → agent calls the install endpoint).

### 8.2 Presence / status UX (~1.5d)

**Why:** agents are invisible until they speak. Surface ambient state in the channel.

**WS events emitted by agent runner / dispatcher:**

- `chat.agent.status` — `{state: "drafting"|"waiting_on_user"|"scheduled_for"|"running_tool"|"idle", session_id, channel_id, detail?: string, eta?: iso}`

**Frontend rendering:**

- Channel header chip near the agent name: status state.
- Below the agent's last message: a "drafting…" / "waiting on Alice…" line that auto-clears when the next message lands.
- Subagent transcripts (from 5.3.2) appear as a collapsible thread under the spawning message.

**Files:** `web/src/lib/ws.ts` (new event handlers), `web/src/components/Channel/AgentStatusChip.tsx` (new), `web/src/components/Channel/Message.tsx` (subagent thread render).

### 8.3 Channel-agent install UX (~1d)

Admin panel: `web/src/views/ChannelSettings/AgentsTab.tsx` — list of installed agents, their handle, last activity, install + uninstall actions. Install calls `POST /api/v1/chat/channels/<id>/agents/install` (5.2.2 backend) directly from the panel. The agent can ALSO drive install via natural-language ("install ContractBot in this channel" → agent confirms via `AskUserQuestion` per 1.3/1.5, then hits the same endpoint) — no slash command path.

**Admin panel:** `web/src/views/ChannelSettings/AgentsTab.tsx` — list of installed agents, their handle, last activity, an "uninstall" action.

### 8.4 Schedule UX (~1d)

**Where:** on a channel-resident agent's profile sheet, a "Schedules" tab.

**UI:** list of `Schedule` rows for this agent, with cron editor (cron-as-text + a human-friendly preview), payload editor (markdown), enable/disable toggle. Backed by 7.1's API.

**File:** `web/src/views/AgentProfile/SchedulesTab.tsx`.

### 8.5 ~~Notification policy UI~~ — dropped 2026-06-26

> Backend 7.2 dropped (no `NotificationPolicy` model); no UI to back. Re-add if 7.2 ever lands.

---

## Critical files (summary)

### New
- `server/donna/chat/agents/styles/__init__.py` + `bundled/*.md` (Phase 1)
- `server/donna/chat/agents/nodes/tool_summary.py` (Phase 1)
- `server/donna/chat/agents/tools/ask_user.py` (Phase 1)
- `server/donna/chat/agents/tools/todo_tools.py` (Phase 1)
- `server/donna/chat/agents/hooks/__init__.py` + `bundled/*.py` (Phase 2.3)
- `server/donna/automation/feedback.py` — polarity classifier (Phase 7.3)
- `server/donna/celery_routes.py` (Phase 3.4)
- `server/donna/chat/agents/subagents/__init__.py` + `bundled/*.md` (Phase 5.1.2)
- `server/donna/chat/agents/verify.py` (Phase 5.4)
- `server/donna/chat/agents/subagents/bundled/verifier.md` (Phase 5.4)
- `server/donna/chat/agents/tools/mcp_tool.py` (Phase 5.5)
- `server/donna/automation/` whole app (Phase 7)
- `web/src/components/Channel/AgentStatusChip.tsx` (Phase 8.2)
- `web/src/views/ChannelSettings/AgentsTab.tsx` (Phase 8.3)
- `web/src/views/AgentProfile/SchedulesTab.tsx` (Phase 8.4)
- `server/donna/chat/agents/memory/session_memory.py` (Phase 4)
- `server/donna/chat/agents/memory/auto_dream.py` (Phase 4)
- `server/donna/chat/agents/tools/agent_tool.py` (Phase 5)
- `server/donna/chat/agents/subagents/__init__.py` (Phase 5)
- `server/donna/chat/agents/tools/send_message_tool.py` (Phase 5)
- `server/donna/chat/agents/magicdocs/draft_status_updater.py` (Phase 6)
- `server/donna/chat/agents/prompt_suggestion.py` (Phase 6)

### Edited
- `server/donna/chat/agents/tools/base.py` — add `requires_user_interaction`, `is_concurrency_safe`, `should_defer` fields (Phase 1, 3)
- `server/donna/chat/agents/tools/factory.py` — mode-based `build_registry` + register new tools + MCP proxy registration (Phase 1, 2, 5, 5.5)
- `server/donna/chat/apps.py` — register new tool sets + hook discovery + subagent FS loader (Phase 1, 2, 2.3, 5, 5.1.2)
- `server/donna/chat/models.py` — `AgentSession.mode` field, `is_channel_resident` + `resident_handle` (5.2.2); `Message.kind` + `question_options` + `answer_payload` + `answered_message` + `expires_at` (1.5); `SessionMemory` model + scope/scope_ref (4.1, 4.4); `Artifact.metadata` for multi-audience (6.3) — migrations per phase
- `server/donna/chat/mentions.py` — `@<resident_handle>` dispatch routing (5.2.2)
- `server/donna/chat/agents/nodes/drafter.py` — accept `output_style` arg (Phase 1)
- `server/donna/chat/agents/tools/draft_tools.py` — read output_style from session config; dispatch MagicDoc update; verify_finding wrap (Phase 1, 5.4, 6)
- `server/donna/chat/agents/nodes/tool_dispatcher.py` — concurrency partition + Haiku summary broadcast + `requires_user_interaction` gate + hook fires (Phase 1, 2.3, 3)
- `server/donna/chat/agents/graph.py` — output-cap recovery + AwaitingUser suspend/resume (Phase 1.5, 3)
- `server/donna/chat/agents/runner.py` — session_start hook fire + subagent transcript broadcast (Phase 2.3, 5.3.2)
- `server/donna/chat/agents/state/builder.py` — token-based trigger + structured compaction prompt + scoped memory loader (Phase 3, 4, 4.4)
- `server/donna/chat/agents/nodes/conversation_agent.py` — pass `max_output_tokens_override` + capture `stop_reason` (Phase 3)
- `server/donna/chat/agents/prompts.py` — mode guidance + multi-audience drafter section + COORDINATOR prompt (Phase 2, 5, 6.3)
- `server/donna/chat/agents/memory/extract.py` — emit scope + scope_ref (4.4)
- `server/donna/chat/agents/memory/autodream.py` — group by (scope, scope_ref), not session (4.4)
- `server/donna/chat/tasks.py` — `run_subagent_task` + dispatch `extract_session_memory` post-turn + `chat.resume_turn` (Phase 1.5, 4, 5)
- `server/donna/celery.py` — task_routes import, beat schedule, conditional gevent monkey-patch (Phase 3.4, 7)
- `server/donna/notifications/services.py` — policy gate before dispatch (Phase 7.2)
- `server/donna/settings.py` — `MODEL_CONTEXT_WINDOWS`, beat entries for auto-dream + schedule_tick + feedback_aggregate, `INSTALLED_APPS` += `donna.automation` (Phase 3, 4, 7)
- `server/donna/chat/api/v1/views.py` + `urls.py` — `POST /runs/<run_id>/answer/`, `POST /questions/<id>/answer/` (1.5), `POST /channels/<id>/agents/install/` (5.2.2)
- `server/docker-compose.yml` + `server/deploy/entrypoint.sh` — split `worker-io` + `worker-cpu` services w/ pool detection (Phase 3.4)
- `web/src/components/Channel/Composer.tsx` — slash command popover wiring (Phase 8.1)
- `web/src/components/Channel/Message.tsx` — subagent transcript thread render (Phase 5.3.2 + 8.2)
- `web/src/lib/ws.ts` — `chat.subagent.message`, `chat.agent.status` handlers (5.3.2, 8.2)

### Reused (no edit)
- `donna.chat.services.channel_group` — WS routing
- `donna.core.llm.factory.LLMFactory` — for Haiku/Sonnet/skeptic verifier calls
- `donna.chat.models.Artifact` — already has drafting lifecycle (renamed from `Document` 2026-06-25)
- `donna.chat.models.MessageReaction` — source for aggregator (7.3); polarity classified on read, no new table
- `donna.notifications.services.NotificationService.send` — used as-is by 7.x flows (no policy gate; 7.2 dropped 2026-06-26)
- `donna.chat.models.Channel` + `ChannelMembership` — channel-resident agent install lookup (5.2.2)
- `donna.workspaces.middlewares.WorkspaceMiddleware` — workspace resolution for hooks + MCP server config (2.3, 5.5)
- `donna.cortex.services.CortexService` — for `create_entity`/`linter_check` in FinalizeDraft + AutoDream

---

## Verification

### Per-phase

Each phase ships green tests + manual smoke. Test placement:

- Phase 1: `chat/tests/test_styles.py`, `test_tool_summary.py`, `test_ask_user.py`, `test_todo_tools.py`, `test_hil_multistep.py` (1.5)
- Phase 2: `chat/tests/test_mode_gating.py`, `test_hook_registry.py` (2.3)
- Phase 3: `chat/tests/test_output_cap_recovery.py`, `test_token_compaction.py`, `test_concurrency_partition.py`, `test_celery_routing.py` (3.4)
- Phase 4: `chat/tests/test_session_memory.py`, `test_auto_dream.py`, `test_structured_compaction.py`, `test_memory_sharding.py` (4.4)
- Phase 5: `chat/tests/test_agent_tool.py`, `test_send_message.py`, `test_coordinator.py`, `test_fs_subagent_defs.py` (5.1.2), `test_channel_resident.py` (5.2.2), `test_subagent_visibility.py` (5.3.2), `test_verify_helper.py` (5.4), `test_mcp_tool.py` (5.5)
- Phase 6: `chat/tests/test_magicdoc_draft_status.py`, `test_multi_audience.py` (6.3), `test_prompt_suggestion.py` (deferred)
- Phase 7: `automation/tests/test_schedule_worker.py`, `test_polarity.py`, `test_aggregator.py`, `test_aggregator_excludes_user_messages.py`
- Phase 8: `web/src/__tests__/AgentStatusChip.test.tsx`, `AgentsTab.test.tsx`, `SchedulesTab.test.tsx`

Run inside container (host postgres port-forward broken — see prior session):
```bash
docker exec donna-server bash -lc \
  "cd /opt/donna && DATABASE_HOST=donna-database \
   uv run python -m django test donna.chat --verbosity=2"
bash /Users/ristoc/Workspaces/cube/donna/server/scripts/cleanup_test_residue.sh
```

### End-to-end smoke

After Phase 1+2:
1. Set `AgentSession.config["output_style"] = "customer"`
2. `AgentSession.mode = "drafting"`
3. Bruno → Channel Message Send: `"draft me a status update for the Acme migration"`
4. Watch worker log: `tool_summary` Haiku call, then `update_draft_section` invocation (no more `load_skill` round)
5. Bruno → Channel Documents List: see draft v0 → v1 with customer-tone body

After Phase 3:
1. Force a long tool result (cortex_query returning a 30k-token blob)
2. Confirm no `agent_round_cap_exhausted`; agent recovers via injected resume message

After Phase 4:
1. Run 6 chat turns
2. Check `AgentSession.memory["session_notes"]` populated with 7 sections
3. Force `auto_dream_workspace.delay(<ws-id>)` manually
4. Confirm new `CortexEntity(type='person', author='self', source='donna://auto-dream')` written

After Phase 5:
1. Prompt: `"research what we know about Acme's API standards"`
2. Confirm AgentTool spawn + background subagent + final synthesis arrives
3. Follow-up: `"now also check our Drive folder for any signed contracts"`
4. Confirm send_message reuses the spawned researcher mailbox

After Phase 6:
1. Iterate a draft 5+ times
2. Check sibling DraftStatus artifact updates in-place after each edit
3. Multi-audience: `"draft a launch update for the team, the customer, and the CEO"` → 3 sibling Artifact rows in the channel rail, distinct bodies
4. (deferred) Pause; confirm Haiku ghost-text suggestion appears for the next prompt

After Phase 7:
1. Create a `Schedule` row firing every minute on a test channel; confirm a synthetic message lands w/ the configured payload, and the bound agent responds
2. React 👍 on an agent message → `automation.feedback_aggregate` next run updates `AgentSession.config["feedback_stats"]["win_rate_7d"]`; channel UI chip reflects new ratio
3. Kill `donna-cpu` worker; confirm `donna-io` keeps draining the `schedules` queue

After Phase 8:
1. Agent draft runs; channel header shows "drafting…" chip until the message lands
2. From channel settings → Agents tab → click "Install ContractBot" → channel settings shows the resident agent; `@ContractBot` posted by another user routes to that agent
3. Add a `Schedule` from the agent profile UI; confirm `Schedule` row created via API

### Cleanup discipline

After every test run:
```bash
bash server/scripts/cleanup_test_residue.sh
```

User has stated this is a hard rule (per checkpoint 2026-06-19): tests must leave zero filesystem residue.

---

## Open questions (review before starting)

### Resolved (2026-06-25 Cowork-framing review)

- ✅ **Q2 — AskUserQuestion future resolution** — picked Redis pub/sub up front (see 1.5). Reuses the broker that already holds `turn_lock`; survives worker death.
- ✅ **Q4 — MagicDoc storage** — `Artifact.metadata` JSONField for the status block. The renamed `Artifact` model already gains `metadata` in 6.3.
- ✅ **Q6 — Phase 5 scope** — ship `summarizer` + `planner` + `drafter` + `websearch` + `verifier` (5.4) bundled defs. Filesystem-loaded variant (5.1.2) is the extension surface for everything else.

### Still open — resolve before execution

1. ~~Skill format~~ — N/A as of 2026-06-26 (skills layer dropped; see 2.2).

2. **Subagent isolation** — do subagents share the parent's cortex permissions, or get a restricted subset? E.g. websearch agent probably shouldn't be able to write drafts. (Filesystem-loaded defs in 5.1.2 declare `allowed_tools` per subagent, which partially answers this — but cortex-row visibility scope is separate.)

3. **Output styles vs per-workspace defaults** — user-pickable per channel, OR workspace-defaulted with per-channel override?

### New — Cowork fold-in questions

4. **Hook scope (2.3)** — workspace-global only, OR allow per-channel filtering at registration time? Default answer: workspace-global w/ a `ctx.channel_id` filter inside hook callbacks. Matches the Donna middleware model. A future `WorkspaceHook` DB row (Phase 8 admin UI) opts in to per-channel scope explicitly.

5. ~~NotificationPolicy DSL~~ — N/A as of 2026-06-26 (7.2 dropped).

6. ~~FeedbackSignal cortex linkage~~ — resolved 2026-06-26: `FeedbackSignal` model dropped entirely. Feedback derives from `MessageReaction` on read; aggregator writes rolling stats to `AgentSession.config["feedback_stats"]`. Cortex linkage was the only reason to add a denormalized signal table; with that deferred and the classifier in code, no model is justified.

7. **MCP per-workspace UI (5.5)** — ship a workspace-settings UI for MCP server config in Phase 8, OR push to a later plan? Default: ship in Phase 8 alongside notification policy (same admin surface, low marginal cost).

8. **Adversarial verify cost ceiling (5.4)** — how many verify passes per outbound message before we stop? Default: 1 pass per message, max 3 skeptics per pass, ~9 Haiku calls per turn worst case. Surface a `WorkspaceConfig.verify_max_per_turn` for paranoid customers.

9. **Channel-resident agent lifecycle (5.2.2)** — when a channel is archived, do its resident `AgentSession` rows get archived too? Default: yes, cascade via the existing `channel.is_archived` flag. Schedules disable automatically (via `enabled=False` propagation on archive).

10. **Schedule clock skew (7.1)** — `schedule_tick` runs every 30s; what happens if the worker is down for 5 minutes? Default: when it comes back up, fire all `next_fires_at <= now` once (catch-up), not N times for the missed cron slots. Doc this in `automation/services.py:_next_cron` docstring.

These are clarifying questions for the user's review, not blocking decisions. Default answers above; replace per feedback.
