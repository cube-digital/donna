# Plan — Donna agent runtime: Claude Code pattern adoption

> Source of architecture decisions: [`docs/important-docs/00n - claude-code-patterns-for-donna.md`](../../docs/important-docs/00n%20-%20claude-code-patterns-for-donna.md).
> Source of current Donna shape: 2026-06-21 verification pass (see "Current state" below).
> Out of scope: cortex Phase 6 (eval harness + maintenance workers) — separate plan, see [`docs/important-docs/00f - silver-completion-plan.md`](../../docs/important-docs/00f%20-%20silver-completion-plan.md).

---

## Context

### Why this work

A1 (Q&A runtime) and A2 (drafting layer) are shipped. The agent functions but feels generic. Reading the Claude Code source surfaced ~20 patterns that explain why their drafting / iteration / multi-agent UX feels natural — none of which Donna has. Document `00n` captures the patterns; this plan converts them into concrete code changes against Donna's current Django/Celery/Channels stack.

The goal is **production-grade drafting + multi-agent orchestration** without re-architecting the chat layer. Every change is additive: new fields on existing models, new tools in the registry, new Celery tasks. The current Q&A flow keeps working unchanged through every phase.

### Current state (verified 2026-06-21)

| Subsystem | File | What exists | What's missing |
|---|---|---|---|
| `DonnaTool` ABC | [`chat/agents/tools/base.py:49`](../donna/chat/agents/tools/base.py) | name, description, args_model, timeout_s, taint_safe | is_concurrency_safe, should_defer, requires_user_interaction, structured permission result |
| Tool dispatcher | [`chat/agents/nodes/tool_dispatcher.py:208`](../donna/chat/agents/nodes/tool_dispatcher.py) | ThreadPoolExecutor(max_workers=1), sequential, taint check | concurrent partitioning, abort-cascade |
| Graph loop | [`chat/agents/graph.py:24`](../donna/chat/agents/graph.py) | MAX_ROUNDS=6, defensive fallback | output-cap recovery, stop_reason handling |
| State builder | [`chat/agents/state/builder.py:29`](../donna/chat/agents/state/builder.py) | message-count trigger (60), branch-aware buckets, Haiku digest | token-based trigger, structured compaction prompt |
| `AgentSession` | [`chat/models.py:124`](../donna/chat/models.py) | memory + config JSONFields | no `mode` field, no SessionMemory model |
| `Document` (A2) | [`chat/models.py:246`](../donna/chat/models.py) | status, version, target_doc_type, finalized_entity_id, partial unique | — (shipped) |
| Tool registry | [`chat/agents/tools/factory.py`](../donna/chat/agents/tools/factory.py) | GLOBAL_REGISTRY frozen, draft_enabled gate | no skills registry, no output-style registry |
| Celery runner | [`chat/tasks.py:68`](../donna/chat/tasks.py) | turn_lock, build_state→registry→graph→persist | no post-turn memory extraction hook |
| WS broadcast | [`chat/services.py:42`](../donna/chat/services.py) + [`runner.py:84`](../donna/chat/agents/runner.py) | channel_group, channel_typing_group, agent_run_group | (sufficient) |

### Plan shape

Six phases, sequenced by ROI per day. Each phase is independently shippable. Phase 1 lifts perceived quality immediately; later phases compound. Total ≈ 13d.

| Phase | Scope | Effort |
|---|---|---|
| 1 | Drafting UX polish: output styles, Haiku tool-use summaries, AskUserQuestion, TodoWrite | ~2d |
| 2 | Drafter as skilled agent: drafting mode, skills layer | ~2d |
| 3 | Robust runtime: output-cap recovery, token-based compaction, concurrency-safe tools | ~1.5d |
| 4 | Memory loop: SessionMemory + AutoDream + structured compaction prompt | ~2.5d |
| 5 | Multi-agent: AgentTool spawn, named-agent mailbox, coordinator mode | ~3d |
| 6 | Long-tail polish: MagicDocs auto-updater, PromptSuggestion | ~2d |

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

---

## Phase 2 — Drafter as a skilled agent (~2d)

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

### 2.2 Skills layer (~1.5d)

Markdown + frontmatter, discovered at boot.

**New dir + loader** mirror Phase 1's output styles, expanded with paths-and-trigger semantics from `00n §6.1`:

```
server/donna/chat/agents/skills/
├── __init__.py            # loader + Skill dataclass
├── bundled/
│   ├── contract.md
│   ├── email_response.md
│   ├── meeting_notes.md
│   ├── brief.md
│   └── status_update.md
└── README.md
```

Skill format:

```markdown
---
name: contract
description: Draft a formal contract with standard clauses
triggers: ["draft a contract", "write a contract", "MSA", "SOW"]
applies_in_modes: ["drafting"]
---

When drafting a contract, follow this structure:

1. **Parties** — full legal names + jurisdictions
2. **Recitals** — short context paragraphs ("WHEREAS...")
3. **Definitions** — all CAPS terms used elsewhere
4. **Term & Termination** — duration + exit clauses
5. **Payment** — amount, schedule, late-fee policy
6. **Governing law** — jurisdiction + venue
7. **Signatures**

Use formal register. Avoid contractions. Define every term in CAPS
the first time it appears.
```

**New file:** `server/donna/chat/agents/skills/__init__.py`

```python
"""Skills layer — markdown templates the drafter loads on demand.

Discovery: bundled/*.md at boot + workspace-scoped at runtime (Phase 7).
Listing in system prompt at <1% budget (truncated descriptions);
full body loads when LLM invokes load_skill(name).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml


_BUNDLED_DIR = Path(__file__).parent / "bundled"


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    triggers: list[str]
    applies_in_modes: list[str]


def load_bundled_skills() -> Mapping[str, Skill]:
    skills: dict[str, Skill] = {}
    for path in _BUNDLED_DIR.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        if text.startswith("---\n"):
            _, fm, body = text.split("---\n", 2)
            meta = yaml.safe_load(fm) or {}
        else:
            meta, body = {}, text
        name = meta.get("name") or path.stem
        skills[name] = Skill(
            name=name,
            description=meta.get("description", ""),
            body=body.strip(),
            triggers=meta.get("triggers", []) or [],
            applies_in_modes=meta.get("applies_in_modes", []) or [],
        )
    return skills


# Module-level snapshot loaded at boot.
BUNDLED_SKILLS: Mapping[str, Skill] = load_bundled_skills()
```

**New tool:** `server/donna/chat/agents/tools/skill_tools.py`

```python
"""SkillTool — load a skill body into the conversation (00n §6.1).

The system prompt lists every skill at a 1% budget (truncated
descriptions). When the LLM invokes load_skill(name), the full body
is returned as the tool result and the LLM uses it for the next
generation.
"""
from typing import ClassVar

from pydantic import BaseModel, Field

from donna.chat.agents.skills import BUNDLED_SKILLS
from donna.chat.agents.tools.base import DonnaTool, ToolContext, ToolResult


class LoadSkillArgs(BaseModel):
    name: str = Field(description="Skill slug to load")


class LoadSkillTool(DonnaTool):
    name: ClassVar[str] = "load_skill"
    description: ClassVar[str] = (
        "Load a domain-specific drafting skill. Call when the user's "
        "request matches a skill's trigger phrases. Returns guidance "
        "to follow for the rest of the turn."
    )
    args_model: ClassVar[type[BaseModel]] = LoadSkillArgs

    def run(self, args: LoadSkillArgs, ctx: ToolContext) -> ToolResult:
        skill = BUNDLED_SKILLS.get(args.name)
        if skill is None:
            return ToolResult.fail(
                f"No skill named '{args.name}'. Available: "
                f"{', '.join(sorted(BUNDLED_SKILLS))}"
            )
        return ToolResult(payload={
            "name": skill.name,
            "body": skill.body,
        })
```

**Edit:** [`prompts.py:build_system_prompt`](../donna/chat/agents/prompts.py) — append a 1%-budget skills listing in drafting/planning mode:

```python
def _skills_listing(mode: str) -> str:
    applicable = [s for s in BUNDLED_SKILLS.values()
                  if not s.applies_in_modes or mode in s.applies_in_modes]
    if not applicable:
        return ""
    lines = ["== SKILLS (load with load_skill(name)) =="]
    for s in applicable:
        desc = s.description[:120]
        triggers = ", ".join(f'"{t}"' for t in s.triggers[:3])
        lines.append(f"- {s.name}: {desc}  (triggers: {triggers})")
    return "\n".join(lines)
```

---

## Phase 3 — Robust runtime (~1.5d)

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
- draft tools: `is_concurrency_safe = False` (mutate Document)
- todo tools: `is_concurrency_safe = False` (mutate session.memory)
- ask_user_question: `is_concurrency_safe = False` (blocks the user)

---

## Phase 4 — Memory loop (~2.5d)

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

---

## Phase 5 — Multi-agent (~3d)

**Goal:** AgentTool spawn primitive + named-agent mailbox + coordinator mode.

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
        allowed_tools=("cortex_query", "read_entity", "load_skill",
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

### 5.3 Coordinator mode (~0.5d)

**Edit:** `prompts.py` — add COORDINATOR system prompt template. Activated when `session.config.get("coordinator_mode")` is True. Background subagents emit `<task-notification>` XML blocks (via Celery post-success hook) into the parent's message store; parent re-reads and synthesizes.

---

## Phase 6 — Long-tail polish (~2d)

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

### 6.2 PromptSuggestion (~1d)

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

---

## Critical files (summary)

### New
- `server/donna/chat/agents/styles/__init__.py` + `bundled/*.md` (Phase 1)
- `server/donna/chat/agents/nodes/tool_summary.py` (Phase 1)
- `server/donna/chat/agents/tools/ask_user.py` (Phase 1)
- `server/donna/chat/agents/tools/todo_tools.py` (Phase 1)
- `server/donna/chat/agents/skills/__init__.py` + `bundled/*.md` (Phase 2)
- `server/donna/chat/agents/tools/skill_tools.py` (Phase 2)
- `server/donna/chat/agents/memory/session_memory.py` (Phase 4)
- `server/donna/chat/agents/memory/auto_dream.py` (Phase 4)
- `server/donna/chat/agents/tools/agent_tool.py` (Phase 5)
- `server/donna/chat/agents/subagents/__init__.py` (Phase 5)
- `server/donna/chat/agents/tools/send_message_tool.py` (Phase 5)
- `server/donna/chat/agents/magicdocs/draft_status_updater.py` (Phase 6)
- `server/donna/chat/agents/prompt_suggestion.py` (Phase 6)

### Edited
- `server/donna/chat/agents/tools/base.py` — add `requires_user_interaction`, `is_concurrency_safe`, `should_defer` fields (Phase 1)
- `server/donna/chat/agents/tools/factory.py` — mode-based `build_registry` + register new tools (Phase 1, 2, 5)
- `server/donna/chat/apps.py` — register new tool sets (Phase 1, 2, 5)
- `server/donna/chat/models.py` — `AgentSession.mode` field + migration (Phase 2)
- `server/donna/chat/agents/nodes/drafter.py` — accept `output_style` arg (Phase 1)
- `server/donna/chat/agents/tools/draft_tools.py` — read output_style from session config; dispatch MagicDoc update (Phase 1, 6)
- `server/donna/chat/agents/nodes/tool_dispatcher.py` — concurrency partition + Haiku summary broadcast + `requires_user_interaction` gate (Phase 1, 3)
- `server/donna/chat/agents/graph.py` — output-cap recovery (Phase 3)
- `server/donna/chat/agents/state/builder.py` — token-based trigger + structured compaction prompt (Phase 3, 4)
- `server/donna/chat/agents/nodes/conversation_agent.py` — pass `max_output_tokens_override` + capture `stop_reason` (Phase 3)
- `server/donna/chat/agents/prompts.py` — mode guidance + skills listing + COORDINATOR prompt (Phase 2, 5)
- `server/donna/chat/tasks.py` — `run_subagent_task` + dispatch `extract_session_memory` post-turn (Phase 4, 5)
- `server/donna/settings.py` — `MODEL_CONTEXT_WINDOWS`, beat entries for auto-dream (Phase 3, 4)
- `server/donna/chat/api/v1/views.py` + `urls.py` — `POST /runs/<run_id>/answer/` for AskUserQuestion replies (Phase 1)

### Reused (no edit)
- `donna.chat.services.channel_group` — WS routing
- `donna.core.llm.factory.LLMFactory` — for Haiku/Sonnet calls
- `donna.chat.models.Document` — already has drafting lifecycle
- `donna.cortex.services.CortexService` — for `create_entity`/`linter_check` in FinalizeDraft + AutoDream

---

## Verification

### Per-phase

Each phase ships green tests + manual smoke. Test placement:

- Phase 1: `chat/tests/test_styles.py`, `test_tool_summary.py`, `test_ask_user.py`, `test_todo_tools.py`
- Phase 2: `chat/tests/test_mode_gating.py`, `test_skills.py`
- Phase 3: `chat/tests/test_output_cap_recovery.py`, `test_token_compaction.py`, `test_concurrency_partition.py`
- Phase 4: `chat/tests/test_session_memory.py`, `test_auto_dream.py`, `test_structured_compaction.py`
- Phase 5: `chat/tests/test_agent_tool.py`, `test_send_message.py`, `test_coordinator.py`
- Phase 6: `chat/tests/test_magicdoc_draft_status.py`, `test_prompt_suggestion.py`

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
4. Watch worker log: `tool_summary` Haiku call, then `load_skill(status_update)` invocation
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
3. Pause; confirm Haiku ghost-text suggestion appears for the next prompt

### Cleanup discipline

After every test run:
```bash
bash server/scripts/cleanup_test_residue.sh
```

User has stated this is a hard rule (per checkpoint 2026-06-19): tests must leave zero filesystem residue.

---

## Open questions (review before starting)

1. **Skill format** — should the body be **prepended to the user message** (drafter prompt) or **injected via tool result**? Claude Code does both depending on context. Donna's drafter is simpler: tool-result injection is cleaner.

2. **AskUserQuestion future resolution across workers** — in-memory dict works for single-worker dev. Multi-worker prod needs Redis pub/sub. Worth designing both surfaces (in-memory + Redis) up front?

3. **Subagent isolation** — do subagents share the parent's cortex permissions, or get a restricted subset? E.g. websearch agent probably shouldn't be able to write drafts.

4. **MagicDoc storage** — sibling `DocumentStatus` model or `Document.metadata["status_artifact"]` JSONField? Former is queryable + indexable; latter is simpler.

5. **Output styles vs per-workspace defaults** — user-pickable per channel, OR workspace-defaulted with per-channel override?

6. **Phase 5 scope** — should we ship websearch + summarizer in Phase 5, or stub the registry and add specialists in Phase 7? Recommend stubbing — gets the framework live with one real subagent (`summarizer`), defer websearch until we know the search API surface.

These are clarifying questions for the user's review, not blocking decisions. Default answers above; replace per feedback.
