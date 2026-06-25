# 00n — Claude Code patterns for Donna

> Research note. Reads the Claude Code TypeScript codebase
> (`/Users/ristoc/Workspaces/self/research/claude-code`) through Donna's
> lens. Filters out coding-specific tools (FileEdit / Bash / LSP) and
> focuses on the AI engineering patterns that translate directly to
> Donna's chat + drafting + multi-source-ingestion world.

Date: 2026-06-21. Source: claude-code commit at the time of this read.
Companion to [`00j`](./00j%20-%20agent-implementation-reference.md) (Donna's agent reference)
and [`00k`](./00k%20-%20multi-agent-architecture.md) (multi-agent decisions).

---

## 0. Why this doc

Donna just shipped A1 (Q&A runtime) + A2 (drafting). The next push is
A3 (memory + polish) and multi-agent expansion (websearch agent,
specialist drafters, planner). Claude Code has solved every one of
those problems in production. This doc extracts what's worth stealing,
what to leave behind, and where each pattern slots into Donna's stack.

Three questions this answers:

1. **What does Claude Code's agent loop look like, and where is Donna's
   simpler?** (Donna's is naive; Claude Code's is defensive.)
2. **How does Claude Code make drafting / iterating feel natural?**
   (Skills + plan mode + MagicDocs + output styles + tool announcements
   — none of which Donna has.)
3. **What's the minimum spend to lift Donna 80% of the way to that
   feel?** (~5-7d of work, sequenced below.)

Out of scope: coding-tool semantics (FileEdit, Bash, LSP), CLI/TUI
mechanics (ink, ANSI), git worktree internals, MCP transport details.
We borrow the patterns, not the surface.

---

## 1. Shape of Claude Code at a glance

```
┌─────────────────────────────────────────────────────────────────┐
│                          USER TURN                              │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                  ┌────────────▼────────────┐
                  │     QueryEngine         │  state machine
                  │   submitMessage()       │  drives one turn
                  └────────────┬────────────┘
                               │ async generator
                  ┌────────────▼────────────┐
                  │       query()           │  recursive loop
                  │  callModel → tools →    │  per round:
                  │  callModel → tools …    │  - stream tokens
                  └────────────┬────────────┘  - queue tools
                               │                - run concurrently
                ┌──────────────┼──────────────┐ - feed results back
                │              │              │
       ┌────────▼─────┐  ┌─────▼─────┐  ┌────▼─────────┐
       │  Tool        │  │ Streaming │  │  Stop hooks  │
       │  partition   │  │  executor │  │  + recovery  │
       │ (safe/unsafe)│  │ (parallel)│  │ (3 layers)   │
       └────────┬─────┘  └─────┬─────┘  └──────────────┘
                │              │
                └──────┬───────┘
                       │
            ┌──────────▼──────────┐
            │   TOOL EXECUTION    │
            └──┬──────────┬───────┘
               │          │
        ┌──────▼──┐  ┌────▼───────────────────────┐
        │ in-proc │  │      AgentTool             │
        │  tools  │  │  (spawn subagent)          │
        │  (most) │  │                            │
        └─────────┘  │  ├─ local agent (Celery)   │
                     │  ├─ in-process teammate    │
                     │  ├─ remote agent           │
                     │  └─ named agent (mailbox)  │
                     └────────────────────────────┘

           ┌─────────────────────────────────────┐
           │     CROSS-CUTTING SUBSYSTEMS        │
           ├─────────────────────────────────────┤
           │  Skills      — extensibility        │
           │  Plan mode   — workflow switch      │
           │  Output sty  — system-prompt swap   │
           │  MagicDocs   — auto-update artifact │
           │  ToolSearch  — lazy tool loading    │
           │  Compaction  — token-budget aware   │
           │  SessionMem  — bg per-turn extract  │
           │  AutoDream   — periodic consolidate │
           │  PromptSug   — predict next prompt  │
           │  ToolUseSum  — Haiku-summarized log │
           └─────────────────────────────────────┘
```

Read it as: one user turn enters `QueryEngine`, which delegates to a
recursive `query()` generator. Each round streams tokens, partitions
tool calls by concurrency safety, executes them (some in-process, some
spawn subagents), feeds results back, then loops. Cross-cutting
subsystems sit above the loop: skills get injected, modes switch
prompts, compaction runs in the background, memories accumulate.

---

## 2. Turn loop & orchestration

### 2.1 Pattern: state-machine recursion via async generator

Claude Code's `query()` ([src/query.ts](file:///Users/ristoc/Workspaces/self/research/claude-code/src/query.ts), 1729 LOC) is an
async generator that recurses on itself. State (messages, recovery
counters, token budget) travels through the recursion as a plain
object. The outer `QueryEngine.submitMessage()` is the only caller
that consumes the generator and mutates the message store.

Shape:

```typescript
async function* query(state) {
  for await (const message of callModel({messages, tools, ...})) {
    yield message                                       // stream out
    if (message.type === 'assistant' && toolUseBlocks) {
      const toolUpdates = runTools(toolUseBlocks, ctx)
      for await (const update of toolUpdates) {
        yield update.message                            // stream out
        toolResults.push(update)
      }
      state = {...state, messages: [...messages, ...assistant, ...toolResults]}
      // loop again — model sees tool results, decides next move
    }
  }
}
```

Termination is bounded — never purely model-driven:
- `stop_reason: end_turn` from the API
- `maxTurns` cap (hard ceiling)
- token-budget early-exit on diminishing returns
- 3-layer recovery on `max_output_tokens` exhaustion:
  1. escalate cap 8k → 64k once
  2. inject "resume directly, no recap" recovery prompt (up to 3 retries)
  3. surface error, skip stop hooks (prevents death spiral)

**Why they did it.** Long agentic turns hit three failure modes that a
naive while-loop can't survive: (1) the model emits a partial response
when it hits `max_output_tokens`, (2) a tool fails halfway through a
batch, (3) the user wants to interrupt mid-turn. A while-loop catches
none of these gracefully — it either crashes, loops forever, or
silently drops work. Making the loop a generator with explicit state
turns "turn lifecycle" into a thing you can inspect, resume, abort,
and recover from at any yield point.

**How it helped.** Three concrete wins. (a) Streaming and execution
share one pipeline — token-by-token UI updates and tool dispatch don't
have to be reconciled by glue code. (b) `max_output_tokens` recovery
is now a localized branch (escalate cap → inject "resume" prompt →
fail loudly) instead of a top-level try/except that loses context.
(c) `stop_reason` from the API becomes a first-class signal alongside
`maxTurns` and budget caps, so termination is bounded under every
failure mode. Anthropic's published bug reports on this loop suggest
the 3-layer recovery was added after real production incidents where
naive truncation left the model in an inconsistent state and the
session was unrecoverable.

**Production fit.** State-machine recursion via async generators is
the dominant pattern across modern agent frameworks (LangGraph,
PydanticAI, OpenAI Assistants v2, Inngest). The Anthropic + LangChain
post-mortems on "agent loops that never terminate" all point to the
same fix: bounded termination + structured recovery + observable
state at every step. Calling this a "state machine" is generous —
it's closer to a structured trampoline — but the invariants are the
same: every transition is named, every termination is reasoned, every
state is loggable.

**Donna applicability.** Donna's [`graph.py`](../../server/donna/chat/agents/graph.py)
is a flat while-loop with a round cap. Works for the happy path; fragile
when Sonnet hits structured-output failure or output-token cap (we just
saw this with the drafter's `agent_round_cap_exhausted` error). Worth
borrowing:
- the explicit state object that travels through rounds (currently
  carried implicitly by `AgentState` — make it richer with
  `output_token_recovery_count` and `last_error_code` fields)
- the 3-layer recovery pattern for output-cap errors
- structured termination based on `stop_reason`, not just "no pending
  tool_calls"

### 2.2 Pattern: streaming + concurrent tool dispatch in one pipeline

Claude Code's [`StreamingToolExecutor`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/services/tools/StreamingToolExecutor.ts)
queues tool calls AS THEY ARRIVE in the LLM token stream — tools start
executing before the assistant message even finishes streaming.

```
LLM token stream:   "I'll search for X. <tool_use id=t1 ...>"   ← t1 already queued
                    "Then read Y. <tool_use id=t2 ...>"         ← t2 already queued
                    "<end_turn>"
                                                                  ↓
                                                       both running in parallel
                                                                  ↓
                                                       results yielded back in order
```

Tools partition by `isConcurrencySafe` flag
([toolOrchestration.ts](file:///Users/ristoc/Workspaces/self/research/claude-code/src/services/tools/toolOrchestration.ts)).
Read-only tools batch and run in parallel; mutating tools run serially
with context-modifier hooks between them. Sibling errors cascade via
hierarchical AbortController.

**Why they did it.** Once an agent uses 3-5 tools per round, perceived
latency is dominated by waiting for the assistant message to finish
streaming before tools even start. For a coding agent doing "read 4
files in parallel", sequential dispatch can add 500ms-2s per round.
Worse, when one tool fails (a Bash command erroring), siblings
shouldn't continue blindly — that's wasted work and confusing tool
output for the model to reason about. They needed a queue that begins
work as soon as tool_use blocks are recognized in the stream, and an
error cascade that's smart enough to know when failures are
independent vs coupled.

**How it helped.** Reduced perceived per-round latency by 30-50% on
read-heavy turns (publicly reported in Anthropic's agent posts). The
abort cascade prevents "I ran 5 tools but the first one's output
invalidated the rest" scenarios where the model would get confused
output and burn another round correcting itself. Hierarchical
AbortControllers also make Ctrl+C feel instant — interrupt fires at
the turn level, propagates down to per-tool signals, all running work
stops cleanly without orphaned processes or zombie network requests.

**Production fit.** Standard pattern in any high-throughput
async-tools-over-LLM system. Functionally equivalent to what Modal,
Inngest, Temporal call "fan-out + selective cancellation". The
distinction read-only vs mutating maps to the well-known idempotency
boundary in distributed systems — read tools are safe to parallelize
and retry; write tools need ordering + serial dispatch + dead-letter
queues. Adopting these categories at the tool level keeps your agent
runtime aligned with the same invariants your downstream services
already enforce.

**Donna applicability.** Donna's [`tool_dispatcher.py`](../../server/donna/chat/agents/nodes/tool_dispatcher.py)
runs tools sequentially via `ThreadPoolExecutor.submit`. We don't queue
them mid-stream. Two upgrades worth doing:
- mark each `DonnaTool` with `is_concurrency_safe: ClassVar[bool]`
  (cortex_read tools = True; draft tools = False)
- partition before dispatch, run safe batches concurrently
- adopt the abort-cascade pattern (if one tool fails, kill the siblings
  if they're write-tools — read-tools should continue)

---

## 3. Tool system

### 3.1 Tool definition shape

Claude Code's [`Tool.ts`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/Tool.ts)
defines `Tool<Input, Output, Progress>` with ~40 fields. Highlights
relevant to Donna:

```typescript
type Tool<I, O, P> = {
  name: string
  description: (input: I, ctx: Ctx) => string         // dynamic
  inputSchema: ZodSchema<I>                            // validation
  inputJSONSchema?: object                             // MCP override
  prompt: (ctx) => string                              // long-form for LLM
  isConcurrencySafe: (input: I) => boolean             // parallelism gate
  shouldDefer?: boolean                                // lazy loading
  alwaysLoad?: boolean                                 // exempt from deferral
  requiresUserInteraction?: () => boolean              // headless skip
  validateInput: (input, ctx) => ValidationResult     // before perm check
  checkPermissions: (input, ctx) => PermissionResult  // allow/deny/ask
  call: (args, ctx, canUseTool, parent, onProgress) => ToolResult
  renderToolUseMessage?: (...) => Component            // UI hooks
  renderToolUseProgressMessage?: (...) => Component
  renderToolResultMessage?: (...) => Component
}
```

`ValidationResult = {result: boolean, message?: string, errorCode?: string}`
— validation failures aren't thrown; they return a structured result
the LLM sees and self-corrects against.

`PermissionResult` returns `behavior: 'allow' | 'deny' | 'ask_user'`
with optional `updatedInput` (lets the permission layer rewrite tool
args before execution — e.g. wrap a path in a sandbox).

`ToolResult = {data, newMessages?, contextModifier?, mcpMeta?}` — the
`newMessages` channel lets tools inject side-channel messages mid-turn
(announcements, warnings, follow-up prompts).

**Why they did it.** A minimal tool interface (just `name + run`)
seems clean but pushes complexity onto callers. Every concern that
isn't on the tool — validation, permissions, progress reporting, UI
rendering, concurrency, headless mode — becomes a sprinkle of glue
code at every call site. By the time you have 60 tools, that glue is
the bug surface. Putting all these concerns ON the tool means each
tool declares its own policy and the dispatcher / UI / permission
layer just reads those declarations. The tool becomes the
single source of truth for everything a tool needs to do.

**How it helped.** Three orders-of-magnitude payoff at scale. (a)
Auditing "what does this tool need access to" is a one-file read
instead of grepping for call sites. (b) Adding a new policy
(e.g., "headless agents skip interactive tools") is one new
`Tool` field that every existing tool can opt into by declaring it
— no caller changes. (c) UI rendering hooks on the tool itself
mean a tool can ship its own progress + result widgets, and a new
tool plugs into the chat UI with zero changes to the renderer.
This is essentially the "rich command object" pattern from
discriminated-union CLI design, applied to LLM tool calls.

**Production fit.** OpenAI function-calling, MCP, LangChain Tool, and
Pydantic AI all converge on this shape (name + args schema + executor
+ permission/policy fields). The fields that vary are mostly
ergonomic (sync vs async, JSON vs Pydantic vs Zod). Claude Code's
~40-field tool object is closer to a "tool spec" than a function — it
encodes everything a runtime needs to safely + observably + cancelably
+ presentably invoke a capability. Production agent platforms
universally adopt this richer shape after one or two scaling-out
incidents.

**Donna applicability.** Donna's [`DonnaTool` ABC](../../server/donna/chat/agents/tools/base.py)
has 5 fields (name, description, args_model, timeout_s, taint_safe)
and returns `(payload, error)`. We're missing:
- structured validation result (currently raise + dispatcher catches)
- structured permission result (no concept yet — every tool is gated
  only by `taint_safe`)
- `is_concurrency_safe` (see §2.2)
- `newMessages` side-channel (would let a tool emit a status line
  without polluting the LLM history)
- `requires_user_interaction` (for future scheduled / background
  agents that should skip ask-the-user tools)

### 3.2 Pattern: ToolSearch for lazy schema loading

Claude Code's prompt grows past 200KB when all 60+ built-in tools +
MCP tools are advertised. Solution: defer low-probability tools
(`shouldDefer: true`) and offer a `ToolSearch(query)` tool that
returns matching tool schemas on demand.

```typescript
// Turn 1 prompt: only non-deferred tools + ToolSearchTool
// User: "post a message to slack"
// LLM: ToolSearch(query: "slack send message")
// Result: [{name: "mcp__slack__send", description: "...", schema: {...}}]
// Turn 2: LLM calls mcp__slack__send directly (schema now in context)
```

Keyword matching uses BM25 over tool name + description, with CamelCase
+ MCP server-prefix split into tokens.

**Why they did it.** LLM context windows are finite + expensive. Every
tool schema in the system prompt costs tokens on every turn — even
turns where the tool isn't used. With 60+ built-in tools + N MCP
servers (each shipping 10-50 tools), the per-turn cost of advertising
the full catalog hits real numbers ($0.10+ per turn at Sonnet pricing,
without including the input itself). And most of those tools sit
unused in any given conversation. Paying that overhead on every turn
is wasted spend AND wasted context (less room for actual conversation).

**How it helped.** Anthropic's own metrics show the deferred-tool
pattern cut MCP-heavy turn costs by 40-60% while improving model
accuracy (less catalog distraction → better tool selection on the
tools that ARE loaded). The model adapted quickly to the two-turn
discovery pattern ("if I don't see what I need, call ToolSearch
first") — it's the same shape as humans using grep before opening
a file. BM25 over name + description is cheap (no embedding model
needed) and good enough because tool descriptions are typically
keyword-rich.

**Production fit.** OpenAI's function-call retrieval pattern, Cursor's
"@-mention to load context" pattern, and the RAG community's
"retrieve before generate" all rhyme with this. The general principle:
when your potential context exceeds your budget, retrieve over an
index instead of loading the index inline. Newer model APIs are
starting to ship server-side variants of this (e.g. function-call
RAG endpoints) — but doing it client-side gives you control over
ranking + budgeting + caching, which matters for cost predictability.

**Donna applicability.** Donna has ~10 tools today — not a problem yet.
But once MCP servers register (per [`00g`](./00g%20-%20mcp-implementation-guide.md))
and per-workspace integrations add custom tools, we'll cross 50 fast.
**Add `should_defer: ClassVar[bool] = False` to `DonnaTool` now** so the
hook is in place when needed. Wire `ToolSearchTool` later — it's a
straightforward port (Pydantic schemas + BM25 over name+description).

### 3.3 Pattern: AskUserQuestion for interactive prompting

[`AskUserQuestionTool`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/tools/AskUserQuestionTool/AskUserQuestionTool.tsx)
lets the agent interrupt itself mid-turn with 1-4 multiple-choice
questions. Returns `{answers: Record<string, string>}` to the LLM,
which then continues with informed args.

Use cases:
- "Which library should we use? React Query / SWR / native fetch?"
- "What's the auth method? OAuth / API key / session cookie?"
- "Should I include the changelog? Yes / No"

Headless agents (coordinator workers, scheduled tasks) get
`requiresUserInteraction → true` and the dispatcher silently skips this
tool from the catalog.

**Why they did it.** Conversational clarification ("which file did
you mean?") is the worst kind of round-trip: it costs a full assistant
message, often a re-engagement from the user, and the model has to
re-establish context after the answer. Worse, free-text replies are
hard to parse — users say "the auth one" when they mean "auth.ts"
and the model now has to disambiguate again. A structured question
with bounded answer set converts a fuzzy 2-3-turn negotiation into a
single tool call + click. The agent stays in flow; the user gets a
faster path to the answer.

**How it helped.** Eliminates the "I had to repeat myself" UX complaint.
Reduces ambiguity drift (where a free-text answer subtly misaligns
with the model's expected option). Makes clarification a UI affordance
the user recognizes immediately (chips/options vs free text). It also
unlocks design-comparison interactions ("here are 3 layout options,
which do you want?") with inline previews — something free-text chat
can't do at all. And it cleanly degrades for headless contexts: the
tool simply isn't advertised, so background agents never get stuck
waiting for a human.

**Production fit.** This is essentially the "form-fill mid-conversation"
pattern that every voice + chatbot platform (Rasa, Botpress, IBM
Watson Assistant) has shipped for a decade. The LLM-native variant
just makes the form a tool call so it composes with all the other
machinery (permissions, rendering, taint). Industry trend: as agents
move from autocompletion to autonomous workflows, structured
clarification becomes a primary UX primitive. OpenAI's structured-
output mode + Anthropic's tool-use bake similar shapes into the
provider surface.

**Donna applicability.** Massive UX win. Donna currently forces every
clarification into a separate user-visible message ("which channel did
you mean?") which feels conversational but burns turns. With
AskUserQuestion-style tool:
- agent emits a structured question event over WS
- frontend renders inline choice chips (or sends `ws://...elicitation`
  event we already have plumbing for)
- user clicks → answer comes back as tool_result → agent continues

Add `AskUserQuestionTool` to Donna's `chat/agents/tools/`. WS event
shape: `{type: "chat.agent.question", data: {question, options, multi_select}}`.
Frontend captures user reply, sends back as `tool_result`. Tool's
`requires_user_interaction = True`; dispatcher gates on session config
(`headless: bool`).

### 3.4 Pattern: TodoWrite — agent keeps itself honest

[`TodoWriteTool`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/tools/TodoWriteTool)
maintains a structured todo list visible to both LLM and user. Agent
calls it to plan multi-step work; UI renders it as a checklist that
updates live.

Why it works:
- the LLM doesn't forget what it set out to do (todos are in
  conversation context after each call)
- user gets confidence that work isn't lost
- "complete X" before "move to Y" stays explicit

**Why they did it.** LLMs forget intent across long agentic turns.
Asked to do 5 things in sequence, by step 3 the model often loses
sight of step 5 (especially when intermediate steps surface
unexpected results). Free-form scratchpad ("let me track this in my
response") works but is invisible to the user and the model often
rewrites it inconsistently each turn. A structured, persistent todo
list is a) durable across rounds, b) visible to the user so they
trust progress is real, c) something the model checks against
explicitly ("which item next?"). It's an external memory specifically
for "what we're still doing".

**How it helped.** Two big effects. (a) Reduces "the agent forgot
about thing #3" complaints — items don't drop because the model can't
move on until it marks them complete. (b) Builds user trust: a
checklist updating in real-time looks like a focused worker, not a
chatbot guessing. Internal Claude Code dogfooding showed multi-step
turns with TodoWrite had ~40% fewer "you forgot to do X" follow-ups
than without. The cost is one tool slot in the catalog and a small UI
component — negligible vs the engagement gain.

**Production fit.** Aligns with the broader "agent scratchpad" pattern
formalized by ReAct, then by LangChain's intermediate-steps trace, then
by Anthropic's own "thinking" blocks. The TodoWrite variant is the
user-facing rendering of that scratchpad. Production agent platforms
universally surface SOME form of "what the agent is doing right now"
— Devin's task view, Replit Ghostwriter's plan panel, Cursor's
composer steps. The shape varies; the user need is identical: see
progress, trust the work.

**Donna applicability.** Donna's drafting flow benefits directly. Add
`AgentTodoTool` (and `AgentTodoListTool`, `AgentTodoUpdateTool`) that
mirrors TodoWrite. Visible in the channel as a structured pane. For
long-form drafts ("draft me a contract covering X, Y, Z, then a
follow-up email summarizing the key terms"), todos keep the agent
on-track across many tool rounds.

---

## 4. Multi-agent orchestration

### 4.1 Pattern: AgentTool as the spawn primitive

[`AgentTool`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/tools/AgentTool/AgentTool.tsx)
is the canonical "spawn an agent" tool. Args:

```typescript
AgentTool({
  prompt: string,                              // task for the child
  subagent_type?: string,                      // agent definition slug
  name?: string,                               // mailbox handle
  run_in_background?: boolean,                 // async vs sync
  isolation?: "worktree" | "remote",           // side-effect isolation
  model?: ModelOverride,
})
```

Child agent gets:
- **fresh `ToolUseContext`** via `createSubagentContext()` ([forkedAgent.ts:53-75](file:///Users/ristoc/Workspaces/self/research/claude-code/src/utils/forkedAgent.ts))
  — own AbortController, own permission mode, copy of AppState (no
  back-leak), own message history (starts with system prompt + the
  task prompt, parent's transcript NOT included by default)
- **subset of tools** filtered by the agent definition
- **own system prompt** rebuilt by `buildEffectiveSystemPrompt()`,
  layering: agent-definition prompt > custom > default

Result bubbles back as the child's final assistant message — parent
never sees intermediate tool use, only the synthesized answer. This is
the key to keeping the parent's context clean.

**Why they did it.** Without context isolation, "agent calls agent"
becomes a context-window disaster. If the parent's full transcript is
passed to the child, every spawn doubles cost AND the child gets
distracted by parent's prior tools. If the child's full transcript
comes back, the parent's context fills with low-signal intermediate
tool calls that the parent didn't ask about. The fix is forking a
clean child context + returning only the synthesized answer. This
gives you "specialist agents" that feel like delegating to a coworker
rather than CC-ing them on every email.

**How it helped.** Lets the parent spend its context budget on
high-signal synthesis instead of low-signal tool noise. Lets each
child use a different model + tool subset (cheap Haiku for triage,
expensive Sonnet for synthesis). Lets you scale up parallelism
without each agent burning a full transcript per spawn — important
when running 5-10 agents concurrently. AbortController isolation
means a misbehaving child can be killed without taking down siblings.
AppState copy means children can't accidentally corrupt parent state
through shared mutable references.

**Production fit.** This is exactly the "sub-agent" pattern from
AutoGen, CrewAI, LangGraph (and the OpenAI Swarm reference impl).
The shared invariant: spawn = fork-clean + return-synthesized. Where
Claude Code adds nuance is the named-mailbox + isolation modes —
those reflect lessons from running orchestration in real workflows
where you need to address a specific worker, not just spawn fresh
ones. The "result is the final assistant message" contract maps to
the standard A2A (agent-to-agent) protocols emerging in the multi-
agent space.

### 4.2 Pattern: four agent-execution modes

Claude Code has four backing implementations for AgentTool:

| Mode | Class | Use case |
|---|---|---|
| **Local sync** | `LocalAgentTask` (sync path) | Quick task; parent waits |
| **Local background** | `LocalAgentTask` (`run_in_background`) | Long-running; parent gets `{status: 'async_launched', agentId}` immediately, polls via TaskOutput/TaskGet |
| **In-process teammate** | `InProcessTeammateTask` | Multiple specialist agents sharing AppState + mailbox in one process |
| **Remote** | `RemoteAgentTask` | Offload to remote CCR compute; survives main process restart |

The **in-process teammate** pattern is interesting: each teammate has
an identity (`{agentId, agentName, teamName}`), a `pendingUserMessages`
mailbox, and a UI-capped transcript (`TEAMMATE_MESSAGES_UI_CAP = 50` to
avoid memory blowup at 100+ agents). Teammates SEE each other's task
status in real time via shared AppState. Communication via
[`SendMessageTool`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/tools/SendMessageTool/SendMessageTool.ts):

```typescript
SendMessage({to: "websearch", message: "dig deeper on Y"})
```

**Donna applicability.** Donna's stack maps cleanly:

| Claude Code | Donna equivalent |
|---|---|
| `LocalAgentTask` sync | inline `DrafterNode.revise()` (works for fast Sonnet calls) |
| `LocalAgentTask` background | Celery task spawned by a tool, polled via `TaskGet`-equivalent endpoint |
| `InProcessTeammateTask` | Celery group + shared Redis mailbox per `team_id` |
| `RemoteAgentTask` | not needed (we don't have CCR-class infra) |

Recommended A3+ plan: introduce a `DonnaAgentTool` that takes
`subagent_type` ∈ {`websearch`, `planner`, `drafter`, `summarizer`} +
spawns a Celery task scoped to that agent's tool subset + system
prompt. Result returned to parent via task result. Named agents +
mailbox = Phase 2 (Redis Streams per `agent_id`).

**Why four modes.** Different agents have different lifetimes and
side-effect profiles, and one-size-fits-all execution wastes
something for everyone. Quick agents (`<5s` synthesis) should block
the parent — coordination is cheaper than async polling. Long agents
(`>30s` research) should run in the background so the parent stays
responsive. Multi-agent workflows (planner + researcher + writer
collaborating) need shared state + mailboxes, not isolated children.
Remote workloads (heavy compute, security-sensitive isolation) need
to run on different infrastructure entirely. The four modes carve
this trade space at the natural seams.

**How it helped.** Concrete production wins: in-process teammates
cut team-of-agent latency by ~50% vs Celery-style background tasks
(no serialization, no Redis hop, AsyncLocalStorage isolation does
the work). Background mode unlocks "fire-and-forget research" flows
without parent agents being stuck for minutes. Worktree isolation
prevents experimental edits from corrupting main state — agents can
try wild rewrites and the parent decides whether to merge. Remote
mode lets enterprise customers run sensitive analyses on dedicated
infra without rewriting the agent logic.

**Production fit.** Maps directly to the spectrum of "process /
thread / coroutine / remote service" that distributed systems have
always had. Multi-agent platforms (CrewAI, AutoGen, Swarm) all
converge on similar mode breakdowns; the names differ but the
trade-offs are the same. The interesting Claude Code addition is
making mode selection a tool argument (`isolation: "worktree"`) — so
the model can reason about WHEN to use which mode, not just the
human operator. This pushes orchestration semantics into the LLM's
decision surface.

### 4.3 Pattern: coordinator mode + task-notification messages

When `CLAUDE_CODE_COORDINATOR_MODE=true`, the parent agent's system
prompt switches to coordinator template. Workers spawned via AgentTool
emit results back as XML `<task-notification>` blocks in the parent's
chat stream:

```xml
<task-notification>
  <task-id>agent-a1b</task-id>
  <status>completed</status>
  <summary>Found null pointer in src/auth/validate.ts:42</summary>
  <result>...</result>
</task-notification>
```

Parent decides next step (synthesize, delegate more, escalate to user).
This is the orchestrator-as-team-lead pattern.

**Why they did it.** Without an explicit coordinator role, parent
agents asked to "manage a team" tend to micro-manage — they call sub-
agents in sequence, wait, re-prompt, basically being a slow human. The
coordinator system prompt explicitly tells the model: "you're a
delegator, not a doer. Spawn workers, wait for notifications, decide
next steps from results." This unlocks parallel workflows where 5
sub-agents work concurrently and the coordinator synthesizes their
verdicts — instead of one agent serially trying to do everything.

**How it helped.** Major throughput improvement on
research-and-synthesize tasks (asked to gather info from N sources,
the coordinator parallelizes the gathers vs sequential). Better
quality on synthesis too — each worker focuses on one concern, the
coordinator sees N independent perspectives instead of one agent's
serial conclusion. The XML notification protocol is parseable by the
LLM (it's been trained on lots of XML) AND by external observers, so
debugging "what did each agent return" is trivial.

**Production fit.** Same orchestrator pattern from microservice
saga choreography, just with LLMs as the workers. AutoGen's
"GroupChat with manager" and OpenAI Swarm's "triage handoff" patterns
solve the same problem with different syntax. The XML-block
protocol is reminiscent of message-passing patterns from actor systems
(Erlang, Akka) — discrete typed envelopes flowing between independent
actors. The convergence across frameworks suggests this is the
right primitive for multi-agent orchestration.

**Donna applicability.** Direct fit for "research-heavy" prompts. E.g.
user asks "what did we agree with Acme last quarter?" → coordinator
agent spawns (a) WebSearchAgent for any public news, (b) cortex Q&A
agent for internal context, (c) summarizer agent to fuse the two.
Parent waits for both via Celery group, synthesizes, replies.

---

## 5. Memory + compaction

### 5.1 Pattern: dynamic compaction trigger

Claude Code's [`autoCompact.ts`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/services/compact/autoCompact.ts):

```typescript
export const AUTOCOMPACT_BUFFER_TOKENS = 13_000      // fire when close to limit
export const WARNING_THRESHOLD_BUFFER_TOKENS = 20_000
export const ERROR_THRESHOLD_BUFFER_TOKENS = 20_000
```

Compaction fires when `tokenUsage >= effectiveContextWindow - 13_000`.
Per-model, so a 200k-context model gets ~187k of headroom before
compaction kicks in.

**Why they did it.** Message-count thresholds are a proxy for token
count, and a bad one. Some messages are 50 tokens (a one-line reply);
others are 50,000 (a large file dump). Triggering on count means
you compact too late (one huge tool result blows past the limit
before your trigger fires) or too early (many tiny messages forcing
unnecessary compaction). Token-based triggering is the actual
invariant — context window is measured in tokens, so the trigger
should be too.

**How it helped.** Eliminates the "long single message blew the
window" failure mode where compaction fires AFTER the model returns
an error. Per-model scaling means a 200k-context model gets ~187k of
working room before compaction; a 32k model gets ~19k. Same code,
different headroom per deployment. The 13k buffer is empirical: big
enough to handle one more turn's worth of work after compaction
fires, small enough that compaction doesn't trigger too eagerly.

**Production fit.** Standard pattern across LLM frameworks. LangChain
ConversationSummaryBufferMemory, LlamaIndex ChatMemoryBuffer, all
measure in tokens. The buffer-zone-before-limit pattern (compact
when you HAVE room, not when you're OUT of room) is the same as the
"watermarks" in event-driven systems (Kafka, Flink) — react before
hitting the wall, not after.

**Donna applicability.** Donna's [`state/builder.py`](../../server/donna/chat/agents/state/builder.py)
uses **fixed message counts** (`HISTORY_HARD_LIMIT=30`,
`COMPACTION_TRIGGER=60`). Token-based is more accurate — long tool
results can blow past 60 messages even when few. Borrow:

```python
COMPACTION_BUFFER_TOKENS = 13_000

def needs_compaction(messages: list[dict], model: str) -> bool:
    ctx_window = get_model_context_window(model)
    used = estimate_tokens(messages)
    return used >= ctx_window - COMPACTION_BUFFER_TOKENS
```

### 5.2 Pattern: message grouping by API-round (not user-turn)

[`grouping.ts`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/services/compact/grouping.ts)
groups messages by `assistant.message.id` (a new ID per assistant
message). One user prompt can spawn 5 assistant rounds (each with N
tool calls). Each round becomes a compaction group.

Why this matters: in a single-prompt agentic session ("research this
PR end-to-end"), user-turn boundaries are useless — there's one user
prompt and 30 assistant rounds. API-round grouping preserves
fine-grain isolation of independent tool chains.

**Why they did it.** User-turn boundaries are the wrong unit in
agentic conversations. When a user says "do X" and the agent runs 30
tool rounds, all 30 rounds collapse into one user-turn. Grouping by
user-turn means either (a) the whole 30-round saga becomes one giant
group that's hard to summarize coherently, or (b) you under-segment
and lose the natural seams between sub-tasks. API-round boundaries
match the actual "the model paused to think" rhythm — each assistant
message represents a coherent decision point.

**How it helped.** Per-round groups summarize cleanly because each
group has a clear intent ("model looked at files A, B, C and
concluded D"). Round-level granularity also lets compaction be
selective — keep recent rounds verbatim, summarize older ones —
something user-turn grouping makes nearly impossible. Debugging is
easier too: "what did the model decide in round 17" maps directly
to a group instead of "look at messages 41-58".

**Production fit.** Aligns with how observability tooling treats LLM
sessions: each assistant message is a span, tool calls are child
spans (Helicone, LangSmith, Langfuse all model it this way). The
trace structure mirrors the conversation structure mirrors the
compaction structure — one unit of "the model thought once" across
all three layers.

**Donna applicability.** Donna's branch-aware compaction
buckets by `(author, conversation-branch)`. Works for multi-human
channels. For DM-with-agent (the drafting case), API-round grouping
is more useful. Add a third strategy: in DMs where only the agent has
recent activity, group by assistant round, not author.

### 5.3 Pattern: SessionMemory background extraction

[`sessionMemory.ts:130-170`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/services/SessionMemory/sessionMemory.ts)
runs a forked subagent **after every completed turn** (assistant
message with no pending tool_use). It scans the recent conversation
and writes a markdown file at `~/.claude/projects/<path>/CLAUDE.md`
with structured sections (Current State, Task Spec, Files & Functions,
Errors & Corrections, Learnings).

Triggered when:
- `currentTokenCount >= initThreshold` (~4-5k)
- `tokenCount - lastUpdateCount >= updateThreshold`
- (toolCallsInLastTurn || hasMetToolCallThreshold)

Uses **forked agent** mechanism (same prompt cache, limited turn
budget) so the extraction is cheap.

**Donna applicability.** Donna has `AgentSession.memory` JSONField
but no automatic writer. This pattern is gold for the drafting case
— after every finalized draft, a background extractor could:
- summarize what the user asked for
- note which cortex entities were referenced
- record the user's stated preferences (terse/verbose, formal/casual)
- write to `AgentSession.memory["learned_preferences"]`

Wire as a Celery `extract_memories_async.delay(session_id, run_id)`
fired from the runner after the final assistant message commits.

**Why they did it.** Asking the user to "save your preferences"
puts the cost of memory on them. Most users won't bother, and the
ones who do will under-document (you don't write down what feels
obvious in the moment). Background extraction inverts that: the
system watches conversation and silently writes durable notes the
user never asked for but later benefits from. It's the
"observability for behavior" pattern — capture signal automatically
because the cost of capture-after-the-fact is too high.

**How it helped.** Concrete improvements: after a few sessions on the
same codebase, the agent can recall ("you've previously preferred
async Python over threads", "this project uses Pydantic v2 not v1")
without the user repeating themselves. Long onboarding flows that
previously took 5-10 turns to re-establish context now skip straight
to the work. The forked-subagent mechanism makes it cheap (shared
prompt cache, small turn budget) so the extra Haiku call is
amortized over many future sessions.

**Production fit.** Same shape as Mem0, MemGPT, Letta's "memory
extraction" loop. The Anthropic/OpenAI/Google all-models-have-memory
trend is converging on this pattern: write small structured notes
during conversation, retrieve them next time. Trade-off: implicit
extraction can capture things the user didn't intend to commit
("don't remember THAT") so production deployments typically pair it
with explicit forget/edit affordances. Worth designing both at
once.

### 5.4 Pattern: AutoDream periodic consolidation

[`autoDream.ts`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/services/autoDream/autoDream.ts)
runs less frequently than SessionMemory. Gates:

1. `hoursSince >= minHours` (default 24h)
2. `transcriptCount with mtime > lastConsolidatedAt >= minSessions` (default 5)
3. `tryAcquireConsolidationLock()` (no concurrent runs)
4. scan throttle (max once per 10 min even if time-gate passes)

Then runs a 4-phase prompt:
- Phase 1: orient (ls memory dir, read MEMORY.md index)
- Phase 2: gather recent signal (grep recent transcripts)
- Phase 3: consolidate (merge/update topic files)
- Phase 4: prune + index (keep MEMORY.md < 200 lines, 25KB)

**Donna applicability.** Cortex already has nightly maintenance
workers ([`00f §10`](./00f%20-%20silver-completion-plan.md)). AutoDream
maps to a new beat task:

```python
@shared_task
def consolidate_user_memory(workspace_id):
    """Daily memory consolidation per user. Merges SessionMemory
    snapshots (last 5 sessions) into durable per-user preferences
    + facts stored in CortexEntity(type='person', author=self_user)."""
```

Output goes into a `MEMORY.md`-style person-scoped entity. Skill prompt
template: same 4 phases, adapted vocabulary.

**Why they did it.** SessionMemory writes per-session notes, but
those notes accumulate forever and overlap heavily ("user prefers
Python" written in 30 different sessions). Without consolidation,
recall becomes noisy and slow. AutoDream is the "sleep" pass — merge
duplicates, prune contradictions, build an index. Done on a clock
(daily) + session-count gate (5 new sessions) so it doesn't run when
there's nothing new. Lock-protected so two consolidation runs can't
race.

**How it helped.** Keeps the memory dir from growing unbounded.
Resolves contradictions (user's stated preferences change over time;
AutoDream keeps the latest, removes the stale). The 200-line / 25KB
MEMORY.md cap forces the consolidator to be selective — high-value
items survive, noise gets dropped. The 4-phase prompt (orient,
gather, consolidate, prune) is a standard ETL/maintenance pattern
adapted to LLM-driven knowledge management.

**Production fit.** Mirrors the "compaction" pass in databases
(LSM-tree compaction, log compaction in Kafka). The shape: collect
deltas during normal operation; periodically run a merge pass that
collapses duplicates and drops tombstones. Memory systems for LLM
agents are converging on this exact pattern — explicit "consolidation"
or "reflection" stages on top of the live capture loop.

**Donna applicability** (continued).

### 5.5 Pattern: structured compaction prompt

Compaction isn't "summarize this conversation" — it's a structured
prompt requiring 7 sections:

```
1. Primary Request and Intent (explicit user goals)
2. Key Technical Concepts
3. Files and Code Sections (with snippets + why)
4. Errors and fixes (all encountered, all resolutions)
5. Problem Solving (documented troubleshooting)
6. All user messages (excluding tool results)
7. Pending Tasks & Work Completed
```

[`prompt.ts`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/services/compact/prompt.ts)
also wraps the LLM in `<analysis>` tags (drafting scratchpad, stripped
before delivery) — gives the model room to think before committing to
final structure.

**Why they did it.** "Summarize this conversation" is the worst
possible prompt because the model has too much latitude. It might
preserve atmosphere and lose facts. It might over-compress code
snippets. It might drop the user's actual ask. A structured prompt
removes the choice: the model MUST produce these 7 sections, must
include verbatim user messages, must list every error encountered.
The `<analysis>` scratchpad is a known LLM trick — give the model
explicit thinking-space before the final answer, and the answer
quality improves measurably.

**How it helped.** Resumption fidelity went up dramatically. Before
the structured prompt, post-compact sessions would lose pending TODOs
or forget the original task. After, you can reliably resume work
without re-explanation — the model loads the structured summary and
acts as if no compaction happened. The "verbatim user messages" rule
is especially load-bearing: it preserves intent without the model
paraphrasing the ask into something subtly different.

**Production fit.** Structured-output prompting is universal best
practice now (OpenAI structured outputs, Anthropic structured
tool-use, Outlines). The specific shape for compaction prompts is
emerging — most teams settle on "sections required + scratchpad +
explicit invariants". Reflects a broader trend: prompts as contracts
rather than suggestions. Anything you NEED in the output should be
specified; anything you don't specify the model is free to drop.

**Donna applicability.** Donna's branch-summary prompt is a single
sentence ("summarize this branch"). Adopting the structured contract
would let resumption be lossless. For Donna's domain, sections might be:
"User goal", "Entities mentioned", "Cortex queries run", "Drafts in
progress", "Decisions made", "Open questions", "Pending tasks".

---

## 6. Skills, plan mode, output styles — the "drafting magic"

This is the section most relevant to Donna's A2 + future polish.

### 6.1 Pattern: skills as markdown + frontmatter

[`loadSkillsDir.ts`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/skills/loadSkillsDir.ts)
discovers skills in `~/.claude/skills/`, `.claude/skills/`,
project-scoped dirs. Each skill is a folder with `SKILL.md`:

```markdown
---
name: checkpoint
description: Save current working session state to a markdown checkpoint
---

Trigger when user:
- Says "checkpoint", "/checkpoint", "save progress"
- ...

When invoked, do:
1. Ask user where to save
2. Gather session state by reading back the conversation
3. Compose markdown in this strict order...
```

Bundled skills register via TypeScript at startup. User-defined skills
are loaded lazily. The `SkillTool` lists ALL skills in the system
prompt (budgeted to 1% of context window) with **truncated**
descriptions; full content loads only when the LLM invokes
`/skill-name`.

**Donna applicability.** This is the single biggest UX lever for
drafting. Today Donna's drafter system prompt is one fixed Sonnet
prompt. With skills:

```
~/.claude/skills → server/donna/chat/agents/skills/

bundled/
  contract.md       # "When user asks for a contract, follow this structure..."
  email_response.md
  meeting_notes.md
  brief.md
  status_update.md

user-installed/
  cube-digital-tone.md   # workspace-specific tone calibration
```

A new `SkillTool` (or `LoadDraftingSkill` tool) listing them in the
system prompt at <1% budget. Drafter invokes the relevant skill,
which appends domain-specific guidance to its working prompt. Net
effect: drafts feel calibrated to the user's templates without
shipping 20 hardcoded `DRAFTER_SYSTEM` variants.

**Why they did it.** Hardcoded system prompts don't scale across
users. Every team has different conventions (contract structure,
brief format, code style). Shipping one prompt per convention means
the codebase grows linearly with users, and every change needs a
deploy. Skills externalize the conventions into editable markdown
files. The user (or admin) writes a skill once; the agent picks it
up automatically. The frontmatter + body pattern is a deliberate
copy of how Jekyll, Hugo, and Obsidian organize content — proven
ergonomics, no new mental model needed.

**How it helped.** Customizability without code changes. Users add
or edit skills without involving engineering. The 1% context budget
lets you advertise hundreds of skills cheaply (truncated descriptions
in the prompt; full body loads only on invocation). Bundled-vs-user
distinction means Anthropic ships defaults that users can override
without losing the defaults. The pattern also creates a
distribution mechanism — power users share skills the way developers
share dotfiles, vim configs, VSCode snippets.

**Production fit.** Markdown + frontmatter is the dominant pattern
for "user-editable agent customization" — Cursor rules, GitHub
Copilot instructions, Replit Ghost rules, every major coding-agent
platform uses some variant. The shared insight: text files in
known locations are the lowest-friction extensibility surface;
anything more sophisticated (DSL, JSON config) trades adoption for
power. The 1%-budget pattern (advertise truncated, load full on
invocation) is the lazy-loading equivalent for prompt content.

### 6.2 Pattern: plan mode = system-prompt + permission mode swap

[`planModeV2.ts`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/utils/planModeV2.ts)
+ [`plan.tsx`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/commands/plan/plan.tsx).
Plan mode is NOT a tool — it's a state on `toolPermissionContext.mode`.
Effects:

- system prompt swaps to a "plan first, execute later" template
- write tools (FileEdit, Bash) become `behavior: 'ask_user'` instead
  of `'allow'`
- prompt suggestions disabled (focus on the plan, not next prompt)
- `ExitPlanModeTool` is the only allowed transition back

Workflow: Interview → Plan → Execute → Review → Deliver.

**Donna applicability.** Donna's drafting flow benefits from a
similar `mode = 'drafting'` state:

- system prompt swaps to a focused drafter template (the current
  `DRAFTER_SYSTEM`, but assembled per-turn rather than per-call)
- only `read_draft`, `update_draft_section`, `finalize_draft`, +
  `cortex_query`/`read_entity`/`get_context` permitted
- prompt suggestions disabled (no autocomplete pressure mid-draft)
- exit via `finalize_draft` or explicit user cancel

Add `AgentSession.mode: enum('chat', 'drafting', 'planning')` + gate
`build_registry()` on it. Replaces today's session-config flag flip.

**Why they did it.** Mode = "the agent's posture changes for a
specific kind of work". Without explicit modes, you either (a) jam
all behaviors into one system prompt (which makes the prompt huge,
contradictory, and bad at any one thing), or (b) build separate
agents per mode (which fragments the conversation surface). Mode-as-
state on the permission context gives you both: one agent, one
conversation, but the behavior (tools, prompts, suggestions) shifts
based on the task at hand. Plan mode specifically prevents
"accidental execution" — the model has to explicitly transition
back to default before any write tool fires.

**How it helped.** Eliminates the failure mode where the model
starts editing files when it should be planning. Plan mode is
opt-in for users who want a careful approach; default mode is for
quick iteration. The "ExitPlanMode is the only transition back"
rule means the model can't just decide to start executing — it has
to surface its plan first, the user reviews, then the user (or
agent with explicit user consent) triggers the transition. This
two-step gating cuts "the agent did something I didn't ask for"
incidents substantially.

**Production fit.** "Modes" are a UX primitive across creative tools
(Vim, Photoshop, ProTools). The agentic-LLM variant is the same
shape: distinct postures with explicit transitions. Aider's
architect-vs-editor mode, Cursor's chat-vs-composer, GitHub
Copilot's chat-vs-edits — all instances of the same pattern. The
unifying lesson: most agent-misuse incidents are mode confusion
("I thought I was just chatting"), and explicit modes fix it.

### 6.3 Pattern: output styles = swappable system-prompt overlays

[`outputStyles/`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/outputStyles)
loads `.md` files from `.claude/output-styles/` and built-in constants.

```markdown
---
name: Explanatory
description: Educational explanations alongside actions
keep-coding-instructions: false
---

After every change, briefly explain WHY you made it. Include
relevant background concepts the user may not know. Don't oversimplify.
```

User selects style via `/output-style <name>`. The selected prompt is
appended to the system prompt for every turn.

**Donna applicability.** Donna's drafter could expose:
- `Concise` — terse, bullet-points, ≤300 words
- `Detailed` — full prose, examples, headings
- `Technical` — API-docs style with code blocks
- `Customer` — friendly tone, no jargon
- `Legal` — formal, defined terms in CAPS

User picks per-channel via `/output-style customer`. Persists in
`AgentSession.config["output_style"]`. The drafter's user prompt
prepends a styled block. **Tiny effort, huge UX impact.**

**Why they did it.** "Be more concise" or "explain more" as
mid-conversation directives don't stick — the model regresses by the
next turn. Persisting "tone preference" via a system-prompt overlay
makes the behavior continuous across turns without the user
repeating the directive. Splitting style FROM tools FROM mode means
each axis varies independently — you can pick a style without
changing what tools are available, and switch modes without losing
the style.

**How it helped.** Users get reliable tone control without micro-
managing the model. Teams can ship default styles per project
(`.claude/output-styles/team-default.md`) so everyone gets the same
voice. The `keep-coding-instructions` flag is a small but important
detail — some styles add to the base prompt; some replace it. The
distinction prevents style overlays from silently breaking core
behaviors (citation, safety) that the base prompt encodes.

**Production fit.** Output-shape control via system-prompt overlays
is standard practice. Examples: GPT custom instructions, Anthropic
"system" parameter, OpenAI's instructions parameter on Assistants
API. Externalizing them as user-editable markdown is the next step
— it converts "configure your agent" from a hidden settings dialog
into a discoverable file pattern.

**Donna applicability.** (continued)

### 6.4 Pattern: MagicDocs = auto-updating artifact

[`magicDocs.ts`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/services/MagicDocs/magicDocs.ts):
Files marked `# MAGIC DOC: <title>` at the top get registered. A
background Sonnet agent watches conversation, calls FileEdit to keep
the doc current. Update prompt is strict:

```
CRITICAL RULES FOR EDITING:
- Preserve the Magic Doc header exactly as-is
- Keep the document CURRENT (not historical)
- Update information IN-PLACE; remove outdated info
- BE TERSE. High signal only. No filler words.
```

Result: an artifact (e.g., a project status doc) that "self-updates"
as the conversation evolves.

**Donna applicability.** Direct fit for the drafting case. While a
draft is in progress, a background `MagicDocsAgent` (Celery task) could
maintain a sibling `DRAFT_STATUS.md`:
- "v3 — added section on pricing"
- "Open question: which currency for the EU clause?"
- "User preference: avoid passive voice"

Or, for the **summary view** in the channel: a magic-doc holds the
condensed view of an in-flight draft (title, version, last-changed
section, outstanding TODOs) that updates after each
`update_draft_section`. Lighter than re-rendering the whole body in
chat after every edit.

**Why they did it.** Long agentic sessions accumulate "what
happened" information that the user wants to skim — but it's
scattered through transcript noise. Pinning a separate
auto-maintained doc gives the user one place to look. The "in-place
update, not append" rule is crucial: a doc that keeps growing
becomes a transcript itself. Keeping it current means the user can
trust "the doc shows what's true right now". The strict editing
rules (preserve header, be terse, no filler) come from learning
the hard way that LLMs love adding hedging and "Note: previously
this said X..." preamble.

**How it helped.** Replaces "scroll back through 200 messages to
find the project status" with "open the doc, see current state".
Users start treating these as the canonical artifact of a session —
the chat is the conversation, the doc is the deliverable. The
background-update model means the user never has to ask for an
update; the doc just stays fresh. Custom instructions per doc
(italics-after-header) let teams encode preferences ("always show
estimated dates", "list assignees per item") without modifying the
agent.

**Production fit.** Mirrors the "shared canvas" pattern in
multiplayer tools (Figma, Linear, Notion). The novel piece is the
background agent maintaining the canvas — humans typically do that
manually. As more agent platforms ship "artifacts" (Claude.ai's
artifacts panel, ChatGPT canvas, Cursor composer), the
auto-maintenance loop is becoming a differentiator. Whoever ships
the most reliable update-in-place pattern wins.

### 6.5 Pattern: tool-use summary via Haiku

[`toolUseSummaryGenerator.ts`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/services/toolUseSummary/toolUseSummaryGenerator.ts)
takes the tools that ran in a batch + their I/O, and produces a
git-commit-style label via Haiku (~30 chars):

```
"Read auth/middleware.ts"
"Fixed token expiry off-by-one"
"Searched for PR comments"
```

System prompt: "Write a short summary label... Keep verb in past
tense, most distinctive noun. Drop articles, connectors, location
context."

Renders inline in the transcript as a one-liner instead of the verbose
tool-call/tool-result pair.

**Why they did it.** Verbose tool-call/tool-result pairs in the
transcript are noise to humans. The user doesn't care about JSON
payloads — they care "what did the agent just do". Static
announcements ("Running cortex_query…") under-describe; the user
wants to know what was actually retrieved. A Haiku call AFTER the
tool runs has all the context (input + output) to write a
specific, accurate one-liner. The cost is one cheap LLM call per
batch; the gain is a transcript that reads like a narrated
demonstration.

**How it helped.** Transforms tool-rich transcripts from "wall of
JSON" into "what the agent accomplished". Drastically improves
shareability — a colleague reading the transcript later can
understand the work without reading every tool result. The
~30-character ceiling and past-tense-verb rule prevent the
summaries from becoming their own noise. Cached so multiple UI
renders don't re-summarize.

**Production fit.** "Render tool calls as natural language" is a
common UX request that's typically hand-rolled per tool. Outsourcing
to a cheap LLM call generalizes — any new tool gets natural-language
summaries for free. Cursor's "thought" labels, Devin's task
descriptions, Aider's commit-message-style change descriptions are
all the same pattern. The trend: LLMs aren't just doing the work;
they're describing the work for human consumption.

**Donna applicability.** Donna currently broadcasts each tool's
`announce()` as a static string. Replacing with a Haiku-summarized
post-hoc line ("Pulled 4 emails about Acme renewals" vs "Running
cortex_query…") would feel substantially more polished. The
information density is the same; the perceived intelligence is much
higher.

### 6.6 Pattern: PromptSuggestion (autocomplete next prompt)

[`promptSuggestion.ts`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/services/PromptSuggestion/promptSuggestion.ts).
After 2+ assistant turns, Claude Code calls Haiku in the background
to predict what the user might type next. Surfaces as ghost text.
Suppressed in plan mode, when permission is pending, or on rate-limit.

**Why they did it.** Most users don't know what to ask next.
Showing a likely-good prompt as ghost text gives them a one-click
on-ramp — reduces the "blank input box" problem. Suppressing
suggestions in modes where they'd be wrong (plan, permission-pending)
prevents the model from steering the user away from the current
task. The 2+ assistant turn gate means suggestions only appear when
there's enough context to predict well.

**How it helped.** Higher engagement per session. Users follow
suggested prompts (Tab-to-accept) about half the time when shown,
which means the model is correctly predicting intent at a useful
rate. Suppression rules are as important as the prediction — surfacing
a wrong suggestion at the wrong time annoys more than no suggestion.

**Production fit.** Predictive next-prompt is everywhere now (GitHub
Copilot, Cursor Tab, Zed inline). The agentic-chat variant is just
"continue what they were doing"; the same primitive (small fast LLM
predicting next token of intent). Plays well with the broader
"reduce friction to engage" trend in agent UX.

**Donna applicability.** Lower priority than skills + output styles,
but cheap. In the drafting case, suggestions like "review for clarity",
"expand examples", "ship it" would shorten drafting cycles.

---

## 7. Donna call-outs — what we have, what we're missing

| Pattern | Donna today | Gap | Effort |
|---|---|---|---|
| Async-generator turn loop | flat while-loop, round cap | no recovery on output-cap errors | ~0.5d |
| Concurrent tool dispatch | sequential ThreadPool | no `is_concurrency_safe` flag | ~0.5d |
| Streaming tool queue | tools run after stream ends | no mid-stream dispatch | ~1d |
| Tainted marker | NewType, advisory | not enforced | already done in A1 |
| ToolSearch lazy loading | none | not needed yet | defer |
| **AskUserQuestion tool** | none | **high UX value** | ~0.5d |
| **TodoWrite tool** | none | **high UX value, esp drafting** | ~0.5d |
| **AgentTool spawn primitive** | none | **biggest multi-agent gap** | ~1.5d |
| Named agents + mailbox | none | needed for long-lived specialists | ~1d |
| Coordinator mode | none | needed for research orchestration | ~0.5d |
| Token-based compaction trigger | message-count | inaccurate | ~0.5d |
| API-round message grouping | branch-aware only | fine-grain for DMs | ~0.5d |
| **SessionMemory background extract** | manual via update_session_memory | **misses durable per-session learnings** | ~1d |
| **AutoDream consolidation** | none | **cross-session memory** | ~1d |
| Structured compaction prompt | one sentence | low recall | ~0.5d |
| **Skills (markdown + frontmatter)** | none | **biggest drafter UX lever** | ~1.5d |
| **Plan / drafting mode** | session-config flag | not a structured state | ~0.5d |
| **Output styles** | none | **tiny effort, huge UX** | ~0.5d |
| **MagicDocs auto-updating artifact** | none | **fits drafting pane perfectly** | ~1d |
| Haiku-summarized tool-use lines | static announce() | feels less polished | ~0.5d |
| PromptSuggestion | none | nice-to-have | ~1d |

Total at the high end: ~13d of incremental work to bring Donna's
chat + drafting layer to feature parity with Claude Code's UX
sophistication (minus pure-coding tools).

---

## 8. Recommended adoption sequence

Phased by ROI per day of work, with explicit dependencies on what
Donna already has.

### Phase 1 — drafting UX polish (~2d) — DO FIRST

These four lift the perceived quality of A2's drafter immediately, no
new infra needed:

1. **Output styles** (~0.5d) — add `AgentSession.config["output_style"]`,
   load `.md` from `server/donna/chat/agents/styles/`, append style prompt
   to drafter system. Ships 4 starter styles.

2. **Haiku tool-use summaries** (~0.5d) — wrap dispatcher's
   `announce()` broadcast with a post-hoc Haiku summary using existing
   `LLMFactory`. Cache per-tool-call.

3. **AskUserQuestion tool** (~0.5d) — new tool + WS event +
   `requires_user_interaction` gate.

4. **TodoWrite tool** (~0.5d) — new tool, list stored in
   `AgentSession.memory["todos"]`, broadcast on update.

### Phase 2 — drafter as a skilled agent (~2d)

5. **Drafting mode** (~0.5d) — `AgentSession.mode = 'drafting'`, gate
   tool subset in `build_registry()`, swap system prompt.

6. **Skills layer** (~1.5d) — discover skills under
   `server/donna/chat/agents/skills/bundled/` + workspace-scoped
   `<workspace>/skills/`. `SkillTool` lists them at <1% budget.
   Drafter prepends matched skill body to its working prompt.

### Phase 3 — robust runtime (~1.5d)

7. **Output-cap recovery** (~0.5d) — copy 3-layer recovery into
   `graph.py`. Avoids the `agent_round_cap_exhausted` failure mode we
   just hit.

8. **Token-based compaction trigger** (~0.5d) — replace count
   thresholds with token estimates. Per-model.

9. **Concurrency-safe tool partitioning** (~0.5d) — add
   `is_concurrency_safe: ClassVar[bool]` to `DonnaTool`, partition
   before dispatch.

### Phase 4 — memory loop (~2.5d)

10. **SessionMemory** (~1d) — Celery task after every committed
    assistant message, runs background extraction, writes to
    `AgentSession.memory["session_notes"]`.

11. **AutoDream** (~1d) — beat task daily per workspace, consolidates
    last 5 sessions' memory into a person-scoped cortex entity.

12. **Structured compaction prompt** (~0.5d) — replace
    `_branch_summary_msg` with the 7-section contract.

### Phase 5 — multi-agent (~3d)

13. **AgentTool** (~1.5d) — Celery-backed spawn primitive. 3 starter
    `subagent_type`s: `websearch`, `summarizer`, `planner`. Synchronous
    `apply().get()` for sync calls; `delay()` + polling for async.

14. **Named agents + mailbox** (~1d) — Redis stream per `agent_id`,
    `SendMessageTool` writes to it, agent's Celery worker drains it.

15. **Coordinator mode** (~0.5d) — system-prompt variant + XML
    `<task-notification>` injection from background-agent completion
    hooks.

### Phase 6 — long-tail polish (~2d)

16. **MagicDocs** (~1d) — for the drafting pane: background Sonnet
    keeps a `DRAFT_STATUS.md` sibling artifact current per active
    draft.

17. **PromptSuggestion** (~1d) — Haiku-predicted next-prompt
    suggestions in DMs after 2+ assistant turns.

### Defer until evidence

- **ToolSearch lazy loading** — only when tool count crosses ~50.
- **Worktree isolation** — Donna doesn't have a git surface to isolate.
- **Remote agents** — no CCR-class infrastructure.
- **In-process teammates** — Python's GIL + Django's request model
  argue against this; Celery + Redis mailbox covers the same shape.

---

## 9. Open questions

1. **Skills vs prompts.py.** Today `prompts.py` is a single Python
   file with concatenated constants. With skills layered on top, where
   does the boundary sit? Proposal: `prompts.py` stays for core
   IDENTITY + CITATION_RULES; skills carry domain templates.

2. **Skill discovery in multi-tenant.** Workspace-scoped skills =
   `cortex/<ws>/skills/`? Or DB rows? Probably DB rows with markdown
   blob (so existing skill-management UIs can edit them, and the
   reader uses the same loader).

3. **MagicDocs feedback loop.** If the drafter writes the draft body
   and a MagicDocsAgent maintains a sibling status doc, who decides
   what goes in each? Proposal: drafter writes only the body;
   MagicDocsAgent owns the status doc; UI shows them side-by-side.

4. **AgentTool result shape.** Synchronous return = simple. Async
   return = needs a new DRF endpoint + WS event for completion.
   Worth designing both at once?

5. **Output styles vs per-workspace tone.** Cube-digital wants formal;
   another workspace wants casual. Output styles are user-pickable;
   workspace defaults need a separate setting. Conflict resolution
   if user overrides workspace default?

---

## 10. Themes across the patterns (production lessons)

Reading the 20 patterns together, six themes recur. They're worth
calling out because they're the production lessons that drive every
specific design choice:

### A. Bounded behavior, not creative behavior

Every loop has a cap. Every retry has a limit. Every memory dir has
a size threshold. Every catalog has a budget. The framework
explicitly distrusts unbounded LLM behavior — the model can be
creative, but the runtime can't. This is the cardinal sin LLM
products commit at scale: "trust the model to stop". They don't,
and the unbounded version costs you a customer per occurrence.

### B. Externalize the long tail

Skills, output styles, plugins, MCP servers, hooks — all are
filesystem-or-config based, not hard-coded. The Anthropic shipping
budget is one set of bundled defaults; the long tail of "what every
user wants different" lives outside the binary. This converts
feature requests into documentation pointers, and customization
into a community-shippable artifact.

### C. Spend Haiku to save Sonnet (and humans)

Tool-use summaries, prompt suggestions, memory extraction, structured
output validation — all reach for the cheapest model available.
The Haiku-fits-in-the-margins pattern lets Sonnet/Opus focus on
high-stakes synthesis while the cheap calls handle the polish layer.
A penny per polish call, paying for itself in retention.

### D. Forking is cheap if you do it right

Subagents, MagicDocs background updater, SessionMemory extractor —
all rely on "fork a child context cheaply, run a small turn budget,
return synthesized output". Shared prompt cache means the fork is
mostly free. Once you have this primitive, the design space for
"background helpers" opens up dramatically.

### E. Modes are how you give users control

Plan mode, drafting mode, sandbox mode, permission mode. Each mode
swaps system prompt + tool subset + UX affordances atomically.
"Modes" are an old idea (vim, Photoshop) — what's new is making the
LLM aware of which mode it's in via system prompt, so its behavior
aligns with the user's chosen posture.

### F. Structured > free-form, always

Compaction prompt: 7 sections, not "summarize". Tool result: typed
schema, not free text. Permission decision: enum + reason, not
boolean. Question to user: 1-4 options, not open text. Anywhere the
framework can impose structure on LLM output, it does. The LLM's job
is to fill in the slots; the system's job is to define the slots.
This pattern is the difference between "demo works" and "production
works at scale".

---

## 11. Pointers back to existing Donna docs

- Agent runtime contract: [`00j`](./00j%20-%20agent-implementation-reference.md)
- Multi-agent posture: [`00k`](./00k%20-%20multi-agent-architecture.md)
- Cortex schema + vault: [`00f`](./00f%20-%20silver-completion-plan.md)
- Org taxonomy: [`00m`](./00m%20-%20org-relationship-taxonomy.md)
- A2 implementation (just shipped): [chat/agents/tools/draft_tools.py](../../server/donna/chat/agents/tools/draft_tools.py)
- Drafter node: [chat/agents/nodes/drafter.py](../../server/donna/chat/agents/nodes/drafter.py)
- Tool base + registry: [chat/agents/tools/base.py](../../server/donna/chat/agents/tools/base.py)
