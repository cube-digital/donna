# 00o — Claude Code architecture reference

> Standalone architectural overview of Claude Code (Anthropic's CLI
> + SDK + MCP agent platform). Reads the codebase at
> `/Users/ristoc/Workspaces/self/research/claude-code` as a system,
> not as a source of patterns to borrow. Companion doc
> [`00n`](./00n%20-%20claude-code-patterns-for-donna.md) maps these
> patterns onto Donna; this one stays inside Claude Code's world.

Date: 2026-06-21. Filtered: coding-specific tool internals (FileEdit,
Bash, LSP) are mentioned by name only — we focus on the framework
that wraps them, not their semantics.

---

## Reading guide

The system has 11 substantial subsystems. Read in this order if you're
new:

1. §1 — system map (the diagram)
2. §2 — entrypoints + boot (how the thing starts)
3. §3 — turn lifecycle (the core loop)
4. §4 — tool framework (the contract every capability follows)
5. §5 — multi-agent (how Claude Code does "agents calling agents")
6. §6 — state + memory (what survives across turns and sessions)
7. §7 — skills, modes, output styles (how user-facing behavior morphs)
8. §8 — hooks + permissions + sandbox (the safety + extensibility layer)
9. §9 — MCP + plugins (the "third-party" extensibility surface)
10. §10 — engineering patterns to notice
11. §11 — file index

Each section is self-contained with file:line refs so you can dive
straight into the code afterward.

---

## 1. System map

```
                   ┌────────────────────────────────┐
                   │   ENTRYPOINTS (§2)             │
                   │                                │
                   │   CLI (TTY/ink)                │
                   │   SDK (programmatic)           │
                   │   MCP server (stdio)           │
                   │   CCR (remote control bridge)  │
                   └─────────────┬──────────────────┘
                                 │
                   ┌─────────────▼──────────────────┐
                   │   BOOT (§2)                    │
                   │                                │
                   │   setup() → bootstrap state    │
                   │   load settings + permissions  │
                   │   discover skills + plugins    │
                   │   parallel: SessionMemory,     │
                   │     PolicyLimits, MCP, Telemetry│
                   │   prefetch GrowthBook, MCP reg │
                   └─────────────┬──────────────────┘
                                 │
                   ┌─────────────▼──────────────────┐
                   │   REPL / PROMPT PIPELINE       │
                   │                                │
                   │   user input                   │
                   │     → parseSlashCommand        │
                   │     → findCommand              │
                   │     → expand prompt-type cmds  │
                   │     → attach files / images    │
                   │     → UserPromptSubmit hooks   │
                   │     → enqueue user message     │
                   └─────────────┬──────────────────┘
                                 │
┌────────────────────────────────▼──────────────────────────────────┐
│  TURN LOOP — QueryEngine.submitMessage → query() (§3)             │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │ async function* query(state) {                           │    │
│  │   for await (msg of callModel(state)) {     ←─┐          │    │
│  │     yield msg                                 │          │    │
│  │     if (msg has tool_use_blocks) {            │          │    │
│  │       streamingToolExecutor.queue(blocks)     │          │    │
│  │       for await (u of executor.results()) {   │          │    │
│  │         yield u.message                       │          │    │
│  │       }                                       │          │    │
│  │       state.messages += [assistant, results]  │          │    │
│  │     }                                         │          │    │
│  │   }                                ──────────→┘ (loop)   │    │
│  │   stop_reason / maxTurns / budget cap → return           │    │
│  │   3-layer recovery on max_output_tokens                  │    │
│  │   Stop hooks: continue=false blocks termination          │    │
│  │ }                                                        │    │
│  └────────────┬──────────────────────────┬──────────────────┘    │
│               │                          │                       │
│               ▼                          ▼                       │
│   ┌──────────────────────┐    ┌─────────────────────────┐       │
│   │  TOOL FRAMEWORK (§4) │    │ HOOKS + PERMS (§8)      │       │
│   │                      │    │                         │       │
│   │  Tool<I,O,P> shape   │    │  PreToolUse / PostToolUse│       │
│   │  validateInput       │    │  Stop / SessionStart    │       │
│   │  checkPermissions    │    │  PermissionRequest      │       │
│   │  call(args,ctx)      │    │  modes: default/plan/   │       │
│   │  isConcurrencySafe   │    │    auto/bypass/dontAsk  │       │
│   │  shouldDefer         │    │  sandbox: net + fs      │       │
│   │  ToolSearch lazy load│    │  policy > user > project│       │
│   └──────────┬───────────┘    └─────────────────────────┘       │
│              │                                                  │
│              ▼                                                  │
│   ┌──────────────────────────────────────────────────┐          │
│   │  EXECUTION TARGETS                               │          │
│   │                                                  │          │
│   │  in-process tools                                │          │
│   │  AgentTool → 4 modes (§5):                       │          │
│   │    - LocalAgentTask (sync / background)          │          │
│   │    - InProcessTeammateTask (mailbox + AppState)  │          │
│   │    - RemoteAgentTask (CCR offload)               │          │
│   │  MCP tools (§9) → mcp__server__tool              │          │
│   │  Plugin tools / hooks (§9)                       │          │
│   └──────────────────────────────────────────────────┘          │
└───────────────────────────────────────────────────────────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                  ▼
  ┌────────────────┐  ┌─────────────────┐  ┌──────────────────┐
  │  STATE + MEM   │  │ SKILLS / MODES  │  │ MCP / PLUGINS    │
  │  (§6)          │  │  (§7)           │  │  (§9)            │
  │                │  │                 │  │                  │
  │ autoCompact    │  │ skills/         │  │ stdio/sse/http/ws│
  │   13k buffer   │  │   SKILL.md +    │  │   transports     │
  │ API-round grp  │  │   frontmatter   │  │ OAuth + cache    │
  │ structured     │  │ plan mode       │  │ deferred tools   │
  │   compact prompt│  │   (perm + sys)  │  │ resources + LRU  │
  │ SessionMemory  │  │ output styles   │  │ plugins/         │
  │   per-turn bg  │  │ MagicDocs       │  │   .claude-plugin │
  │ AutoDream      │  │   (auto-update  │  │   commands/      │
  │   24h, 5 sess  │  │    artifacts)   │  │   agents/        │
  │ session resume │  │ PromptSuggestion│  │   hooks/         │
  └────────────────┘  └─────────────────┘  └──────────────────┘
```

Everything below expands one box.

---

## 2. Entrypoints + boot

### 2.1 Three entrypoints, three subsets

| Entrypoint | File | Subsystems init'd | Permission posture |
|---|---|---|---|
| **CLI (TTY/ink)** | `entrypoints/cli.tsx` | full: tools, hooks, MCP, OAuth, ink UI, settings sync | default mode, prompts allowed |
| **SDK (programmatic)** | `entrypoints/sdk/*` + `entrypoints/agentSdkTypes.ts` | full minus ink; hooks invoked as JS callbacks | mode controlled by caller |
| **MCP server (stdio)** | `entrypoints/mcp.ts` | minimal; only `review` command is MCP-safe | empty context (`getEmptyToolPermissionContext()`) |

The CCR (Remote Control bridge) is layered on the CLI — it can drive a
running session from mobile/web through a daemon. There's a slash-command
allowlist (`REMOTE_SAFE_COMMANDS` ≈ 17 items, `BRIDGE_SAFE_COMMANDS` ≈ 6
items) that gates which commands can be dispatched remotely.

### 2.2 Boot sequence (CLI path)

[`setup.ts`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/setup.ts):

```
main.tsx
  profileCheckpoint() + startMdmRawRead() + startKeychainPrefetch()
  ↓
setup(cwd, permissionMode, ...)
  ├─ Node 18+ check
  ├─ custom session id (if --custom-session-id)
  ├─ terminal backup restore (interactive only)
  ├─ FileChanged hook watcher (sync — watches .claude/hooks.yaml)
  └─ worktree create (if --worktree)
  ↓
parallel non-blocking:
  ├─ initSessionMemory()              [registers stop hook]
  ├─ initContextCollapse()            [feature flag]
  ├─ getCommands(projectRoot)         [async, memoized]
  ├─ loadPluginHooks()
  └─ UDS messaging server             [feature flag]
  ↓
blocking prefetch:
  ├─ GrowthBook init (feature gates)
  ├─ bootstrap API data fetch
  └─ MCP official registry prefetch
  ↓
launchRepl()
```

### 2.3 Bootstrap state singleton

[`bootstrap/state.ts`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/bootstrap/state.ts)
is a frozen singleton holding session id, permission context, cost
counters, cached `CLAUDE.md` for the project. Accessed via memoized
getters — anything that needs "what session am I in" reads from here,
not from React state.

### 2.4 Settings layering

Configuration is layered, highest priority first:

```
policy (managed)      managed deployments / enterprise
  → user             ~/.claude/settings.json
    → project        .claude/settings.json
      → local        .claude/local.json (gitignored)
        → CLI flag   --permissions=... etc
          → command  /command-args
            → session
```

Higher layers can flip `allowManagedHooksOnly` etc to hide lower
layers entirely. `services/policyLimits/` + `services/remoteManagedSettings/`
sync from a remote endpoint every 60 min, fail-open on network errors.

---

## 3. Turn lifecycle

### 3.1 Prompt processing pipeline

User text → message that hits the LLM. Pipeline in
[`utils/processUserInput/processUserInput.ts`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/utils/processUserInput/processUserInput.ts):

```
input text
  ↓
parseSlashCommand(input)              [utils/slashCommandParsing.ts]
  → { commandName, args, isMcp }
  ↓
findCommand(commandName, commands)    [commands.ts:findCommand]
  ↓
branch by command.type:
  ├─ 'prompt'   → expand to text, injected into user message
  ├─ 'local'    → run synchronously, output as system text
  └─ 'local-jsx'→ lazy-load ink component, render in UI
  ↓
createUserMessage() / createCommandInputMessage()
  + attach @file refs, images, pasted content (AgentMention)
  ↓
ultraplan keyword rewriting (if enabled)
  ↓
UserPromptSubmit hooks fire (.claude/hooks.yaml)
  ↓
ProcessUserInputBaseResult {
  messages, shouldQuery, allowedTools?, model?, effort?
}
```

**Key fact:** prompt-type commands (skills, `/plan`, etc.) expand to
text BEFORE the LLM sees them. `/skill-name` becomes `<skill body>` in
the user message; there's no separate "skill turn".

### 3.2 The query() generator

[`query.ts`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/query.ts)
(~1729 LOC) is the recursive heart. Driven by
`QueryEngine.submitMessage()`:

```typescript
async function* query(state) {
  for await (const message of callModel({messages, tools, ...})) {
    yield message                                      // stream out
    if (message.type === 'assistant' && toolUseBlocks) {
      streamingToolExecutor.addTool(block, message)    // queue mid-stream
    }
  }
  // after stream ends:
  for await (const update of streamingToolExecutor.getRemainingResults()) {
    yield update.message                               // tool results
    toolResults.push(update)
  }
  state.messages = [...state.messages, ...assistant, ...toolResults]
  // loop continues: model sees results, decides next move
}
```

### 3.3 Streaming + concurrent dispatch

[`StreamingToolExecutor`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/services/tools/StreamingToolExecutor.ts)
queues each `tool_use` block as it arrives in the assistant token
stream — tools begin executing before the assistant message finishes
streaming. [`toolOrchestration.ts`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/services/tools/toolOrchestration.ts)
partitions by `isConcurrencySafe`:

- read-only tools batch + run in parallel
- mutating tools run serially, with optional `contextModifier` between
- Bash errors trigger `siblingAbortController.abort('sibling_error')`
  → cascade-kill running siblings to prevent compounding failures
- abort hierarchy: per-tool > per-batch (sibling) > per-turn (user
  interrupt)

### 3.4 Termination, recovery, stop hooks

Termination is bounded. Conditions:

- `stop_reason: end_turn` from the API
- `maxTurns` cap
- token budget early-exit (diminishing returns detection)

`max_output_tokens` errors get a 3-layer recovery (query.ts:215-270):

1. **Cap escalation** — `maxOutputTokensOverride = 64_000` (from 8k
   default), retry once silently
2. **Multi-turn recovery** — inject user message:
   `"Output token limit hit. Resume directly — no apology, no recap."`
   Up to `MAX_OUTPUT_TOKENS_RECOVERY_LIMIT = 3` retries
3. **Surface error + skip stop hooks** — prevents death spiral

Stop hooks (covered in §8) can block termination by returning
`{continue: false, stopReason: "..."}` or inject error messages that
force the model to re-evaluate.

---

## 4. Tool framework

### 4.1 Tool shape

[`Tool.ts`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/Tool.ts):
`Tool<Input, Output, Progress>` is a TypeScript generic with ~40
fields. Highlights:

```typescript
type Tool<I, O, P> = {
  name: string
  description: (input: I, ctx: Ctx) => string                  // dynamic
  inputSchema: ZodSchema<I>                                     // primary
  inputJSONSchema?: object                                      // MCP override
  outputSchema?: ZodSchema<O>
  prompt: (ctx) => string                                       // full LLM descriptor
  isConcurrencySafe: (input: I) => boolean
  isReadOnly: (input: I) => boolean
  isDestructive?: (input: I) => boolean
  shouldDefer?: boolean                                         // lazy load
  alwaysLoad?: boolean                                          // exempt from defer
  requiresUserInteraction?: () => boolean                       // headless skip
  aliases?: string[]
  searchHint?: string                                           // ToolSearch keyword

  validateInput: (input, ctx) => ValidationResult
  checkPermissions: (input, ctx) => PermissionResult
  call: (args, ctx, canUseTool, parent, onProgress) => Promise<ToolResult>

  // UI hooks (ink Components)
  renderToolUseMessage?: (...)
  renderToolUseProgressMessage?: (...)
  renderToolResultMessage?: (...)
}
```

### 4.2 Result protocol

```typescript
type ValidationResult = { result: boolean; message?: string; errorCode?: string }
type PermissionResult = {
  behavior: 'allow' | 'deny' | 'ask_user'
  updatedInput?: any                  // permission layer can rewrite args
  reason?: PermissionDecisionReason
}
type ToolResult<T> = {
  data: T
  newMessages?: Message[]             // side-channel injection
  contextModifier?: (ctx) => ctx     // mutate ToolUseContext (serial only)
  mcpMeta?: { _meta?, structuredContent? }
}
```

Errors don't throw — validation returns `{result: false, ...}`,
permission returns `{behavior: 'deny', reason}`, runtime errors get
caught and returned as `ToolResultBlockParam` with the error text. The
model sees structured failures and self-corrects.

### 4.3 ToolSearch lazy loading

Claude Code can advertise 200+ tools (built-in + N MCP servers). The
naive prompt blows past 200KB. Solution: mark low-probability tools as
`shouldDefer: true`. Turn 1 prompt only includes non-deferred tools +
`ToolSearchTool`. When the model needs a deferred tool, it calls
`ToolSearch(query: "slack send message")`, which returns matching tool
schemas via BM25 over name + description (CamelCase + MCP prefix
tokenized). Turn 2 the model calls the tool directly.

`alwaysLoad: true` exempts critical tools (AgentTool, BriefTool) from
ever being deferred.

### 4.4 Tools that bend the framework

A few non-coding tools illustrate the framework's expressiveness:

- **AskUserQuestionTool** ([tools/AskUserQuestionTool](file:///Users/ristoc/Workspaces/self/research/claude-code/src/tools/AskUserQuestionTool/AskUserQuestionTool.tsx))
  — interrupts the agent mid-turn with 1-4 multiple-choice questions.
  `requiresUserInteraction() → true` so headless coordinator workers
  silently skip it.
- **TodoWriteTool** — agent maintains a structured todo list visible to
  user AND model. Keeps long multi-step work honest; model can't forget
  what's pending because it's literally in the context.
- **SkillTool** — invokes a skill by name, injects markdown body into
  conversation. See §7.
- **AgentTool** — spawn a subagent. See §5.
- **TaskCreate/List/Get/Update/Stop/Output** — full lifecycle for
  background jobs. UI shows live stdout capture from running tasks.

---

## 5. Multi-agent orchestration

### 5.1 AgentTool — the spawn primitive

[`tools/AgentTool/AgentTool.tsx`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/tools/AgentTool/AgentTool.tsx).
Args:

```typescript
AgentTool({
  prompt: string,                              // task for child
  subagent_type?: string,                      // agent-definition slug
  name?: string,                               // mailbox handle
  run_in_background?: boolean,
  isolation?: 'worktree' | 'remote',
  model?: ModelOverride,
})
```

Child gets a fresh `ToolUseContext` via `createSubagentContext()`
([`utils/forkedAgent.ts:53-75`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/utils/forkedAgent.ts)):

- own `AbortController` (isolated cancellation)
- own permission mode (no UI prompts unless `shareAbortController`)
- copy of AppState (mutations don't leak back to parent)
- own message history starting with system prompt + task prompt
  (parent transcript NOT included by default)
- subset of tools (filtered by agent definition's allowlist)
- own system prompt assembled via `buildEffectiveSystemPrompt()`,
  layered as: agent-def > custom > default

Result bubbles back as the child's final assistant message. Parent
never sees intermediate tool use — only the synthesized answer. This
context isolation is the central trick.

### 5.2 Four execution modes

| Mode | Class | Use case |
|---|---|---|
| Local sync | `LocalAgentTask` (sync path) | quick subagent, parent waits |
| Local background | `LocalAgentTask` (`run_in_background: true`) | long-running; parent gets `{status: 'async_launched', agentId}` immediately, polls via `TaskGet` / `TaskOutput` |
| In-process teammate | `InProcessTeammateTask` | multiple specialists sharing AppState + Redis-like mailbox; transcripts UI-capped at 50 msgs to avoid memory blowup |
| Remote | `RemoteAgentTask` | offload to CCR compute; survives main process restart |

In-process teammates can SEE each other's task status in real-time via
shared AppState, and communicate via:

```typescript
SendMessage({ to: "websearch", message: "dig deeper on Y" })
```

(`tools/SendMessageTool`). The "researcher" name becomes a mailbox
handle. Idle teammates wait in `pendingUserMessages` until a SendMessage
delivers work.

### 5.3 Worktree isolation

`isolation: 'worktree'` creates a temp git worktree
([`utils/worktree.ts`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/utils/worktree.ts)):
agent's file mutations are isolated from main working tree. On
completion the worktree is pruned. Pattern generalizes beyond git —
it's "isolated side effects per agent".

### 5.4 Coordinator mode

When `CLAUDE_CODE_COORDINATOR_MODE=true`, the parent agent's system
prompt switches to a coordinator template. Workers spawned via AgentTool
run autonomously. Their results bubble back as XML
`<task-notification>` blocks in the parent's chat stream:

```xml
<task-notification>
  <task-id>agent-a1b</task-id>
  <status>completed</status>
  <summary>Found null pointer in src/auth/validate.ts:42</summary>
  <result>...</result>
</task-notification>
```

Parent decides next step (synthesize, delegate more, escalate to user).
Orchestrator-as-team-lead, without explicit state machines in user code.

---

## 6. State, memory, compaction

### 6.1 Compaction trigger

[`services/compact/autoCompact.ts`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/services/compact/autoCompact.ts):

```typescript
export const AUTOCOMPACT_BUFFER_TOKENS = 13_000      // auto-fire
export const WARNING_THRESHOLD_BUFFER_TOKENS = 20_000
export const ERROR_THRESHOLD_BUFFER_TOKENS = 20_000
```

Fires when `tokenUsage >= effectiveContextWindow - 13_000`. Per-model
(200k context → ~187k headroom before compaction). Override via
`CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`.

### 6.2 Message grouping

[`grouping.ts`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/services/compact/grouping.ts):
boundaries fall at each new assistant message id, not at user-turn
boundaries. One prompt can spawn 30 assistant rounds (each with N tool
calls); each round is a compaction group. Fine-grain isolation of
independent tool chains.

### 6.3 Compaction prompt contract

[`services/compact/prompt.ts`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/services/compact/prompt.ts):
not "summarize this conversation" — a structured prompt requiring 7
sections:

```
1. Primary Request and Intent
2. Key Technical Concepts
3. Files and Code Sections (with snippets + why)
4. Errors and fixes (all encountered, all resolutions)
5. Problem Solving (documented troubleshooting)
6. All user messages (excluding tool results)
7. Pending Tasks & Work Completed
```

The LLM wraps analysis in `<analysis>` tags (scratchpad, stripped
before delivery). Two variants: `BASE_COMPACT_PROMPT` (full conversation)
and `PARTIAL_COMPACT_UP_TO_PROMPT` (recent only). Output wrapped via
`getCompactUserSummaryMessage()` with resumption instructions:
*"Do not recap, pick up where you left off."*

### 6.4 SessionMemory (background per-turn extraction)

[`services/SessionMemory/sessionMemory.ts:130-170`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/services/SessionMemory/sessionMemory.ts).
Fires after EVERY completed turn (no pending tool_use). Gates:

- `currentTokenCount >= initThreshold` (~4-5k)
- `tokenCount - lastUpdateCount >= updateThreshold`
- (`toolCallsInLastTurn || hasMetToolCallThreshold`)

Runs a forked subagent (same system prompt, shared prompt cache,
limited turn budget) that writes a markdown file at
`~/.claude/projects/<path>/CLAUDE.md` with sections: Current State,
Task Specification, Files & Functions, Workflow, Errors & Corrections,
Codebase Documentation, Learnings, Key Results, Worklog.

### 6.5 AutoDream (cross-session consolidation)

[`services/autoDream/autoDream.ts`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/services/autoDream/autoDream.ts).
Less frequent than SessionMemory. Gate order (cheapest first):

1. `hoursSince >= minHours` (default 24h)
2. `transcriptCount with mtime > lastConsolidatedAt >= minSessions`
   (default 5)
3. `tryAcquireConsolidationLock()` — no concurrent runs
4. scan throttle — max once per 10 min

Then a 4-phase consolidation prompt:

```
Phase 1: Orient    - ls memory dir, read MEMORY.md index
Phase 2: Gather    - grep recent session transcripts for new signal
Phase 3: Consolidate - merge/update topic files
Phase 4: Prune + index - keep MEMORY.md under 200 lines & 25KB
```

### 6.6 Session resume

[`commands/resume/resume.tsx`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/commands/resume/resume.tsx):
three paths. No args → interactive LogSelector. UUID → direct lookup.
Text → search via `agenticSessionSearch`. Cross-project detect — if
resuming from a different cwd, copies `/cd` command to clipboard.

Transcript format: JSONL (one message per line). Path:
`~/.claude/projects/<projectDir>/<sessionId>.jsonl`. Messages form a
parentUuid tree (branching for user edits, reruns). Ephemeral progress
entries filtered out (`EPHEMERAL_PROGRESS_TYPES`). Full transcript
replay on resume — no delta/patch.

### 6.7 ExtractMemories (lightweight per-query writer)

[`services/extractMemories`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/services/extractMemories/extractMemories.ts).
Fires via `handleStopHooks`. Tool allowlist: FileRead, Grep, Glob,
read-only Bash, FileEdit/Write (memory dir only). Turn budget ~5-6
turns. Exclusion: if main agent already wrote memories this turn
(`hasMemoryWritesSince`), skip.

---

## 7. Skills, modes, output styles

### 7.1 Skills

[`skills/`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/skills) +
[`utils/skills/`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/utils/skills/).
Each skill is a folder with `SKILL.md`:

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
...
```

Discovery: `~/.claude/skills/`, `.claude/skills/`, project-scoped dirs.
Bundled skills register via TypeScript at startup. User skills loaded
lazily.

`SkillTool` ([tools/SkillTool/prompt.ts](file:///Users/ristoc/Workspaces/self/research/claude-code/src/tools/SkillTool/prompt.ts))
lists ALL skills in the system prompt, budgeted to **1% of context
window** (`SKILL_BUDGET_CONTEXT_PERCENT = 0.01`), with truncated
descriptions (`MAX_LISTING_DESC_CHARS = 250`, bundled always full).
Full markdown body loads only when the LLM invokes the skill — by then
the skill is executed in a forked subagent.

### 7.2 Plan mode

[`utils/planModeV2.ts`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/utils/planModeV2.ts) +
[`commands/plan/plan.tsx`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/commands/plan/plan.tsx).
Plan mode is NOT a tool — it's a permission-context state:

```typescript
setAppState(prev => ({
  ...prev,
  toolPermissionContext: applyPermissionUpdate(prepareContextForPlanMode(...), {
    type: 'setMode',
    mode: 'plan',
    destination: 'session'
  })
}))
```

Effects:
- system prompt swaps to a "plan first, execute later" template
- write tools (FileEdit, Bash) become `behavior: 'ask_user'` instead of `'allow'`
- prompt suggestions disabled (`getSuggestionSuppressReason() → 'plan_mode'`)
- `ExitPlanModeTool` is the only transition back; restores `prePlanMode`

Workflow: Interview → Plan → Execute → Review → Deliver.

### 7.3 Output styles

[`outputStyles/`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/outputStyles).
Markdown files in `.claude/output-styles/` or `~/.claude/output-styles/`:

```markdown
---
name: Explanatory
description: Educational explanations alongside actions
keep-coding-instructions: false
---

After every change, briefly explain WHY you made it. ...
```

Frontmatter:

```typescript
type OutputStyleConfig = {
  name: string
  description: string
  prompt: string                       // the markdown body
  source: SettingSource | 'built-in' | 'plugin'
  keepCodingInstructions?: boolean
}
```

User picks via `/output-style <name>`; selected prompt appends to the
system prompt every turn. Built-in styles include `Explanatory`,
`Learning`.

### 7.4 MagicDocs

[`services/MagicDocs/magicDocs.ts`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/services/MagicDocs/magicDocs.ts).
Files with `# MAGIC DOC: <title>` header at the top get registered in
`trackedMagicDocs`. A background Sonnet agent (FileEditTool-only)
watches conversation context and keeps the doc current.

Update prompt rules ([`prompts.ts`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/services/MagicDocs/prompts.ts)):

```
- Preserve the Magic Doc header exactly as-is
- Keep the document CURRENT (not historical)
- Update information IN-PLACE; remove outdated info
- Fix typos, grammar, formatting; clean up irrelevant sections
- BE TERSE. High signal only. No filler words.
```

Custom per-doc update instructions can be embedded as italics after
the header. Pattern: agent-maintained living artifact distinct from
chat transcript.

### 7.5 Tool-use summary

[`services/toolUseSummary/toolUseSummaryGenerator.ts`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/services/toolUseSummary/toolUseSummaryGenerator.ts).
After tool batches complete, a Haiku call generates a git-commit-style
label (~30 chars):

```
Searched in auth/
Fixed NPE in UserService
Created signup endpoint
```

System prompt: *"Write a short summary label... Keep verb in past tense,
most distinctive noun. Drop articles, connectors, location context."*
Rendered inline instead of the verbose tool-call/tool-result pair.

### 7.6 PromptSuggestion

[`services/PromptSuggestion/promptSuggestion.ts`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/services/PromptSuggestion/promptSuggestion.ts).
After 2+ assistant turns, Haiku predicts the next user prompt. Surfaces
as ghost text. Suppressed in plan mode, when permission pending, on
rate-limit, in non-interactive sessions.

```typescript
function getSuggestionSuppressReason(): string | null {
  if (appState.toolPermissionContext.mode === 'plan') return 'plan_mode'
  if (appState.promptSuggestionEnabled === false) return 'disabled'
  if (appState.pendingWorkerRequest || appState.pendingSandboxRequest)
    return 'pending_permission'
  // ...
}
```

---

## 8. Hooks, permissions, sandbox

### 8.1 Hook taxonomy

27 event types (from `entrypoints/agentSdkTypes.ts`):

```
PreToolUse, PostToolUse, PostToolUseFailure
UserPromptSubmit, SessionStart, SessionEnd
Stop, StopFailure
SubagentStart, SubagentStop
PreCompact, PostCompact
PermissionRequest, PermissionDenied
Setup, TeammateIdle, TaskCreated, TaskCompleted
Elicitation, ElicitationResult
ConfigChange, WorktreeCreate, WorktreeRemove
InstructionsLoaded, CwdChanged, FileChanged
Notification
```

Each event has a typed input shape.

### 8.2 Hook configuration

[`utils/hooks/hooksSettings.ts:22-28`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/utils/hooks/hooksSettings.ts):

```typescript
type IndividualHookConfig = {
  event: HookEvent
  config: HookCommand                            // command | prompt | agent | http | function
  matcher?: string                               // "Edit|Write", empty=all
  source: HookSource                             // userSettings|projectSettings|localSettings|sessionHook|pluginHook|builtinHook|policySettings
  pluginName?: string
}

// settings.json shape:
{ "PreToolUse": [{ "matcher": "Edit|Write", "hooks": [{"type": "command", "command": "echo Done"}]}] }
```

Five hook types:

- `command` — shell script (`shell`, conditional `if`)
- `prompt` — interactive user question
- `agent` — spawn a subagent
- `http` — POST request
- `function` — TypeScript callback (plugin/internal only)

Discovery: scan user → project → local → session → plugin → builtin;
dedupe by resolved path; priority: policy > user > project > local >
plugin/builtin. `allowManagedHooksOnly` lets policy hide user hooks.

### 8.3 Hook execution

[`types/hooks.ts:49-176`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/types/hooks.ts):

```typescript
type SyncHookResponse = {
  continue?: boolean              // proceed after hook (default true)
  suppressOutput?: boolean
  stopReason?: string
  decision?: 'approve' | 'block'  // override permission decision
  hookSpecificOutput?: union[...] // event-specific mutations
}

type AsyncHookResponse = { async: true, asyncTimeout?: number /*seconds*/ }

type HookCallback = {
  type: 'callback'
  callback: (input, toolUseID, abort, hookIndex?) => Promise<HookJSONOutput>
  timeout?: number
  internal?: boolean
}
```

Side effects allowed per event:

- **PreToolUse** — permission override, input mutation (`updatedInput`),
  context injection
- **PostToolUse** — output mutation (MCP tool output), context injection
- **UserPromptSubmit** — context injection (this is how
  `<system-reminder>` blocks get added to user prompts)
- **SessionStart** — watch paths, initial message override
- **PermissionRequest** — allow/deny, rule updates, input mutation
- **Stop** — block continuation (`continue: false`), inject error
  message into messages list for model re-evaluation

Timeouts per hook (seconds). AbortSignal passed for cancellation.

### 8.4 Permission system

[`types/permissions.ts:47-441`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/types/permissions.ts):

```typescript
type ToolPermissionContext = {
  mode: PermissionMode
  additionalWorkingDirectories: Map<string, AdditionalWorkingDirectory>
  alwaysAllowRules: ToolPermissionRulesBySource
  alwaysDenyRules: ToolPermissionRulesBySource
  alwaysAskRules: ToolPermissionRulesBySource
  isBypassPermissionsModeAvailable: boolean
  strippedDangerousRules?: ToolPermissionRulesBySource
  shouldAvoidPermissionPrompts?: boolean
  awaitAutomatedChecksBeforeDialog?: boolean
  prePlanMode?: PermissionMode
}

type PermissionRule = {
  source: PermissionRuleSource
  ruleBehavior: 'allow' | 'deny' | 'ask'
  ruleValue: { toolName: string, ruleContent?: string }
  // "Bash(git *)" parses to: toolName="Bash", ruleContent="git *"
}
```

Three-rule system: alwaysAllow / alwaysDeny / alwaysAsk. First match
(by source priority) wins. Ask overrides Allow (user gets final say).
Deny + anything = Deny (fail-safe).

Source priority order (`PERMISSION_RULE_SOURCES`):

```
userSettings → projectSettings → localSettings → flagSettings
→ policySettings → cliArg → command → session
```

Decision reasons are first-class:

```typescript
type PermissionDecisionReason =
  | { type: 'rule'; rule: PermissionRule }
  | { type: 'mode'; mode: PermissionMode }
  | { type: 'hook'; hookName: string; hookSource?: string }
  | { type: 'classifier'; classifier: string; reason: string }
  | { type: 'safetyCheck'; reason: string; classifierApprovable: boolean }
  | { type: 'sandboxOverride'; reason: 'excludedCommand' | 'dangerouslyDisableSandbox' }
  | { type: 'subcommandResults'; reasons: Map<string, PermissionResult> }
```

### 8.5 Permission modes

```typescript
const EXTERNAL_PERMISSION_MODES = [
  'acceptEdits',         // legacy implicit-allow for edits
  'bypassPermissions',   // skip all prompts (policy can disable)
  'default',             // respect rules: allow/deny/ask
  'dontAsk',             // auto-deny when no rule matches (headless)
  'plan',                // plan mode (see §7.2)
]

type InternalPermissionMode = ExternalPermissionMode | 'auto' | 'bubble'
// 'auto'  : transcript classifier runs, auto-approves safe commands
// 'bubble': permission denied → escalate to parent agent (subagent only)
```

Transitions: default ↔ plan (stored in `prePlanMode`); `auto` enabled by
feature flag `TRANSCRIPT_CLASSIFIER`; `bubble` for coordinator/subagent
hierarchies; `dontAsk` for background agents.

### 8.6 Sandbox

[`entrypoints/sandboxTypes.ts:14-143`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/entrypoints/sandboxTypes.ts):

```typescript
type SandboxSettings = {
  enabled?: boolean
  failIfUnavailable?: boolean              // exit if sandbox can't start
  autoAllowBashIfSandboxed?: boolean
  allowUnsandboxedCommands?: boolean
  excludedCommands?: string[]              // always run unsandboxed (e.g., ["git"])
  network?: SandboxNetworkConfig           // allowedDomains, allowUnixSockets, etc
  filesystem?: SandboxFilesystemConfig     // allowWrite[], denyWrite[], allowRead[], denyRead[]
  ignoreViolations?: { [command]: string[] }
  enableWeakerNetworkIsolation?: boolean
  enableWeakerNestedSandbox?: boolean
}
```

Enforcement via `@anthropic-ai/sandbox-runtime` (separate package).
Bash/PowerShell/REPL tools check `shouldUseSandbox()` before executing.
Violations can be ignored per command + path.

### 8.7 Stop hooks — controlling termination

Stop hooks can prevent turn termination:

```typescript
// Stop hook response:
{ continue: false, stopReason: "deployment not healthy" }
// blocks termination, model forced to re-evaluate

{ continue: true }
// allows normal exit

// blockingErrors get injected as HookBlockingError messages
// into the model's context for next round
```

Integration with turn loop ([`utils/hooks.ts`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/utils/hooks.ts)):

```
1. Execute all matching Stop hooks
2. If preventContinuation || blockingErrors.length > 0:
   - inject messages
   - state.messages.push(blocking errors)
   - continue turn (model sees errors, decides next action)
3. Else: clean termination
```

### 8.8 Policy + managed settings

[`services/policyLimits/`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/services/policyLimits/index.ts) +
[`services/remoteManagedSettings/`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/services/remoteManagedSettings/index.ts).

```
GET /api/claude_code/policy_limits
  → { restrictions: { [policyKey]: { allowed: boolean } } }

GET /api/claude_code/settings
  → full SettingsJson (hooks, permissions, sandbox)
```

Both: eligibility-gated (Console all; OAuth Team/Enterprise/C4E only),
60-min polling, ETag/SHA256-cached, fail-open. Initialize loading
promises early to prevent deadlocks.

---

## 9. MCP + plugins

### 9.1 MCP transport + lifecycle

[`services/mcp/types.ts:23-26`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/services/mcp/types.ts):

```typescript
const TransportSchema = z.enum(['stdio', 'sse', 'sse-ide', 'http', 'ws', 'sdk'])
```

Each transport has its own config schema. Server connects via MCP SDK
`Client` wrapping the chosen transport.

Reconnect: on SSE stream expiration (404 `session-not-found`), call
`reconnectMcpServerImpl()` ([client.ts:~1800](file:///Users/ristoc/Workspaces/self/research/claude-code/src/services/mcp/client.ts))
which clears memoized resources and re-establishes the session.

Timeouts: `MCP_TOOL_TIMEOUT ≈ 27.8 hrs default` (env-overridable);
per-request 60s wrapping fetch to handle stale AbortSignal.

### 9.2 MCP tool advertising via namespacing

[`services/mcp/mcpStringUtils.ts:39-67`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/services/mcp/mcpStringUtils.ts):

```typescript
function getMcpPrefix(serverName: string): string {
  return `mcp__${normalizeNameForMCP(serverName)}__`
}
function buildMcpToolName(serverName: string, toolName: string): string {
  return `${getMcpPrefix(serverName)}${normalizeNameForMCP(toolName)}`
}
function getToolNameForPermissionCheck(tool): string {
  return tool.mcpInfo
    ? buildMcpToolName(tool.mcpInfo.serverName, tool.mcpInfo.toolName)
    : tool.name
}
```

MCP tools enter the catalog as `mcp__<server>__<tool>`. `MCPTool` is a
template tool ([tools/MCPTool/MCPTool.ts:27-77](file:///Users/ristoc/Workspaces/self/research/claude-code/src/tools/MCPTool/MCPTool.ts))
that `buildTool()` marks with `shouldDefer: true`. Per-server tools
clone MCPTool and override `name`, `description`, `call`, `inputSchema`,
`outputSchema` with server-advertised metadata.

Permission checks use the fully-qualified name — `Bash(git *)` deny
rule won't match `mcp__editor__write`. Server-prefix wildcards
(`mcp__github__*`) allow blanket allow/deny per server.

### 9.3 MCP resources (distinct from tools)

[`tools/ListMcpResourcesTool`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/tools/ListMcpResourcesTool/ListMcpResourcesTool.ts) +
[`tools/ReadMcpResourceTool`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/tools/ReadMcpResourceTool/ReadMcpResourceTool.ts).

```typescript
const outputSchema = z.array(z.object({
  uri: z.string(),
  name: z.string(),
  mimeType: z.string().optional(),
  description: z.string().optional(),
  server: z.string()
}))
```

Resources LRU-cached by server name, prefetched at startup. Discovery
(cheap, cacheable) decoupled from content retrieval (potentially
expensive, streamed via Read).

### 9.4 OAuth flow

[`services/mcp/auth.ts:257-316`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/services/mcp/auth.ts):

```typescript
const MCP_AUTH_CACHE_TTL_MS = 15 * 60 * 1000

// auth cache shape: { [serverId]: { timestamp: number } }
function getMcpAuthCache(): Promise<McpAuthCacheData> { ... }
```

Server discovery from `oauth.authServerMetadataUrl`. Writes serialized
via promise chain to prevent race when multiple servers 401
concurrently. `McpAuthTool` is a pseudo-tool created when server needs
auth — on call, performs `performMCPOAuthFlow()`, opens browser, stores
tokens via OS secure storage (macOS Keychain), then triggers reconnect
which swaps in the real authenticated tools.

### 9.5 Plugin architecture

Plugins are distinct from MCP and skills. Layout:

```
my-plugin/
├── .claude-plugin/
│   └── plugin.json          # manifest: name, version, permissions
├── commands/                # custom slash commands (*.md)
├── agents/                  # custom agent defs (*.md)
├── hooks/
│   └── hooks.json
└── dist/ or src/            # optional JS/TS (if MCP server)
```

Manifest ([`utils/plugins/pluginLoader.ts:54-60`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/utils/plugins/pluginLoader.ts)):

```typescript
type PluginManifest = {
  name: string
  version: string
  description?: string
  permissions?: string[]
  ...
}
```

Discovery sources:
1. Marketplaces (`plugin@marketplace` in settings)
2. Session-only (`--plugin-dir` CLI flag)
3. Built-in (`src/plugins/builtinPlugins.js`)

Load sequence ([`services/plugins/PluginInstallationManager.ts:60-100`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/services/plugins/PluginInstallationManager.ts)):

1. **Cache-only boot** — `loadAllPluginsCacheOnly()` reads plugin.json
   from cache. No network wait.
2. **Background reconciliation** — compare declared (settings) vs.
   materialized (known-marketplaces.json). Diff drives auto-install.
3. **Refresh** — new installs trigger `refreshActivePlugins()`.
4. **Hot reload** — `commands/reload-plugins/`.

Versioning: git SHA, semver, or marketplace-supplied. Cached path
encodes version.

Bundled plugins ([`src/plugins/bundled/index.ts`](file:///Users/ristoc/Workspaces/self/research/claude-code/src/plugins/bundled/index.ts))
is currently empty scaffold — features ship as skills (auto-load), not
plugins (user-installable).

### 9.6 Conflict resolution

- **MCP tools** — namespaced by server. Two servers can both expose
  `search` → distinct `mcp__server1__search` vs `mcp__server2__search`.
  Model picks.
- **Plugin commands** — scoped by plugin ID in `.claude-plugin/hooks.json`.
- **Permissions** — fully-qualified names prevent rule collision (deny
  on `Write` doesn't hit `mcp__editor__write`).

---

## 10. Engineering patterns worth noting

These patterns aren't subsystems themselves but recur across the code:

### 10.1 Fail-open

Policy fetch fails, network down, hook timeout — the system continues
in a degraded mode rather than blocking. Particularly visible in
`policyLimits`, `remoteManagedSettings`, MCP discovery, and the LLM
provider's `formatted_instructions` validation (which catches errors
and returns raw content rather than crashing).

### 10.2 Memoization + cache-first loads

Settings, commands, system prompt, MCP resources — all behind memoized
loaders. The boot path explicitly prefers cache reads to unblock UX,
with background reconciliation that swaps in fresh data when ready.

### 10.3 Discriminated unions for command/hook shapes

`Command` is `{type: 'prompt'} | {type: 'local'} | {type: 'local-jsx'}`.
`HookCommand` is `command | prompt | agent | http | function`. Each
shape carries enough info to dispatch without runtime polymorphism.

### 10.4 Hierarchical AbortControllers

Per-tool > per-batch (sibling) > per-turn (user interrupt). One signal
cascade kills sub-operations safely. Combined with `StreamingToolExecutor`
this gives fine-grained interruption without orphaned work.

### 10.5 Forked subagent as a reusable primitive

Background services (SessionMemory, ExtractMemories, AutoDream, Tool-use
summary, PromptSuggestion) all spawn forked subagents that share the
prompt cache but have isolated context. The "fork" pattern is the
unit of cheap background intelligence.

### 10.6 1%-budget tool/skill advertising

`SKILL_BUDGET_CONTEXT_PERCENT = 0.01` for skills. Similar pattern for
deferred MCP tools. The catalog is huge, but the LLM only sees a
budgeted slice with truncated descriptions on turn 1. Full content
loads on demand via SkillTool / ToolSearchTool.

### 10.7 Sources stack with policy override

Settings, hooks, permissions all follow the same stack pattern. Policy
sits at the top and can force "managed-only" mode that hides every
layer below. This makes the same code path serve solo CLI users,
project teams, and enterprise deployments.

### 10.8 Async generators as the streaming primitive

`query()` is `async function*`. `runTools()`, `getRemainingResults()` —
all generators. State traverses recursive generator calls cleanly; UI
consumes yielded messages without coupling to internal loop structure.

### 10.9 Structured prompts as contracts

Compaction prompt enforces 7 sections. MagicDocs update prompt has 5
hard rules. Tool-use summary system prompt specifies past-tense verb +
~30-char ceiling. These aren't free-form — they're contracts that the
calling code parses output against.

### 10.10 Slash commands as pre-LLM rewrites

Most slash commands expand to text injected into the user message
BEFORE the LLM sees the turn. `/skills`, `/plan`, prompt-type commands
— none of them create a separate model round. This keeps the agent
loop pure: input → expand → query.

### 10.11 Worktree + sandbox isolation as the unit of "safe try"

Whenever an agent might mutate something risky, the framework offers
isolation: git worktree, sandbox filesystem, separate subagent context.
The pattern "run risky thing in a corner, throw away the corner if it
fails" is woven through plan mode, AgentTool's `isolation` arg,
Sandbox config.

---

## 11. File index (quick reference)

Grouped by subsystem. All paths under
`/Users/ristoc/Workspaces/self/research/claude-code/src/`.

### Turn loop + orchestration
- `query.ts` — main recursive generator loop
- `QueryEngine.ts` — outer driver + message store
- `Task.ts` — task wrapper
- `services/tools/StreamingToolExecutor.ts` — parallel queue + abort cascade
- `services/tools/toolOrchestration.ts` — concurrency-safe partitioning
- `Tool.ts` — Tool<I,O,P> interface + buildTool() factory

### Tool framework
- `tools.ts` — registry assembly, deny filtering
- `tools/AskUserQuestionTool/` — mid-turn user prompting
- `tools/TodoWriteTool/` — agent todo list
- `tools/ToolSearchTool/` — lazy descriptor fetching
- `tools/AgentTool/` — subagent spawning
- `tools/SendMessageTool/` — named-agent messaging
- `tools/TaskCreateTool/` etc — background job lifecycle

### Multi-agent
- `tools/AgentTool/AgentTool.tsx`
- `tasks/LocalAgentTask/`
- `tasks/InProcessTeammateTask/`
- `tasks/RemoteAgentTask/`
- `tasks/DreamTask/`
- `utils/forkedAgent.ts` — `createSubagentContext()`
- `utils/worktree.ts` — worktree isolation
- `utils/swarm/` — coordinator + teammate utilities
- `coordinator/coordinatorMode.ts` — coordinator system-prompt swap

### State + memory
- `services/compact/autoCompact.ts` — token-threshold trigger
- `services/compact/grouping.ts` — API-round message grouping
- `services/compact/prompt.ts` — 7-section structured prompt
- `services/SessionMemory/sessionMemory.ts` — per-turn extraction
- `services/extractMemories/extractMemories.ts` — lightweight per-query writer
- `services/autoDream/autoDream.ts` — cross-session consolidation
- `services/AgentSummary/` — turn summary
- `commands/resume/resume.tsx` — session resume
- `history.ts`, `memdir/` — transcript + memory storage
- `utils/sessionStorage.ts` — JSONL transcript format

### Skills + modes + styles
- `skills/loadSkillsDir.ts` — discovery
- `skills/bundled/` — bundled skills
- `tools/SkillTool/prompt.ts` — 1%-budget listing
- `tools/SkillTool/SkillTool.ts` — invocation
- `utils/planModeV2.ts` + `commands/plan/plan.tsx` — plan mode
- `outputStyles/loadOutputStylesDir.ts` — output style discovery
- `constants/outputStyles.ts` — built-in styles
- `services/MagicDocs/magicDocs.ts` — auto-updating artifacts
- `services/MagicDocs/prompts.ts` — update prompt
- `services/PromptSuggestion/promptSuggestion.ts` — next-prompt prediction
- `services/toolUseSummary/toolUseSummaryGenerator.ts` — Haiku tool labels

### Hooks + permissions + sandbox
- `types/hooks.ts` — hook response schemas
- `utils/hooks/hooksSettings.ts` — discovery + priority
- `utils/hooks.ts` — execution + stop-hook integration
- `types/permissions.ts` — `ToolPermissionContext`, `PermissionDecisionReason`
- `utils/permissions/permissions.ts` — decision logic
- `utils/permissions/permissionSetup.ts` — boot-time init
- `entrypoints/sandboxTypes.ts` — sandbox config
- `utils/sandbox/sandbox-adapter.ts` — sandbox-runtime wrapper
- `services/policyLimits/` — enterprise policy
- `services/remoteManagedSettings/` — remote settings sync

### MCP + plugins
- `services/mcp/client.ts` — server lifecycle, reconnect
- `services/mcp/types.ts` — transport schemas
- `services/mcp/mcpStringUtils.ts` — namespacing
- `services/mcp/auth.ts` — OAuth + token cache
- `tools/MCPTool/MCPTool.ts` — deferred template tool
- `tools/ListMcpResourcesTool/`, `tools/ReadMcpResourceTool/`
- `tools/McpAuthTool/McpAuthTool.ts` — OAuth pseudo-tool
- `services/plugins/PluginInstallationManager.ts` — install + reconcile
- `utils/plugins/pluginLoader.ts` — manifest validation
- `plugins/bundled/index.ts` — bundled plugin scaffold

### Entrypoints + boot
- `setup.ts` — boot sequence
- `bootstrap/state.ts` — singleton state
- `entrypoints/cli.tsx` — CLI entry
- `entrypoints/sdk/` + `entrypoints/agentSdkTypes.ts` — SDK contract
- `entrypoints/mcp.ts` — MCP server entry
- `commands.ts` — slash command registry
- `utils/processUserInput/processUserInput.ts` — prompt pipeline
- `utils/slashCommandParsing.ts` — `/cmd` parsing
- `cli/transports/` — SSE/WebSocket/HybridTransport

---

## Closing observations

Three things stand out architecturally:

1. **The agent loop is treated as a first-class control-flow construct.**
   It's a recursive async generator with explicit state, not a
   while-loop hiding inside a service. The structure means streaming,
   abort cascading, and recovery are uniform across every turn rather
   than ad-hoc per call site.

2. **Extensibility is layered, not monolithic.** Skills (markdown +
   frontmatter, user-facing), plugins (full directories with manifests,
   distributable), MCP (cross-process tool servers), hooks (lifecycle
   interception) are four distinct mechanisms with different lifecycles
   and contracts. A user adding a draft template uses skills; a vendor
   shipping an integration uses plugins or MCP; an org enforcing
   compliance uses hooks + policy settings.

3. **Almost every background intelligence reuses the "forked subagent"
   primitive.** SessionMemory, ExtractMemories, AutoDream, tool-use
   summary, PromptSuggestion — all spawn forked agents that share the
   prompt cache, isolate context, run on cheap models. The unit of
   cheap intelligence is "fork a Haiku call with a small turn budget".
   Once you have that primitive, you can build an arbitrary number of
   background helpers without architectural rework.

What's notably absent from a more conventional product surface:

- **No central event bus** — communication between subsystems goes
  through the `AppState` object + AbortControllers, not pub/sub.
- **No DI container** — modules are imported directly; "services"
  are objects with init/get functions, no DI framework.
- **No formal state machine** — turn lifecycle is the generator loop;
  permission modes are enum + transitions handled inline.

These omissions reduce indirection at the cost of some discoverability —
finding "where does X get registered" can require following imports
through 4-5 files.
