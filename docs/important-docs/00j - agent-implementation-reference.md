# Agent Implementation Reference — chat agent layer handbook

> **Audience:** developers building the Donna chat agent — UC1
> (company Q&A) + UC2 (conversation-locked drafting) — under
> `donna/chat/agents/` (Phase 3.5/3.6 of the
> [communication platform plan](../../server/plans/communication-platform-plan.md)).
>
> **Status:** drafted 2026-06-12 from the approved implementation
> blueprint. Code blocks are starting points written against verified
> current signatures — refine while implementing, keep the contracts.
>
> **Pattern source:** docupal `agents/legal` v10 (agent-as-router,
> ToolRegistry + factory, dispatcher, DI) — minus its LangChain
> bridge: Donna's `LLMProvider.chat` has native `tools=`.
>
> **Companions:** [`00f`](./00f%20-%20silver-completion-plan.md)
> silver master plan · [`00i`](./00i%20-%20silver-implementation-reference.md)
> silver handbook · [`00g`](./00g%20-%20mcp-implementation-guide.md)
> MCP deep-dive · [`00h`](./00h%20-%20ask-donna-roadmap.md) Q&A
> critical path · [`00k`](./00k%20-%20multi-agent-architecture.md)
> multi-agent pattern catalog + verdicts ·
> [`00l`](./00l%20-%20agentic-rag-walkthrough.md) worked example —
> one question traced end-to-end with reasoning + code per step.

**Verified chat/LLM facts this doc builds on (2026-06-12):**
- `Channel(kind: CHANNEL|DIRECT, visibility, workspace)`; `AgentSession(channel FK, name="Donna", memory JSON, config JSON)` exists; `Message` has `author_user XOR author_agent` DB constraint; `Document(channel, title, body)` exists (Cowork-style).
- `ChannelService.send_message(*, channel, sender_user, body, client_msg_id=None)` static + `@transaction.atomic`; `_broadcast()` + group helpers `channel_group/agent_run_group/...`; services comment reserves a separate worker path for agent-authored messages.
- `AgentStreamConsumer` ready on `agent-run-{run_id}-tokens`; producer missing.
- `LLMProvider.chat(messages, system_prompt=, temperature=, stream=, formatted_instructions=, tools=, tool_choice=, available_functions=)` → `LLMResponse(content, tool_calls: list[ToolCall{id, function{name, arguments}}])`; tool_calls **non-streaming only**.
- No chat `tasks.py` yet; no cache.lock util (`redis_manager` has set_ex/delete).
- **Decision 2026-06-12:** drafts = extend `Document` (status/version/target_doc_type/finalized_entity_id + partial unique), not a new model.

**Dependency:** cortex tools properly target `CortexService`
(00f Phase 4a, unbuilt). To unblock chat work, §A1 ships an interim
`CortexReadFacade` over the ORM (heads-only), swapped for
`CortexService` when 4a lands — the swap point is isolated in
`tools/factory.py`.

---

## §0 Orientation

```
Message arrives (REST/WS) → ChannelService.send_message() persists
  └─ on_commit → maybe_dispatch_agent(message)            [A1 hook]
       └─ Celery run_agent_turn(channel_id, message_id)
            ├─ redis lock "agent-turn:{channel_id}"        ← cowork serialization
            ├─ build AgentState (window of Message rows + AgentSession.memory + active draft)
            ├─ graph: entry → conversation_agent ⇄ tool_dispatcher (max 6 rounds)
            │     tools: cortex read (UC1) · draft tools (UC2, gated per surface)
            ├─ final text → Message(author_agent=session) + chat.message.created broadcast
            └─ status/tokens → agent-run-{run_id}-tokens (AgentStreamConsumer)
```

Invariants (carried from docupal v10 + Donna design):
- **One message kind per agent turn**: tool calls XOR final text.
- **Anti-loop**: never dispatch when `message.author_agent` is set.
- **Tenancy below the prompt**: every tool takes `ToolContext(workspace, user, channel)`; scope filters live in tool `run()`, not in LLM instructions.
- **One active draft per channel** — Postgres partial unique, member churn can't fork it.
- **Draft ≠ silver**: mutable `Document` until `finalize` → one linted `CortexEntity` write.

Module fate map:

| Path | Action | Phase |
|---|---|---|
| `donna/chat/agents/{tools,nodes,prompts,state}/`, `graph.py`, `runner.py`, `locks.py` | new | A0–A2 |
| `donna/chat/tasks.py` | new (dispatch + turn task) | A1 |
| `donna/chat/services.py` `send_message` | + on_commit dispatch hook | A1 |
| `donna/chat/models.py` `Document` | + draft lifecycle fields + partial unique | A2 |
| `donna/chat/consumers.py` | unchanged (producer feeds existing `AgentStreamConsumer`) | — |

## §A0 Foundations (~1d)

**`donna/chat/agents/tools/base.py` (new):**

```python
from typing import NewType

# Taint tracking (openfang pattern, adopted 2026-06-12) — strings that
# originated outside trusted boundaries (email bodies, cortex entity
# bodies, webhook payloads, scraped URLs) carry a marker. Tools that
# perform dangerous ops (shell exec, URL fetch, draft body assembly
# without explicit sanitization) refuse tainted args; tools that only
# read or display are taint-safe. Type-level signal — not a runtime
# wrapper — keeps Pydantic happy; the dispatcher inspects field
# annotations on args_model to find taint sources.
Tainted = NewType("Tainted", str)            # marker only; identity at runtime

@dataclass(frozen=True)
class ToolContext:
    workspace: "Workspace"
    user: "User | None"                       # None when agent acts from schedule, later
    channel: "Channel"
    agent_session: "AgentSession"

@dataclass(frozen=True)
class ToolResult:
    payload: Any = None
    error: str | None = None
    @classmethod
    def fail(cls, msg: str) -> "ToolResult": return cls(error=msg)

class DonnaTool(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    args_model: ClassVar[type[BaseModel]]

    # Tiered timeouts (openfang pattern, adopted 2026-06-12) — most tools
    # finish in <2s; macro-tools that fan out parallel sub-calls or
    # spawn sub-agents need 5× headroom. Dispatcher honors this per
    # tool, not a global wall.
    timeout_s: ClassVar[int] = 120

    # Tainted args policy. Default False = tool may NOT receive tainted
    # strings from cortex/email/webhook content. Tools that explicitly
    # accept external text (draft revision, body summarization) flip
    # this to True and shoulder the responsibility of sanitizing.
    taint_safe: ClassVar[bool] = False

    def announce(self, args: BaseModel) -> str:              # user-facing status line
        return f"Running {self.name}…"

    @abstractmethod
    def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult: ...

    def describe(self) -> dict:                              # OpenAI tool schema for LLMProvider
        return {"type": "function", "function": {
            "name": self.name, "description": self.description,
            "parameters": self.args_model.model_json_schema()}}
```

**Taint flow in plain English:** any data the agent did not type itself
is tainted. Email body retrieved by `read_entity`? Tainted. Webhook
payload echoed back? Tainted. A cortex doc body? Tainted (it was
authored by a human or another connector — could contain hostile
"ignore prior instructions" text). The dispatcher checks tool returns
and stamps the type marker on string fields; downstream tools that
declare `taint_safe = False` get the value rejected with a clear error
the agent can recover from.

**`registry.py` (new):** `register/get/describe_all()` (list of `describe()` dicts — feeds `LLMProvider.chat(tools=...)`); duplicate-name guard; `freeze()` lock after boot.

```python
class RegistryFrozenError(RuntimeError): pass

class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, DonnaTool] = {}
        self._frozen = False

    def register(self, *tools: DonnaTool) -> None:
        if self._frozen:
            raise RegistryFrozenError(
                "ToolRegistry is frozen — tool registration must happen during app boot. "
                "Got attempt to register: " + ", ".join(t.name for t in tools))
        for t in tools:
            if t.name in self._tools:
                raise ValueError(f"duplicate tool name: {t.name}")
            self._tools[t.name] = t

    def freeze(self) -> None:
        """Lock the registry. Called from chat AppConfig.ready() AFTER
        all connectors + tool modules have imported. After this point,
        register() raises — prevents runtime tool-injection attacks
        (e.g., a malicious skill loaded mid-session)."""
        self._frozen = True

    def get(self, name: str) -> DonnaTool: return self._tools[name]
    def describe_all(self) -> list[dict]: return [t.describe() for t in self._tools.values()]
```

Note: per-turn registries built via `build_registry(channel=...)` (factory.py, §A2) are short-lived and intentionally NOT frozen — the long-lived risk is the global/module registry, not the per-turn one. The frozen registry is `donna.chat.agents.tools.GLOBAL_REGISTRY`, sealed in `apps.py ready()`. Per-turn registries are built from it via `GLOBAL_REGISTRY.copy()` + per-channel filtering.

**`locks.py` (new):** redis `SET NX EX` turn lock (adapt to `redis_manager`'s client):

```python
@contextmanager
def turn_lock(channel_id: str, timeout: int = 120):
    key, token = f"agent-turn:{channel_id}", uuid4().hex
    acquired = redis_manager.client.set(key, token, nx=True, ex=timeout)
    if not acquired:
        raise TurnBusy(channel_id)
    try:
        yield
    finally:                                  # compare-and-delete (Lua) — never release another turn's lock
        redis_manager.client.eval(_RELEASE_LUA, 1, key, token)
```

**`state/types.py` (new):** `AgentState` dataclass — `messages: list[dict]` (LiteLLM-flat), `pending_tool_calls`, `rounds: int`, `draft: DraftState | None`, `run_id`. Built per turn from the last ~30 `Message` rows (`author_agent` → `assistant`, `author_user` → `user` with `"{display_name}: "` prefix) + `AgentSession.memory`.

Tests: registry duplicate guard; describe() schema matches pydantic; lock mutual exclusion + token-safe release.

## §A1 UC1 — Q&A runtime (~2d)

**`tools/cortex_read.py` (new)** — three tools; interim facade until 00f Phase 4a:

```python
class QueryArgs(BaseModel):
    text: str
    type: EntityType | None = None
    doc_type: str | None = None
    client_id: UUID | None = None
    limit: int = Field(default=8, le=25)

class CortexQueryTool(DonnaTool):
    name = "cortex_query"
    description = ("Search company knowledge (meetings, emails, docs, tickets, people, "
                   "decisions). Metadata filters run before similarity. Results carry "
                   "source: URIs — cite them in answers.")
    args_model = QueryArgs
    def __init__(self, reader): self._reader = reader        # facade now, CortexService later

    def announce(self, args): return f"Searching cortex for “{args.text[:60]}”…"
    def run(self, args, ctx):
        rows = self._reader.query(workspace_id=ctx.workspace.id, **args.model_dump())
        return ToolResult(payload=[r.summary() for r in rows])
# ReadEntityTool(id, include_body=False) · GetContextTool(id, depth<=2) same shape.
```

**`prepare_context` macro-tool** (docupal `prepare_legal_context`
pattern, adopted 2026-06-12) — compiles the typical first-turn
sequence (resolve → query → read top hits) into ONE tool call;
parallel fan-out kills 3 loop rounds of latency on fresh topics:

```python
class PrepareContextArgs(BaseModel):
    topic: str                                    # "Acme payment terms"

class PrepareContextTool(DonnaTool):
    name = "prepare_context"
    description = ("Call FIRST when a conversation turns to a new topic or client. "
                   "Resolves named entities, searches, and reads the top hits in "
                   "parallel — returns one context digest with source: URIs. "
                   "After this, use focused tools (cortex_query/read_entity) for "
                   "follow-ups.")
    args_model = PrepareContextArgs
    timeout_s = 300                                # 3 parallel sub-calls + 3 body reads

    def announce(self, args): return f"Preparing context on “{args.topic[:60]}”…"

    def run(self, args, ctx):
        with ThreadPoolExecutor(max_workers=2) as pool:
            cards_f = pool.submit(self._resolve_names, args.topic, ctx)
            hits_f  = pool.submit(self._query, args.topic, ctx)
        cards, hits = cards_f.result(), hits_f.result()
        bodies = [self._read(h["id"], ctx) for h in hits[:3]]     # top hits, full bodies
        return ToolResult(payload={
            "entities": cards,                    # org/person/project cards w/ ids
            "results": hits,                      # snippets + source URIs
            "top_documents": bodies,              # the 3 most relevant, in full
        })
```

System prompt carries the docupal-style heuristic: *"new topic and no
context yet → `prepare_context`; targeted follow-ups → focused
tools."* Not a hard gate — a routing hint the model follows.

**TOC injection** (narrio pattern, adopted 2026-06-12) — for channels
bound to a client/project scope, the prompt builder injects the
scope's prompt-sized index (Phase 5 `render_index_for_prompt`, 00f) so
the agent reads the map before searching:

```python
def build_system_prompt(ctx: ToolContext, state: AgentState) -> str:
    base = IDENTITY + CITATION_RULES + TOOL_ROUTING_HINTS
    if scope := _channel_scope(ctx.channel):          # channel ↔ client/project binding
        base += f"\n\n== SCOPE INDEX ==\n{render_index_for_prompt(scope, max_chars=2500)}"
    if memory := ctx.agent_session.memory.get("summary"):
        base += f"\n\n== MEMORY ==\n{memory}"
    return base
```

Gated on Phase 5 (the renderer must exist); until then the branch is
simply never true.

```python
class CortexReadFacade:
    """INTERIM (decision 2026-06-12): ORM-direct, heads-only. Replace with
    CortexService when 00f Phase 4a lands — swap lives ONLY in factory.py."""
    def query(self, *, workspace_id, text, type=None, doc_type=None, client_id=None, limit=8):
        qs = CortexEntity.objects.filter(workspace_id=workspace_id, superseded_by__isnull=True)
        if type: qs = qs.filter(type=type)
        if doc_type: qs = qs.filter(extensions__doc_type=doc_type)
        if client_id: qs = qs.filter(client_id=client_id)
        return list(qs.filter(Q(title__icontains=text) | Q(extensions__icontains=text))
                      .order_by("-occurred_at")[:limit])     # keyword-only until RRF exists
```

**`nodes/conversation_agent.py` (new)** — router; one message kind per turn:

```python
class ConversationAgent:
    def __init__(self, llm: LLMProvider, registry: ToolRegistry, prompt_builder):
        self._llm, self._registry, self._prompt = llm, registry, prompt_builder

    def __call__(self, state: AgentState, ctx: ToolContext) -> AgentState:
        resp = self._llm.chat(
            messages=state.messages,
            system_prompt=self._prompt(ctx, state),          # identity + citation rules + memory + draft summary
            tools=self._registry.describe_all(),
            tool_choice="auto", temperature=0.3)
        if resp.tool_calls:
            state.messages.append({"role": "assistant", "content": "",
                                   "tool_calls": [tc.model_dump() for tc in resp.tool_calls]})
            state.pending_tool_calls = resp.tool_calls       # text content discarded — invariant
        else:
            state.messages.append({"role": "assistant", "content": resp.content})
            state.final_text, state.pending_tool_calls = resp.content, []
        return state
```

**`nodes/tool_dispatcher.py` (new):** for each pending call → `registry.get(name)` → `args_model.model_validate_json(arguments)` (validation error → tool message with the error, agent self-corrects) → **taint check** (reject if any tainted string flows into a `taint_safe=False` tool) → emit `agent.status` announce to `agent_run_group(run_id)` → **timeout-wrapped `run(args, ctx)`** (per-tool `timeout_s`, default 120, macro/delegating tools override to 600) → **taint stamp on result** (string fields that came from external sources get marked) → append `{"role": "tool", "tool_call_id": id, "content": json.dumps(result)}`. Announces go to the stream group only — **never** into `state.messages` (docupal's two-consecutive-assistant API trap).

```python
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout

# Tools that source external content — their string outputs get
# wrapped as Tainted before any downstream tool sees them. Maintained
# in one place so the policy is auditable.
EXTERNAL_CONTENT_TOOLS: set[str] = {
    "read_entity", "cortex_query", "prepare_context", "read_draft",
}

# Argument fields whose values, if they came from a tool result that
# was tainted, must NOT reach taint_safe=False tools. Maintained on
# args_model by field annotation (Tainted) — dispatcher walks them.

def _is_tainted(value) -> bool:
    return isinstance(value, str) and getattr(value, "_donna_tainted", False)

def _mark_tainted(value: str) -> str:
    # NewType is identity at runtime; smuggle a flag on a thin str subclass
    class _T(str):
        _donna_tainted = True
    return _T(value)

def dispatch_one(call, registry, ctx, state, run_id) -> dict:
    tool = registry.get(call.function.name)
    try:
        args = tool.args_model.model_validate_json(call.function.arguments)
    except ValidationError as e:
        return _tool_msg(call.id, {"error": "args_validation_failed", "detail": e.errors()})

    if not tool.taint_safe:
        for field_name, value in args.model_dump().items():
            if _is_tainted(value):
                return _tool_msg(call.id, {
                    "error": "tainted_input_rejected",
                    "tool": tool.name, "field": field_name,
                    "hint": ("This value came from external content (email/cortex/webhook). "
                             "Summarize or extract structured fields first, then call this tool "
                             "with the sanitized value.")})

    _broadcast_status(run_id, tool.announce(args))

    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(tool.run, args, ctx)
        try:
            result: ToolResult = fut.result(timeout=tool.timeout_s)
        except FutTimeout:
            return _tool_msg(call.id, {
                "error": "tool_timeout",
                "tool": tool.name, "timeout_s": tool.timeout_s,
                "hint": "Try a narrower query or break the request into smaller steps."})

    payload = result.payload
    if tool.name in EXTERNAL_CONTENT_TOOLS and isinstance(payload, dict):
        # mark all string leaves as tainted so downstream tools know
        payload = _walk_and_taint(payload)
    return _tool_msg(call.id, {"error": result.error} if result.error else payload)

def _tool_msg(tool_call_id, content) -> dict:
    return {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps(content)}
```

**Timeout policy in plain English:** ordinary read tools (cortex query, read entity) finish well under 2s; default 120s catches runaway provider latency without killing healthy calls. `PrepareContextTool` fans out three parallel sub-calls + reads three full documents → override to 300s. A future `research_subagent` tool spawning a nested loop → override to 600s. Dispatcher logs every timeout to structlog so eval can spot tools that drift.

**`graph.py` (new):** plain loop, no framework: entry (reset turn-locals) → agent → while pending and rounds < 6 → dispatcher → agent. Round-cap exhaustion → apologetic final text.

**`runner.py` + `donna/chat/tasks.py` (new):**

```python
@shared_task(bind=True, max_retries=3)
def run_agent_turn(self, channel_id: str, message_id: str) -> None:
    try:
        with turn_lock(channel_id):
            channel = Channel.objects.select_related("workspace").get(id=channel_id)
            session = channel.agent_sessions.first()
            ctx = ToolContext(channel.workspace, Message.objects.get(id=message_id).author_user,
                              channel, session)
            state = build_state(channel, session)
            registry = build_registry(channel=channel, draft_enabled=_draft_enabled(channel))
            state = run_graph(state, ctx, registry)          # streams status to agent-run group
            _persist_agent_message(channel, session, state.final_text)   # Message(author_agent=…)
            session.memory = update_memory(session.memory, state)        # A3 expands
            session.save(update_fields=["memory", "last_active_at"])
    except TurnBusy as exc:
        raise self.retry(exc=exc, countdown=5)
```

`_persist_agent_message` mirrors `ChannelService.send_message` broadcast shape (`chat.message.created` on `channel_group`) with `author_agent` set — per the services.py comment.

**Dispatch hook — `ChannelService.send_message` (edit):**

```python
# after Message persists, still inside @transaction.atomic
transaction.on_commit(lambda: maybe_dispatch_agent(message))

def maybe_dispatch_agent(message: Message) -> None:
    if message.author_agent_id is not None: return            # anti-loop
    session = message.channel.agent_sessions.first()
    if session is None: return
    is_dm = message.channel.kind == Channel.Kind.DIRECT
    mentioned = f"@{session.name.lower()}" in message.body.lower()   # interim until Phase 4a Mention model
    if is_dm or mentioned:
        run_agent_turn.delay(str(message.channel_id), str(message.id))
```

**Colleague-mode WebSockets (decision 2026-06-12):** the agent acts
like a teammate by emitting the **same events through the same groups
humans use** — no special client path needed for normal chat:

```python
# runner.py — wraps the whole turn
def _typing(channel, session, active: bool) -> None:
    async_to_sync(get_channel_layer().group_send)(
        channel_typing_group(channel.id),
        {"type": "chat.typing", "payload": {
            "author_agent": str(session.id), "name": session.name, "active": active}})

# turn start → _typing(active=True); heartbeat re-emit every ~5s while
# tools run (typing TTLs client-side like human typing); turn end →
# _typing(active=False) then the final Message broadcasts
# chat.message.created on channel_group — identical shape to a human
# message, author_agent set. FE renders Donna as just another member.
```

- **Typing**: `chat-channel-{id}-typing`, same event type humans
  produce; payload carries `author_agent` instead of user id.
- **Message**: `chat.message.created` on `channel_group` — the
  existing consumer already serializes `author_agent`.
- **Presence**: v1 static — FE lists the agent as an online member
  whenever `channel.agent_sessions` is non-empty (no presence-TTL
  machinery for agents).
- **`agent-run-{run_id}-tokens` group demoted to optional panel UI**
  (draft side-panel progress, tool announce lines). Normal chat
  surface never needs it. Token-streaming the final text stays
  possible there (`stream=True` final pass only — tool_calls are
  non-streaming, verified) but is config-gated, not default.

Tests: anti-loop; DM-always/channel-mention rules; lock serializes two concurrent turns; tool validation error round-trips as tool message; round-cap; facade heads-only; typing events fire start/stop around the turn and stop on failure (finally-guarded); agent message event shape identical to human message event minus author field.

## §A2 UC2 — Drafting (~2d; FinalizeDraft gated on 00f Phase 4a)

**`Document` migration (edit `donna/chat/models.py`):**

```python
class Document(TimestampsMixin, UserAuditMixin):             # existing fields kept
    class Status(models.TextChoices):
        DRAFTING = "drafting"; FINALIZED = "finalized"; ABANDONED = "abandoned"
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFTING)
    version = models.IntegerField(default=0)
    target_doc_type = models.CharField(max_length=32, blank=True, default="")   # DocType vocab
    finalized_entity_id = models.UUIDField(null=True, blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["channel"], condition=Q(status="drafting"),
            name="uq_one_active_draft_per_channel")]          # the cowork lock
```

**`tools/draft_tools.py` (new):** `CreateDraftTool(target_doc_type, title)` (IntegrityError on second active draft → friendly error), `ReadDraftTool`, `UpdateDraftSectionTool(instruction, expected_version)`, `FinalizeDraftTool(title)`:

```python
class UpdateDraftSectionTool(DonnaTool):
    # Drafter intentionally accepts tainted snippets — its whole job is
    # to weave retrieved context (which IS external content) into a
    # draft body. The DrafterNode prompt frames context_snippets as
    # data, not instructions. taint_safe is True because the tool
    # owns the sanitization contract internally.
    taint_safe = True
    timeout_s = 180                              # Sonnet pass on long bodies can take 60-120s

    def run(self, args, ctx):
        with transaction.atomic():
            draft = (Document.objects.select_for_update()
                     .get(channel=ctx.channel, status=Document.Status.DRAFTING))
            if args.expected_version != draft.version:
                return ToolResult.fail(f"draft at v{draft.version}, you expected v{args.expected_version} — re-read")
            out = self._drafter.revise(current=draft.body, instruction=args.instruction,
                                       context=args.context_snippets or [])
            draft.body, draft.version = out.markdown, draft.version + 1
            draft.save(update_fields=["body", "version", "updated_at"])
        _broadcast_doc_updated(ctx.channel, draft)            # chat.document.updated WS event
        return ToolResult(payload={"version": draft.version, "summary": out.summary})

class FinalizeDraftTool(DonnaTool):                           # NEEDS CortexService (00f 4a)
    taint_safe = True                            # writes the (already-drafted) body to cortex
    timeout_s = 240                              # linter + create_entity + embedding job kickoff

    def run(self, args, ctx):
        draft = Document.objects.get(channel=ctx.channel, status=Document.Status.DRAFTING)
        svc = CortexService(current_user=ctx.user, company=ctx.workspace)
        verdict = svc.linter_check(type="doc", body_md=draft.body,
                                   extensions={"doc_type": draft.target_doc_type})
        if not verdict.ok:
            return ToolResult(payload={"rejected": verdict.codes})   # agent fixes + retries
        entity = svc.create_entity(type="doc", author="agent",
            source=f"donna://channel/{ctx.channel.id}/draft/{draft.id}",
            title=args.title or draft.title, body_md=draft.body,
            extensions={"doc_type": draft.target_doc_type})
        draft.status, draft.finalized_entity_id = Document.Status.FINALIZED, entity.id
        draft.save(update_fields=["status", "finalized_entity_id", "updated_at"])
        return ToolResult(payload={"entity_id": str(entity.id)})
```

**`nodes/drafter.py` (new):** `DrafterNode.revise(current, instruction, context) -> DraftOutput(markdown, summary)` — Sonnet via `LLMFactory.create`, `formatted_instructions=DraftOutput`; prompt in `prompts/drafter.py`.

**`tools/factory.py` (new):**

```python
def build_registry(*, channel: Channel, draft_enabled: bool) -> ToolRegistry:
    reader = CortexReadFacade()                # ← swap to CortexService(…) at 00f Phase 4a; ONLY line that changes
    reg = ToolRegistry()
    reg.register(CortexQueryTool(reader), ReadEntityTool(reader), GetContextTool(reader),
                 CortexResolveTool(reader), PrepareContextTool(reader))
    if draft_enabled:
        reg.register(CreateDraftTool(), ReadDraftTool(),
                     UpdateDraftSectionTool(drafter=DrafterNode()), FinalizeDraftTool())
    return reg
```

Tests: partial-unique blocks second draft; member add/remove doesn't fork; version conflict path; finalize linter-reject loop; finalize writes entity + freezes; WS doc events.

## §A3 Memory + config + polish (~1d)

`update_memory`: rolling summary in `AgentSession.memory` (`{"summary": str, "facts": [...]}`), compacted by Haiku when > N turns; `AgentSession.config` honored — `model` override into `LLMFactory.create`, `tool_allowlist` filtering registry, system-prompt extra. Per-turn usage logging (LLMResponse.usage) → structlog. Eval hook: golden conversation fixtures replayed in tests.

### Branch-aware history compaction (openclaw pattern, adopted 2026-06-12)

Naive truncation ("keep last 30 messages") drops semantic continuity the moment a long debate goes one turn past the window — the agent forgets the decision rationale even though the decision text is still scrolled three messages above. openclaw's `agent-core` solves this with **branch-aware summarization**: chat history is bucketed by `(author, conversation-branch)` and old buckets get a one-paragraph Haiku digest instead of being dropped. Donna's `build_state` adopts the same shape — works particularly well in channels (vs DMs) where multiple humans interleave threads.

**`donna/chat/agents/state/builder.py` (new):**

```python
HISTORY_HARD_LIMIT = 30                          # verbatim window
COMPACTION_TRIGGER = 60                          # total messages → kick compaction
KEEP_VERBATIM_RECENT = 15                        # tail always kept raw

def build_state(channel: Channel, session: AgentSession) -> AgentState:
    qs = (Message.objects
          .filter(channel=channel, parent__isnull=True)        # top-level only; replies inline below
          .select_related("author_user", "author_agent", "parent")
          .order_by("-created_at")[:max(HISTORY_HARD_LIMIT, COMPACTION_TRIGGER)])
    rows = list(reversed(qs))                                  # chronological

    if len(rows) <= HISTORY_HARD_LIMIT:
        messages = [_to_litellm(r) for r in rows]
    else:
        # Split: older half summarized per branch; recent tail verbatim.
        split_at = len(rows) - KEEP_VERBATIM_RECENT
        older, recent = rows[:split_at], rows[split_at:]
        messages = [_branch_summary_msg(older, channel, session)] + [_to_litellm(r) for r in recent]

    return AgentState(
        messages=messages,
        pending_tool_calls=[],
        rounds=0,
        draft=_load_active_draft(channel),
        run_id=uuid4().hex,
    )

def _branch_summary_msg(older: list[Message], channel: Channel, session: AgentSession) -> dict:
    """One synthetic system message that compresses N old turns into a
    branch-aware digest. Cached on AgentSession.memory['branch_digest']
    keyed by the highest message id summarized — only recomputed when
    new old-tier messages appear."""
    high_id = str(older[-1].id)
    cached = session.memory.get("branch_digest", {})
    if cached.get("up_to_id") == high_id:
        return {"role": "system", "content": cached["text"]}

    branches: dict[tuple[str, str], list[Message]] = {}        # (author_label, thread_root_id) → messages
    for m in older:
        author_label = m.author_user.display_name if m.author_user_id else f"Donna({session.name})"
        thread_root = str(m.parent_id or m.id)
        branches.setdefault((author_label, thread_root), []).append(m)

    chunks = []
    for (author, thread), msgs in branches.items():
        first_ts = msgs[0].created_at.date().isoformat()
        joined = "\n".join(f"- {m.body[:200]}" for m in msgs)
        chunks.append(f"### {author} (thread {thread[:8]}, {first_ts}, {len(msgs)} msgs)\n{joined}")

    bulk = "\n\n".join(chunks)
    llm = LLMFactory.create("haiku")
    digest = llm.chat(
        messages=[{"role": "user", "content": bulk}],
        system_prompt=(
            "Summarize the following chat history bucketed by author and thread. "
            "Keep decisions, named entities, and unresolved questions verbatim. "
            "Drop chitchat. Output one short paragraph per bucket. Plain prose, no markdown headers."),
        temperature=0.2,
    ).content

    text = f"== EARLIER CONVERSATION (compacted, branch-aware) ==\n{digest}"
    session.memory["branch_digest"] = {"up_to_id": high_id, "text": text}
    session.save(update_fields=["memory", "updated_at"])
    return {"role": "system", "content": text}

def _to_litellm(m: Message) -> dict:
    if m.author_agent_id is not None:
        return {"role": "assistant", "content": m.body}
    label = m.author_user.display_name if m.author_user_id else "Unknown"
    return {"role": "user", "content": f"{label}: {m.body}"}
```

**Plain English:** when the channel has hundreds of messages, Donna doesn't read all of them and doesn't forget the early ones. The middle gets compressed into a "what happened earlier, who said what to whom" paragraph — bucketed so Alice's discussion of payment terms stays separate from Bob's discussion of timeline. The last 15 messages are always raw verbatim. The digest is cached on `AgentSession.memory` keyed by the last summarized message id, so the same compaction cost is paid once, not on every turn.

**Tuning knobs:**
- `HISTORY_HARD_LIMIT` (30) — below this, no compaction; flat list works fine.
- `COMPACTION_TRIGGER` (60) — when we even bother fetching/digesting old turns. Cheap default.
- `KEEP_VERBATIM_RECENT` (15) — the tail. Should match how many messages a human glances at when entering a chat.
- Bucket key (author, thread) — for projects with rich thread reply trees use thread root; for flat DMs use just author.

**Tests:** flat-channel under limit → no compaction (no LLM call); flat-channel over trigger → exactly one Haiku call, digest cached on session.memory; second turn after digest cached → zero LLM compaction calls (cache hit); new message at the tail → recent slice rolls, digest unchanged; old-tier message appended (rare — backfill) → cache invalidated, digest recomputed; multi-author channel → buckets reflect (author, thread) split.

### Query-path cache (decision 2026-06-12 — prod-grade RAG audit gap)

Hot read paths repeat at scale: same question typed in two channels, same entity-name resolved across turns, same classifier verdict on every variant of "draft the SOW". A thin Redis layer in front of the three expensive read-path steps cuts 60–80% of LLM hops on repeat traffic without changing any business logic. Lives in `donna/core/cortex/cache.py`; tools opt in per call site.

**`donna/core/cortex/cache.py` (new):**

```python
import hashlib, json, pickle
from typing import Any, Callable
from donna.core.redis_manager import redis_manager

def _key(prefix: str, *parts: str) -> str:
    h = hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]
    return f"cortex:{prefix}:{h}"

class QueryCache:
    """Read-path cache. Three namespaces; each TTL'd independently.
    Keys are workspace-scoped to prevent cross-tenant leakage."""

    @staticmethod
    def embed_get(workspace_id: str, text: str) -> bytes | None:
        raw = redis_manager.client.get(_key("embed", workspace_id, text))
        return raw if raw else None                          # bytes ready for pgvector cast

    @staticmethod
    def embed_set(workspace_id: str, text: str, vec_bytes: bytes) -> None:
        redis_manager.client.set(_key("embed", workspace_id, text), vec_bytes, ex=86400)

    @staticmethod
    def rewrite_get(workspace_id: str, text: str, recent_turns: str) -> str | None:
        raw = redis_manager.client.get(_key("rewrite", workspace_id, text, recent_turns))
        return raw.decode() if raw else None

    @staticmethod
    def rewrite_set(workspace_id: str, text: str, recent_turns: str, rewritten: str) -> None:
        redis_manager.client.set(_key("rewrite", workspace_id, text, recent_turns),
                                 rewritten, ex=3600)

    @staticmethod
    def classify_get(workspace_id: str, text: str) -> dict | None:
        raw = redis_manager.client.get(_key("cls", workspace_id, text))
        return json.loads(raw) if raw else None              # {"doc_type": str, "conf": float}

    @staticmethod
    def classify_set(workspace_id: str, text: str, verdict: dict) -> None:
        redis_manager.client.set(_key("cls", workspace_id, text), json.dumps(verdict), ex=86400)
```

**Wire-in sites:**

- `prepare_context` macro-tool — wrap the rewrite step:
  ```python
  recent = "|".join(state.messages[-2:])
  cached = QueryCache.rewrite_get(ctx.workspace.id, args.text, recent)
  if cached: return cached
  rewritten = self._llm.chat(...).content
  QueryCache.rewrite_set(ctx.workspace.id, args.text, recent, rewritten)
  ```
- `CortexReadFacade.query` (and later `CortexService.query`) — wrap embedding:
  ```python
  vec = QueryCache.embed_get(workspace_id, text) or self._embed_and_cache(workspace_id, text)
  ```
- Classifier ladder rung A/B (00f Phase 0/4) — cache the verdict by (text, workspace), invalidated whenever the workspace retrains its B+ LogReg model (`cache.delete_pattern("cortex:cls:{workspace_id}:*")` on retrain).

**TTL rationale:** embedding model + text → deterministic, 24h is conservative (only bumps when embedding model upgrades — invalidate the prefix on deploy). Rewrite depends on recent conversation turns → 1h matches typical chat-session length. Classifier verdict drifts as labels grow → 24h, plus explicit purge on retrain.

**Cache stampede guard:** for hot keys (workspace-default queries), the `embed_get`/`set` pair races on concurrent misses. Acceptable for v1 — duplicate embed calls cost cents. Add `redis_manager.client.set(..., nx=True)` lock if `embed_set` shows >1% duplicate rate.

**Tests:** miss→set→hit round-trips for all three namespaces; cross-workspace isolation (workspace A's cached query never returned to workspace B); TTL respected (mock time, assert expiry); classifier-retrain purge invalidates only that workspace's `cls:*` keys.

## §A4 Phase map + effort

| Phase | Effort | External dependency |
|---|---|---|
| A0 — foundations (tools base + `Tainted` + `timeout_s` + freezable registry, lock, state) | ~1d | none |
| A1 — Q&A runtime (graph, dispatch hook with taint-check + timeout-wrap, colleague-mode WS) | ~2d | none (interim `CortexReadFacade`) |
| A2 — drafting (Document lifecycle, draft tools, finalize; `taint_safe=True` overrides on Update/Finalize) | ~2d | `FinalizeDraftTool` + facade→`CortexService` swap gated on 00f Phase 4a |
| A3 — memory (branch-aware compaction), config, usage logging, query-path cache, eval fixtures | ~1d | none |
| **Total** | **~6d** | |

### Defense-in-depth posture (added 2026-06-12)

A0 lands four orthogonal protections, none of which depend on the others — failure of any one still leaves the agent operational:

| Layer | Threat blocked | Code site |
|---|---|---|
| Type-level taint marker | Indirect prompt injection via cortex/email/webhook content reaching shell/url-fetch tools | `tools/base.py` Tainted + dispatcher `_is_tainted` check |
| Frozen registry | Runtime tool injection from compromised dependency or skill loader | `tools/registry.py` `freeze()` + `apps.py ready()` |
| Per-tool timeout | One slow/hung tool stalling the whole turn | `tools/base.py` `timeout_s` + dispatcher `ThreadPoolExecutor` wrap |
| Turn lock (Redis SET NX EX + Lua release) | Concurrent dispatches for one channel double-processing | `locks.py` |

Plain English: the agent has four locked doors between an attacker and the dangerous stuff. Each door is small (5–30 LOC), independently testable, independently auditable. If we miss one, the other three still hold.

## Implementation verification checklist (run per phase)

1. **Tests green in the container** (host FS mount broken — same as
   00i §8): `docker exec donna-server bash -lc "cd /opt/donna &&
   DATABASE_HOST=donna-database uv run python -m django test
   donna.chat"`.
2. **Anti-loop verified live**: agent message in a DM never triggers a
   second turn (watch worker logs for `run_agent_turn` re-entry).
3. **WS parity**: agent `chat.message.created` event payload is
   byte-shape-identical to a human message event except the author
   field; typing start/stop wraps the turn even on task failure.
4. **Spec/plan sync**: comm-platform plan Phases 3.5/3.6 tick when
   A1/A2 land; 00f Phase 7 row updates when the facade→CortexService
   swap happens.

### Cross-doc adoptions logged (2026-06-12 openfang + openclaw study)

| Pattern | Source | Lives in | Sibling impact |
|---|---|---|---|
| Tainted type marker on tool I/O | openfang `openfang-runtime` (TaintSink) | 00j §A0 + dispatcher | 00k NOW #2 upgraded from prompt-only to type-level |
| `ToolRegistry.freeze()` post-boot | openfang `openfang-skills` | 00j §A0 | 00k NOW #3 new entry |
| Per-tool `timeout_s` ClassVar | openfang `openfang-runtime` (tiered timeouts) | 00j §A0 + dispatcher + Prepare/Update/Finalize overrides | 00k NOW #4 new entry |
| Branch-aware compaction in `build_state` | openclaw `agent-core` session-repo | 00j §A3 | 00k NOW #5 new entry |

### Out-of-scope adoption (logged here, edit deferred)

**Connector doctor / migration hooks** (openclaw `plugin-sdk` doctor contract): every connector declares `detect_stale(connection) -> Repair | None` + `repair(connection)`; Celery beat sweeps nightly, auto-fixes expired tokens, renamed scopes, drifted webhook URLs. **Lives in** `server/plans/05-integration-architecture.md` (new "Connector health & migrations" subsection) + `08-connection-pattern.md` (protocol method addition). Not edited here — connector framework is outside 00j's surface. Flagged for next integration-plan revision.

## Glossary

- **turn** — one dispatched agent invocation for one inbound message.
- **run** — a turn's streaming identity (`agent-run-{run_id}-tokens`).
- **announce** — user-facing tool status line; goes to the run group,
  never into LLM history.
- **draft lock** — the partial unique constraint: one
  `status=drafting` Document per channel.
- **tainted** — string output from a tool whose `name` is in
  `EXTERNAL_CONTENT_TOOLS`; cannot flow into a tool with
  `taint_safe = False`.
- **frozen registry** — `ToolRegistry.freeze()` called at boot end;
  later `register()` raises `RegistryFrozenError`.
- **per-tool timeout** — `DonnaTool.timeout_s` ClassVar; dispatcher
  wraps `run()` in a thread future with that wall.
- **branch digest** — Haiku-summarized bucket of old chat history
  keyed by `(author, thread)`; cached on `AgentSession.memory`.
