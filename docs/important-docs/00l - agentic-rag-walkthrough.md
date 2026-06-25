# Agentic RAG Walkthrough — one question, every gear visible

> **Audience:** developers (and future-you) learning how Donna
> understands a user's question and answers it — the full trace from
> a chat message to a cited answer, with the plain-English reasoning,
> a diagram, **and the code** for every step.
>
> **Status:** captured 2026-06-12 from the architecture education
> session. Code annotations: **(exists)** = in the repo today,
> **(00j)** = target-state from the agent handbook, **(00f/00i)** =
> target-state from the silver plan/handbook.
>
> **Contents:** the worked example (steps 0–5, reasoning + diagrams +
> code) · the takeaway tables · **Appendix: the 10 classic
> query-understanding techniques as code** (intent classification,
> contextualization, decomposition, expansion, HyDE, step-back,
> temporal parsing, entity linking, CRAG) with Donna slots + build
> triggers · **Field study:** how docupal (retrieval-maximalist,
> Qdrant 5-vector) and narrio (scope-minimalist, context-stuffing)
> solve the same problem, what Donna adopted (macro-tool, TOC
> injection, pgvector recall ladder), and the anti-patterns.
>
> **Companions:** [`00j`](./00j%20-%20agent-implementation-reference.md)
> agent handbook · [`00k`](./00k%20-%20multi-agent-architecture.md)
> multi-agent patterns · [`00i`](./00i%20-%20silver-implementation-reference.md)
> silver handbook · [`00f`](./00f%20-%20silver-completion-plan.md)
> master plan.

**The thesis this walkthrough demonstrates:** classic RAG built query
understanding as pipeline stages (intent classification, query
decomposition, filter extraction, expansion). Agentic systems
collapsed most of that into the tool-calling loop — the LLM performs
those stages implicitly *because the tool schemas make it possible*.
The engineering work is designing schemas, descriptions, and the
query engine so the model's natural behavior produces the stages.

---

## The setup

Maria (project manager) DMs Donna:

> **Maria:** "hey, what did we agree with Acme about payment terms? I think it was in a meeting with Ada last month"

Donna's silver layer already contains (from connectors, weeks ago):
- a `meeting` entity — "Acme — Phoenix contract review", May 21, attendees Ada (acme.com) + Maria, filed under `clients/acme/projects/phoenix/meetings/2026/05/`
- a `doc` entity — `doc_type: contract`, the Phoenix contract v2, same scope
- an `org` entity — "Acme", `email_domains: ["acme.com"]`
- a `person` entity — "Ada Lovelace"

---

## Step 0 — plumbing (no AI yet)

```
Maria hits Enter
   │
   ▼
ChannelService.send_message()         persists Message row
   │  on_commit
   ▼
maybe_dispatch_agent(message)
   │  author_agent? no → not a bot loop ✓
   │  channel.kind == DIRECT → DM with Donna → always respond ✓
   ▼
Celery: run_agent_turn(channel_id, message_id)
   │  acquire redis lock "agent-turn:{channel}"   ← only one turn at a time
   │  emit chat.typing (Donna starts "typing…")
   ▼
build AgentState: last ~30 messages from this DM → model-readable history
```

Nothing intelligent happened yet. Pure Django + Celery + WebSockets.

**`donna/chat/services.py` (exists, + one 00j line):**

```python
@staticmethod
@transaction.atomic
def send_message(*, channel, sender_user, body, client_msg_id=None) -> Message:
    message = Message.objects.create(
        channel=channel, author_user=sender_user, body=body)
    ChannelService._broadcast(channel_group(channel.id), {
        "type": "chat.message.created", "payload": _serialize_message(message)})
    transaction.on_commit(lambda: maybe_dispatch_agent(message))   # ← 00j: the ONE new line
    return message
```

**`donna/chat/tasks.py` (00j) — the gatekeeper:**

```python
def maybe_dispatch_agent(message: Message) -> None:
    if message.author_agent_id is not None:          # anti-loop: Donna never answers Donna
        return
    session = message.channel.agent_sessions.first()
    if session is None:                              # no agent in this channel
        return
    is_dm = message.channel.kind == Channel.Kind.DIRECT
    mentioned = f"@{session.name.lower()}" in message.body.lower()
    if is_dm or mentioned:                           # Maria's DM → always
        run_agent_turn.delay(str(message.channel_id), str(message.id))
```

`on_commit` matters: without it, the Celery worker could grab the task
before Postgres commits and find **no message row**. Classic
ghost-task bug, killed by one wrapper.

---

## Step 0.5 — the turn starts: lock, typing, state

**`donna/chat/tasks.py` (00j):**

```python
@shared_task(bind=True, max_retries=3)
def run_agent_turn(self, channel_id: str, message_id: str) -> None:
    try:
        with turn_lock(channel_id):                          # one turn per channel, ever
            channel = Channel.objects.select_related("workspace").get(id=channel_id)
            session = channel.agent_sessions.first()
            trigger = Message.objects.get(id=message_id)
            ctx = ToolContext(workspace=channel.workspace, user=trigger.author_user,
                              channel=channel, agent_session=session)
            _typing(channel, session, active=True)           # Donna starts "typing…"
            try:
                state = build_state(channel, session)
                registry = build_registry(channel=channel,
                                          draft_enabled=_draft_enabled(channel))
                state = run_graph(state, ctx, registry)      # ← the loop, below
                _persist_agent_message(channel, session, state.final_text)
            finally:
                _typing(channel, session, active=False)      # even on crash
    except TurnBusy as exc:
        raise self.retry(exc=exc, countdown=5)               # second turn queues politely
```

**`donna/chat/agents/locks.py` (00j)** — the lock that makes "many
members, one writer" true:

```python
@contextmanager
def turn_lock(channel_id: str, timeout: int = 120):
    key, token = f"agent-turn:{channel_id}", uuid4().hex
    if not redis_manager.client.set(key, token, nx=True, ex=timeout):
        raise TurnBusy(channel_id)
    try:
        yield
    finally:        # Lua compare-and-delete: never release someone else's lock
        redis_manager.client.eval(_RELEASE_LUA, 1, key, token)
```

**`build_state` (00j)** — turning DB rows into what the model sees:

```python
def build_state(channel, session) -> AgentState:
    rows = (channel.messages.select_related("author_user", "author_agent")
            .order_by("-created_at")[:30])[::-1]            # oldest first
    messages = []
    for m in rows:
        if m.author_agent_id:
            messages.append({"role": "assistant", "content": m.body})
        else:
            messages.append({"role": "user",
                             "content": f"{m.author_user.display_name}: {m.body}"})
    return AgentState(messages=messages, run_id=uuid4().hex)
```

At this point `state.messages` ends with:

```json
{"role": "user", "content": "Maria: hey, what did we agree with Acme about payment terms? I think it was in a meeting with Ada last month"}
```

---

## Step 1 — turn 1: the model reads the question

The agent loop starts. The model receives: system prompt (identity,
"cite source: URIs", tool list with descriptions) + chat history +
Maria's message.

Model's reasoning, plain English:

> *"Maria asks about an agreement. I don't know it — I must search. What do I actually know from her sentence?*
> - *topic: payment terms*
> - *counterparty: Acme — that's a client name, not an ID. I shouldn't guess an ID.*
> - *probably said in a meeting*
> - *person involved: Ada*
> - *timeframe: 'last month' — today is June 12, so roughly May.*
>
> *First I need Acme's actual identity in the system."*

📖 **What just happened, in textbook terms:** the model performed
**contextualization** (read history — if Maria had said "what did
*she* say", the history resolves "she" = Ada), **intent detection**
(this needs retrieval, not chitchat), and **filter extraction**
(pulled client / type / person / date constraints out of casual
English). No pipeline code did this — the model did, because the tool
schema *invites* it.

**`donna/chat/agents/nodes/conversation_agent.py` (00j)** calling
**`donna/core/llm/provider.py` (exists)**:

```python
class ConversationAgent:
    def __call__(self, state: AgentState, ctx: ToolContext) -> AgentState:
        resp = self._llm.chat(                       # LLMProvider.chat — exists today
            messages=state.messages,
            system_prompt=self._prompt(ctx, state),  # identity + "cite source: URIs" + tool rules
            tools=self._registry.describe_all(),     # ← JSON schemas, generated below
            tool_choice="auto",
            temperature=0.3)
        if resp.tool_calls:                          # LLMResponse.tool_calls — exists
            state.messages.append({"role": "assistant", "content": "",
                "tool_calls": [tc.model_dump() for tc in resp.tool_calls]})
            state.pending_tool_calls = resp.tool_calls
        else:
            state.messages.append({"role": "assistant", "content": resp.content})
            state.final_text, state.pending_tool_calls = resp.content, []
        return state
```

Where do those `tools=` schemas come from? **Nobody writes JSON by
hand** — pydantic generates them:

```python
# donna/chat/agents/tools/base.py (00j)
class DonnaTool(ABC):
    def describe(self) -> dict:
        return {"type": "function", "function": {
            "name": self.name,
            "description": self.description,        # ← the "retrieval prompt"
            "parameters": self.args_model.model_json_schema()}}   # pydantic → JSON Schema
```

The model returns (raw `LLMResponse.tool_calls`) — a tool call and
nothing else (one message kind per turn):

```json
[{"id": "toolu_01", "type": "function",
  "function": {"name": "cortex_resolve",
               "arguments": "{\"name\": \"Acme\", \"kind\": \"org\"}"}}]
```

The plain-English reasoning happens **inside the model** — the code's
only job was handing it history + schemas and reading back which
schema it filled.

---

## Step 2 — dispatcher executes the resolve (deterministic)

```
ToolDispatcher
   │  validate args against pydantic schema ✓
   │  emit announce → side panel: "Resolving 'Acme'…"
   ▼
tool.run(args, ctx)                    ctx = workspace, user, channel
   │  SQL: org rows WHERE workspace=Maria's  ← tenancy enforced HERE,
   │       AND alias/name matches "Acme"        not in the prompt
   ▼
returns: {id: "f47ac…", type: "org", title: "Acme",
          relationship: "client", domains: ["acme.com"]}
```

📖 **Entity linking** — the one stage we keep deterministic. The model
never invents UUIDs; it asks.

**`donna/chat/agents/nodes/tool_dispatcher.py` (00j):**

```python
class ToolDispatcher:
    def __call__(self, state: AgentState, ctx: ToolContext) -> AgentState:
        for call in state.pending_tool_calls:
            tool = self._registry.get(call.function.name)
            try:
                args = tool.args_model.model_validate_json(call.function.arguments)
            except ValidationError as exc:           # bad args → model self-corrects next turn
                result = ToolResult.fail(f"invalid arguments: {exc}")
            else:
                self._announce(ctx, state.run_id, tool.announce(args))  # side-panel only
                result = tool.run(args, ctx)         # ← tenancy enforced inside
            state.messages.append({                  # LLM-facing result
                "role": "tool", "tool_call_id": call.id,
                "content": json.dumps(result.payload if not result.error
                                      else {"error": result.error}, default=str)})
        state.pending_tool_calls = []
        state.rounds += 1
        return state
```

**The resolve tool itself (00j — the `cortex_resolve` addition):**

```python
class ResolveArgs(BaseModel):
    name: str
    kind: Literal["org", "person", "project"] | None = None

class CortexResolveTool(DonnaTool):
    name = "cortex_resolve"
    description = ("Resolve a company/person/project NAME to its entity card with the "
                   "real id. Always resolve before filtering by client_id — never guess ids.")
    args_model = ResolveArgs

    def run(self, args, ctx):
        qs = CortexEntity.objects.filter(
            workspace_id=ctx.workspace.id,                    # ← the tenant wall, in code
            type__in=[args.kind] if args.kind else ["org", "person", "project"],
            superseded_by__isnull=True,
        ).filter(Q(title__iexact=args.name) |
                 Q(extensions__cross_workspace_aliases__contains=[args.name]))
        return ToolResult(payload=[{
            "id": str(e.id), "type": e.type, "title": e.title,
            "relationship": e.extensions.get("relationship"),
        } for e in qs[:5]])
```

After this, `state.messages` has grown by two entries:

```json
{"role": "assistant", "content": "", "tool_calls": [{"id": "toolu_01", ...cortex_resolve...}]},
{"role": "tool", "tool_call_id": "toolu_01",
 "content": "[{\"id\": \"f47ac...\", \"type\": \"org\", \"title\": \"Acme\", \"relationship\": \"client\"}]"}
```

Loop check in **`graph.py` (00j)** — pending consumed, rounds=1 < 6 →
back to the agent node:

```python
def run_graph(state, ctx, registry) -> AgentState:
    agent, dispatcher = ConversationAgent(...), ToolDispatcher(registry)
    state = agent(state, ctx)
    while state.pending_tool_calls and state.rounds < MAX_ROUNDS:   # = 6
        state = dispatcher(state, ctx)
        state = agent(state, ctx)
    if state.final_text is None:                    # round-cap exhausted
        state.final_text = "I dug around but couldn't finish — mind rephrasing?"
    return state
```

---

## Step 3 — turn 2: the real search

Model reasoning:

> *"Got Acme's id. Now search meetings about payment terms, scoped to Acme, around May."*

```json
{"name": "cortex_query", "arguments":
  "{\"text\": \"payment terms agreement\", \"type\": \"meeting\",
    \"client_id\": \"f47ac...\", \"occurred_after\": \"2026-05-01\", \"limit\": 8}"}
```

📖 The model just *authored a structured query* from natural language —
the **self-query** pattern. The schema told it what's filterable; it
filled the slots.

Inside the query engine (pure SQL, no AI):

```
                 ┌─ metadata filters FIRST ──────────────────┐
all entities ──► │ workspace = Maria's    (tenant wall)      │
                 │ superseded_by IS NULL  (current versions) │
                 │ type = meeting                            │
                 │ client_id = f47ac…                        │
                 │ occurred_at ≥ May 1                       │
                 └──────────────┬────────────────────────────┘
                                ▼  maybe 14 rows survive out of 50,000
                 ┌── three channels rank those 14 ───────────┐
                 │ keyword:  "payment terms" in title/body   │
                 │ vector:   embedding similarity to query   │
                 │ graph:    entity_refs containing Ada      │
                 └──────────────┬────────────────────────────┘
                                ▼
                 RRF fusion → authority + recency tiebreak
                                ▼
                 #1  meeting "Acme — Phoenix contract review" (May 21)
                 #2  meeting "Acme weekly sync" (May 7)
```

📖 **Metadata-first, similarity-second.** Filters shrink 50k rows to 14
*before* any vector math. Similarity then ranks survivors. Cheap,
precise, and the tenant wall is structural.

**`donna/cortex/services.py` (00f Phase 4a):**

```python
class CortexService(BaseService):
    def query(self, *, text, type=None, doc_type=None, client_id=None,
              occurred_after=None, limit=10) -> list[CortexEntity]:
        q_embedding = self.embedder.embed(text)                 # BGE-small, local
        return CortexEntity.objects.raw(RRF_SQL, {
            "ws": self.company.id, "type": type, "doc_type": doc_type,
            "client": client_id, "after": occurred_after,
            "q": q_embedding, "text": text, "k": limit})
```

```sql
-- the metadata-first engine (00i §5c)
WITH filtered AS (                                   -- ① filters BEFORE any similarity
  SELECT id FROM cortex_entities
  WHERE workspace_id = %(ws)s AND superseded_by IS NULL
    AND (%(type)s   IS NULL OR type = %(type)s)
    AND (%(client)s IS NULL OR client_id = %(client)s)
    AND (%(after)s  IS NULL OR occurred_at >= %(after)s)
),                                                   -- 50,000 rows → 14
vec AS (SELECT id, row_number() OVER                 -- ② rank survivors, 3 ways
          (ORDER BY doc_embedding <=> %(q)s) AS rk FROM filtered JOIN ...),
kw  AS (SELECT id, row_number() OVER
          (ORDER BY ts_rank(tsv, plainto_tsquery(%(text)s)) DESC) AS rk FROM ...),
gr  AS (SELECT id, row_number() OVER (...) AS rk
          FROM ... WHERE entity_refs @> %(ref_ids)s)
SELECT id, SUM(1.0/(60+rk)) AS rrf                   -- ③ Reciprocal Rank Fusion
FROM (SELECT * FROM vec UNION ALL SELECT * FROM kw UNION ALL SELECT * FROM gr) c
GROUP BY id
ORDER BY rrf DESC LIMIT %(k)s;                       -- ④ + authority/recency tiebreak
```

The tool wraps rows into compact summaries — **never full bodies**
(context is a budget):

```python
def run(self, args, ctx):
    rows = self._reader.query(workspace_id=ctx.workspace.id, **args.model_dump())
    return ToolResult(payload=[{
        "id": str(e.id), "title": e.title, "type": e.type,
        "occurred_at": e.occurred_at.isoformat(), "source": e.source,
        "snippet": e.load_body()[:300],
    } for e in rows])
```

---

## Step 4 — turn 3: read, judge, dig deeper

Tool results return as compact summaries (title, date, snippet,
`source:` URI). Model reasoning:

> *"#1 is a contract-review meeting with Ada in the window. Snippet mentions payments. But a snippet isn't an agreement — read the full body."*

```json
{"name": "cortex_read_entity", "arguments": "{\"id\": \"meeting-uuid\", \"include_body\": true}"}
```

```python
class ReadEntityTool(DonnaTool):
    def run(self, args, ctx):
        e = CortexEntity.objects.filter(id=args.id,
                workspace_id=ctx.workspace.id).first()      # tenant check AGAIN —
        if e is None:                                       # an id from another workspace
            return ToolResult.fail("not found")             # just doesn't exist here
        payload = {"id": str(e.id), "title": e.title, "source": e.source,
                   "extensions": e.extensions}
        if args.include_body:
            payload["body"] = e.load_body()                 # lazy FileField read — exists
        return ToolResult(payload=payload)
```

Body comes back — rendered markdown, frontmatter + transcript. It
contains:

> *"…Ada agreed to net-30 with two installments, 40% on signature, 60% on delivery. Final wording to be confirmed in the revised contract."*

Model reasoning:

> *"Found the agreement — but it says 'to be confirmed in the revised contract.' The meeting is a proposal, not the final word. Is there a contract that confirms it? One more search."*

```json
{"name": "cortex_query", "arguments": {
    "text": "payment installments",
    "type": "doc", "doc_type": "contract",
    "client_id": "f47ac…", "limit": 3}}
```

→ finds Phoenix contract v2 (the **head** of its supersession chain —
v1 was automatically de-ranked when v2 arrived) → reads it → confirms
net-30, 40/60 split. **No code change between iterations** — the loop
in `run_graph` just keeps going: dispatcher, agent, dispatcher,
agent. Rounds: 4.

📖 Two textbook things happened invisibly: **query decomposition**
(one human question became three searches — but iteratively, each
informed by the last result, which a static pipeline can't do) and
**CRAG-style self-grading** ("this result isn't sufficient → refine
and retry" was just… the model reading and deciding). Also
**TYPE_AUTHORITY** quietly working: when meeting and contract talk
about the same fact, the contract (authority 95) outranks the meeting
(55) as the source of record.

---

## Step 5 — turn 4: the answer

No more tool calls — the `else` branch in `ConversationAgent` fires →
`state.final_text` set → `while` loop exits. The model emits:

> **Donna:** Net-30, paid in two installments — **40% on signature, 60% on delivery**. Agreed in the contract review with Ada on **May 21** and confirmed in the signed Phoenix contract (v2).
>
> Sources: `fathom://meeting/8821` · `gdrive://file/phoenix-contract-v2`

```
   │  typing off
   ▼
Message(author_agent=donna_session) saved
   │
   ▼
chat.message.created on channel group   ← same WS event a human produces
Maria sees it like any colleague's reply
   │
lock released — next turn may start
```

**Back in `tasks.py` (00j):**

```python
def _persist_agent_message(channel, session, text: str) -> None:
    message = Message.objects.create(
        channel=channel, author_agent=session, body=text)    # XOR constraint satisfied
    ChannelService._broadcast(channel_group(channel.id), {   # SAME event humans produce
        "type": "chat.message.created",
        "payload": _serialize_message(message)})             # serializer already handles
    session.last_active_at = timezone.now()                  # author_agent — exists
    session.save(update_fields=["last_active_at"])
```

`finally:` turns typing off, the context manager releases the redis
lock, Maria's client receives a perfectly ordinary
`chat.message.created` over the WebSocket it was already subscribed to.

---

## The whole thing on one screen

```
"what did we agree with Acme about payment terms?"
        │
        │  plumbing: dispatch, lock, typing, history
        ▼
┌─────────────────── AGENT LOOP (max 6 rounds) ───────────────────┐
│                                                                 │
│  T1  model: "Acme is a name, not an id"  → cortex_resolve       │   entity linking
│  T2  model: "now search, scoped+dated"   → cortex_query         │   intent + filter extraction
│           engine: SQL filters → 3 channels → RRF                │   metadata-first
│  T3  model: "snippet ≠ agreement, read"  → read_entity          │   self-grading
│      model: "meeting says 'see contract'" → query again → read  │   decomposition (iterative)
│  T4  model: enough evidence              → final text + sources │   grounded answer
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
typing off · message broadcast · lock released
```

## The one artifact that explains everything

The entire "intelligence" lives in ONE growing JSON array. Final
shape after the turn:

```
messages = [
  {role: user,      "Maria: hey, what did we agree with Acme about payment terms?…"},
  {role: assistant, tool_calls: [cortex_resolve(name="Acme")]},
  {role: tool,      "[{id: f47ac…, title: Acme, relationship: client}]"},
  {role: assistant, tool_calls: [cortex_query(text=…, client_id=f47ac…, type=meeting)]},
  {role: tool,      "[{title: 'Acme — Phoenix contract review', snippet: …}, …]"},
  {role: assistant, tool_calls: [cortex_read_entity(id=meeting-uuid, include_body=true)]},
  {role: tool,      "{body: '…net-30, two installments… confirmed in revised contract…'}"},
  {role: assistant, tool_calls: [cortex_query(type=doc, doc_type=contract, …)]},
  {role: tool,      "[{title: 'Phoenix contract v2', …}]"},
  {role: assistant, tool_calls: [cortex_read_entity(id=contract-uuid, …)]},
  {role: tool,      "{body: '…40% on signature, 60% on delivery, net-30…'}"},
  {role: assistant, "Net-30, two installments — 40% on signature… Sources: fathom://… gdrive://…"}
]
```

Every piece of code above exists to do exactly one of four things to
this array: **build it** (`build_state`), **extend it** (agent node,
dispatcher), **bound it** (lock, rounds cap, snippet truncation), or
**act on its last entry** (persist + broadcast). The model supplies
the judgment; the array is the entire shared memory of the turn; the
code is plumbing around it. That's agentic RAG in one data structure.

## The takeaway — where the classic stages went

There is **no "query understanding module"** anywhere in this trace.
No intent classifier ran, no decomposition pipeline, no
filter-extraction regex. Every classic stage happened anyway —
performed by the model, *because the tools made it possible*:

| Classic stage | Where it actually happened |
|---|---|
| Contextualization | history was just… in the context |
| Intent detection | model chose to search instead of chat |
| Entity linking | `cortex_resolve` tool (the ONE deterministic piece) |
| Filter extraction | model filled the typed `cortex_query` args |
| Metadata-first | inside the query engine, SQL before vectors |
| Decomposition | three searches, each informed by the previous |
| Result grading | model read, judged "not sufficient", retried |
| Grounding | citation rule in system prompt + `source:` URIs on every result |

The engineering work isn't building those stages — it's **designing
the tool schemas, descriptions, and the query engine so the model's
natural behavior produces them**. The tool `description` field is the
retrieval prompt. That's the whole shift from pipeline-RAG to
agentic-RAG in one example.

**What still deserves dedicated machinery:** entity ids (`cortex_resolve`
— models must never guess UUIDs), hard temporal parsing ("last
quarter" → date range, deterministically in the tool layer), a triage
tier when token bills demand it, and HyDE/multi-query inside the
query engine if eval shows vector recall lagging — invisible to the
agent.

---

# Appendix — the classic techniques as code

The punchline up front: **each of these famous techniques is a 10–30
line function wrapping one LLM call with structured output** (or no
LLM at all). The papers made them sound big; the code is tiny. Each
mechanism + the Donna-flavored code piece.

## 1. Intent classification — "what kind of request is this?"

Three implementations, cheap → expensive (same ladder philosophy as
the doc_type classifier in 00f):

```python
# Tier 1 — rules (free, catches the obvious)
GREETING_RX = re.compile(r"^(hi|hey|thanks|thank you|ok|cool|lol)\b", re.I)
DRAFT_RX    = re.compile(r"\b(draft|write up|prepare)\b.*\b(offer|contract|doc|spec)\b", re.I)

def rule_intent(text: str) -> str | None:
    if GREETING_RX.match(text) and len(text) < 40: return "chitchat"
    if DRAFT_RX.search(text):                       return "draft"
    return None                                     # unsure → escalate
```

```python
# Tier 2 — LLM classifier, structured output (Haiku, ~$0.0002/call)
class Intent(BaseModel):
    kind: Literal["chitchat", "retrieval", "draft", "action", "clarify"]
    confidence: float

def llm_intent(text: str, history_tail: str) -> Intent:
    return LLMFactory.create("anthropic/claude-3-5-haiku-latest").chat(
        messages=[{"role": "user",
                   "content": f"Recent chat:\n{history_tail}\n\nNew message:\n{text}\n\n"
                              "Classify the user's intent."}],
        temperature=0.0,
        formatted_instructions=Intent,      # ← pydantic forces the enum
    )
```

That's the whole technique. The `Literal` enum **is** the
classifier's label space.

**Donna slot:** the triage tier (00k "LATER" row) — sits in
`run_agent_turn` before the full loop:

```python
intent = rule_intent(trigger.body) or llm_intent(trigger.body, tail).kind
if intent == "chitchat":
    text = llm.chat(messages=state.messages, system_prompt=CHITCHAT_PROMPT).content
    return _persist_agent_message(channel, session, text)    # no tools, 1 cheap call
# else: full tool loop
```

Today: **the tool loop IS the classifier** — calling `cortex_query`
vs answering directly is the classification, done by Sonnet. Triage
just makes it cheaper.

## 2. Query rewriting / contextualization — "make the follow-up standalone"

Mechanism: one LLM call that fuses chat history + follow-up into a
self-contained query. Needed whenever something downstream embeds a
*single string* (a vector search can't see history).

```python
class Standalone(BaseModel):
    query: str

def condense(history_tail: str, followup: str) -> str:
    return llm.chat(
        messages=[{"role": "user", "content":
            f"Chat so far:\n{history_tail}\n\nFollow-up: \"{followup}\"\n\n"
            "Rewrite the follow-up as ONE standalone search query. Resolve every "
            "pronoun and reference ('he', 'that meeting', 'the second one')."}],
        temperature=0.0, formatted_instructions=Standalone,
    ).query
# "what did she say about it?" → "what did Ada say about the Phoenix payment terms"
```

**Donna slot:** mostly unnecessary — the agent has history in context
and writes `cortex_query.text` already-contextualized. Becomes
necessary if we ever expose a **non-agentic search box** (vault
search UI) over chat context.

## 3. Query decomposition — "one question → a plan of sub-queries"

Mechanism: structured output again — the LLM emits a typed plan; an
executor runs it (parallel where independent, sequential where one
feeds the next).

```python
class SubQuery(BaseModel):
    query: str
    depends_on: int | None = None      # index of a prior sub-query, or None

class Plan(BaseModel):
    sub_queries: list[SubQuery]

def decompose(question: str) -> Plan:
    return llm.chat(
        messages=[{"role": "user", "content":
            f"Question: {question}\n\nBreak into minimal sub-queries a search "
            "engine can answer. Mark dependencies."}],
        temperature=0.0, formatted_instructions=Plan)

def execute(plan: Plan, search) -> list:
    results: list = []
    for i, sq in enumerate(plan.sub_queries):
        text = sq.query
        if sq.depends_on is not None:                       # inject prior answer
            text = f"{text}\n(context: {summarize(results[sq.depends_on])})"
        results.append(search(text))
    return results
# "compare Acme and Beta payment terms" →
#   [SubQuery("Acme payment terms"), SubQuery("Beta payment terms")]  → parallel
```

**Donna slot:** **deliberately not built.** The agent loop decomposes
*adaptively* — search #2 is shaped by what search #1 returned, which
a precomputed plan can't do (the Maria example: the contract search
only existed because the meeting body said "see revised contract").
Explicit decomposition becomes worth it inside an
**orchestrator–workers** upgrade (00k trigger: cross-client
synthesis) — there the `Plan` is what the orchestrator hands to
parallel workers.

## 4. Query expansion — "widen the net"

Two flavors, different eras:

```python
# (a) Multi-query — LLM paraphrases, union via RRF (LangChain's MultiQueryRetriever)
class Variants(BaseModel):
    queries: list[str]                                  # 3-5

def multi_query(question: str, search) -> list:
    variants = llm.chat(
        messages=[{"role": "user", "content":
            f"Generate 4 diverse phrasings of this search query — vary vocabulary, "
            f"keep meaning: \"{question}\""}],
        temperature=0.8,                                # diversity wanted here!
        formatted_instructions=Variants).queries
    ranked_lists = [search(q) for q in [question, *variants]]
    return rrf_merge(ranked_lists)                      # same RRF we already have
```

```python
# (b) Pseudo-relevance feedback — BM25-era, zero LLM cost
def prf_expand(question: str, search) -> str:
    top = search(question)[:3]
    terms = top_tfidf_terms([d.body for d in top], k=5)   # sklearn, already a dep
    return f"{question} {' '.join(terms)}"                # re-search with enriched query
# "payment terms" → "payment terms installment net-30 invoice signature"
```

**Donna slot:** inside `CortexService.query`, engine-side, invisible
to the agent — flip on only if Phase 6 eval shows recall lagging.
Note RRF is shared infrastructure: the same fusion that merges our 3
channels merges expansion variants.

## 5. HyDE — "embed the answer, not the question"

Mechanism: questions and documents live in different regions of
embedding space ("what did we agree on payments?" looks nothing like
a contract clause). So: have the LLM **hallucinate a plausible
answer**, embed *that*, search with it. The hallucination's facts are
wrong; its *vocabulary and shape* are right — and shape is what
cosine similarity measures.

```python
def hyde_embedding(question: str, embedder) -> list[float]:
    fake_doc = llm.chat(
        messages=[{"role": "user", "content":
            f"Write a short plausible excerpt from an internal company document "
            f"that would answer: \"{question}\". Invent specifics freely."}],
        temperature=0.7).content
    return embedder.embed(fake_doc)        # ← embed the FAKE, search the REAL
# fake: "…parties agree to net-30 payment, 40% upon signature…"  ← perfect vector bait
```

**Donna slot:** same as expansion — a `CortexService.query` internal
option, one extra Haiku call per search. Try only after eval data; it
shines on short vague queries, wastes money on precise ones.

## 6. Step-back prompting — "zoom out first"

```python
class StepBack(BaseModel):
    abstract_question: str

def step_back(question: str) -> str:
    return llm.chat(
        messages=[{"role": "user", "content":
            f"\"{question}\" — what broader background question should be answered "
            "first to answer this well?"}],
        temperature=0.0, formatted_instructions=StepBack).abstract_question
# "why did Phoenix margins drop in March?" → "how are Phoenix project margins calculated?"
# → retrieve BOTH → answer with background + specifics
```

**Donna slot:** one sentence in the agent's system prompt ("for
analytical why-questions, first retrieve background, then specifics")
gets 90% of this free. Explicit version: skip.

## 7. Temporal parsing — the never-LLM stage

```python
# tools/temporal.py — deterministic, dateparser already solves it
import dateparser.search

def resolve_temporal(text: str, now: datetime) -> tuple[datetime, datetime] | None:
    hits = dateparser.search.search_dates(
        text, settings={"RELATIVE_BASE": now, "PREFER_DATES_FROM": "past"})
    ...  # "last month" → (2026-05-01, 2026-05-31); "last quarter" → (2026-01-01, 2026-03-31)
```

Why never LLM: models are *bad at date arithmetic* and the failure is
silent. **Donna slot:** the model passes the raw phrase
(`occurred_within: "last month"`) and the **tool layer** resolves it —
the schema carries a string field, `run()` converts deterministically.
The model extracts; code computes.

## 8. Post-retrieval grading (CRAG) — "is this junk?"

```python
class Grade(BaseModel):
    relevant: bool
    reason: str

def grade(question: str, doc_snippet: str) -> Grade: ...   # one Haiku call per doc

def corrective_search(question: str, search) -> list:
    docs = search(question)
    good = [d for d in docs if grade(question, d.snippet).relevant]
    if not good:                                           # all junk → rewrite + retry once
        return search(condense_rewrite(question))
    return good
```

**Donna slot:** already happens implicitly — the agent reads snippets
and decides to re-search (step 4 of the walkthrough was exactly
this). Explicit grading earns its cost only in **non-agentic** paths:
the Phase 6 eval harness uses precisely this shape to *measure*
retrieval (graded relevance → Recall@10).

## The decision table

| Technique | Lines of real code | Donna status | Trigger to build explicitly |
|---|---|---|---|
| Intent classification | ~25 | implicit in loop | token bills → triage tier (00k) |
| Contextualization | ~15 | free via history | non-agentic search UI appears |
| Decomposition | ~30 | implicit, adaptive | orchestrator–workers (cross-client synthesis) |
| Multi-query expansion | ~20 | not built | Phase 6 eval shows recall gap |
| PRF expansion | ~15 | not built | same, when LLM cost matters |
| HyDE | ~10 | not built | recall gap on short/vague queries |
| Step-back | 1 prompt line | add to system prompt now | — |
| Temporal parsing | ~20, no LLM | should be in tool layer from day one | **A1** |
| Entity linking | ~25 | `cortex_resolve` (this doc) | **A1** |
| CRAG grading | ~25 | implicit in loop | eval harness needs it explicitly (Phase 6) |

**The pattern across all ten:** structured output
(`formatted_instructions=PydanticModel`) turned every "technique"
into a typed function. Pre-2023 these were research papers;
post-structured-output they're utility functions. The architecture
decision isn't *how* to build them — it's **where**: agent-implicit
(free, adaptive), engine-internal (invisible, eval-gated), or
tool-layer-deterministic (dates, ids — never trust the model).

---

# Field study — how docupal and narrio answer the same question

*(2026-06-12 code exploration of the two sibling projects. Three
systems, three completely different answers to "how do we know what
the user means" — driven by **corpus shape**, not taste.)*

## Docupal — the retrieval-maximalist (vertical, static corpus)

One domain (Romanian law), one authoritative corpus (Civil Code),
rarely changes. Budget spent on **retrieval quality**, not query
understanding:

```
query ──► 5 parallel representations
            ├─ small_dense  384d   (cosine)
            ├─ medium_dense 768d   (cosine)
            ├─ large_dense  1024d  (cosine)
            ├─ colbert      128d   (late-interaction, token-level)
            └─ sparse BM42         (learned keyword weights)
          ──► Qdrant Query API prefetch → SERVER-SIDE fusion (RRF/DBSF)
```

Query understanding: **deliberately deleted** — the v10 comment in
`rag/civil_code/models.py:4` says decomposition was removed. Replaced
by (1) static tool-routing heuristics in the system prompt ("no
initial_analysis → call `prepare_legal_context`; targeted →
focused tools; commentary last-resort" — an authority hierarchy in
prompt text), and (2) the **macro-tool**: `prepare_legal_context(topic)`
parallelizes Civil Code + legislation searches and runs a Planner LLM
into one structured artifact — decomposition *compiled into a
composite tool*. Context accumulates in an event-sourced `Artifact`
log projected into the prompt each turn — elegant, but **unbounded**
(no context budget; long sessions will blow the window).

## Narrio — the scope-minimalist (everything is a deal)

Narrio barely does RAG, and that's the *correct* call for its shape:

- **Entity linking solved by URL.** Chat opens on a deal page →
  `context_type="deal", context_id=<uuid>` baked into the session →
  every tool pre-bound. The hardest query-understanding problem costs
  zero code because the UI answered it before the model ran.
- **Context-stuffing over retrieval.** ETL loads everything per deal;
  the system prompt carries a pre-computed **Table of Contents**
  (timeframe, patterns, activity index). The model reads the map
  first, then drills via tools (`search_activities` — pgvector
  BGE-small + HNSW, *optional*; `get_event_detail` /
  `get_full_activity` — progressive disclosure).
- **Batch agents ≠ chat agent.** Dashboard/Journey are not loops:
  typed state in, one structured-output call, result stored.
  Deal *ranking* is a deterministic weighted formula — no LLM where
  arithmetic suffices.

## The three-way table

| Technique | Docupal | Narrio | Donna |
|---|---|---|---|
| Intent detection | static prompt heuristics | absent — scope rules everything | implicit in loop; triage tier later |
| Entity linking | absent (corpus has no entities) | **free via URL scope** | `cortex_resolve` tool — no URL scope in chat |
| Decomposition | removed; macro-tool instead | absent; model plans | implicit, adaptive in loop |
| Expansion / HyDE | none — multi-vector replaces it | none | eval-gated, engine-side |
| Hybrid search | ★ 5-vector Qdrant, server fusion | single-vector pgvector, optional | 3-channel Postgres RRF, metadata-first |
| Metadata-first | basic point_type filters | deal_id pre-filter (structural) | first-class: SQL before similarity |
| Authority hierarchy | prompt text | n/a | TYPE_AUTHORITY table (enforced) |
| Context accumulation | artifact log, **unbounded** | TOC + progressive disclosure | snippets + rolling memory summary |
| Temporal | absent | absent | deterministic tool-layer |

## Adopted into Donna (2026-06-12)

1. **Macro-tool** → `prepare_context(topic)` in the 00j registry —
   parallel resolve + query + top-reads, one digest, kills 3
   first-turn loop rounds.
2. **TOC injection** → scope-bound channels get the Phase 5
   `render_index_for_prompt` projection in the system prompt
   (00f Phase 5 + 00j prompt builder). Second consumer of `_index.md`.
3. **Recall ladder, Postgres-translated** (00f Phase 7; decision:
   **stay and maximize vanilla pgvector** — Cloud must run on
   RDS-class Postgres, which carries pgvector incl.
   `sparsevec`/`halfvec` but NOT VectorChord/ParadeDB):
   - Rung 1: BM42 learned-sparse → `sparsevec(30522)` + HNSW
     `sparsevec_ip_ops` → 4th RRF channel.
   - Rung 2: ColBERT as **app-side MaxSim rerank** over RRF top-50
     (numpy, ~50 KB token matrix per entity cached at enrich) —
     pgvector has no multivector; don't add extensions for it.
   - Rung 3: cross-encoder `bge-reranker-v2-m3`, top-50 → top-5.
   - Each rung eval-gated; rungs 2/3 share the rerank slot.
   - pgvector type inventory for reference: `vector` (dense f32),
     `halfvec` (f16 — halves HNSW RAM at scale), `sparsevec`, `bit`.

## Anti-patterns observed (already dodged — keep dodging)

- **Unbounded context accumulation** (docupal's notebook) → rolling
  memory summary + compaction stays mandatory.
- **Engine forking per surface** (narrio's V1/V2 chat split) → one
  loop, one registry, gated per surface; never fork the loop.

**One sentence per system:** narrio scopes the question away before
the model runs; docupal compiles question-understanding into one fat
retrieval tool over a deep corpus; Donna resolves-then-filters
because its corpus is the only one that's horizontal, multi-tenant,
and alive. Same problem, three correct answers — **shape of the data
decides.**
