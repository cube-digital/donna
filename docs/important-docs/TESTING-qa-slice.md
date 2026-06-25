# Q&A test recipe — user-driven verification

> **Audience:** Rares running the post-execution test on the
> 2026-06-14 Q&A slice. Code delivered: P0 critical fixes, P1 bronze
> versioning, P4 CortexService, A1 agent runtime + dispatch hook.
>
> **What this verifies:** message in a DM with Donna → Donna queries
> cortex → Donna answers grounded in retrieved entities with source
> URIs.
>
> **What this does NOT verify:** drafting (A2), MCP server, multi-turn
> branch compaction, narratives. See **Deferred** at the bottom.

---

## 1. Bring up the stack

From `server/`:

```bash
docker compose up --build
```

Five containers should come up: `donna-database` (Postgres 16),
`donna-redis` (Redis 7), `donna-web` (gunicorn), `donna-worker`
(Celery), `donna-beat`. Wait for `Listening on...` on web.

If `web` exits with `relation cortex_entities does not exist`, run
migrations once:

```bash
docker compose run --rm web migrate
```

Verify Redis + Postgres reachability from web:

```bash
docker exec donna-server bash -lc "cd /opt/donna && \
  DATABASE_HOST=donna-database uv run python -m django check --deploy 2>&1 | head -20"
```

(Container name may be `donna-web` instead of `donna-server` — adjust
with `docker compose ps`.)

## 2. Seed fixture (one workspace, one user, one DM, one cortex entity)

The fast path uses Django shell — no connector run required (Drive +
Gmail wire-ups exist but seeding through them adds OAuth dependency
this test doesn't need).

```bash
docker compose run --rm web shell
```

Inside the shell, paste:

```python
import hashlib
from datetime import datetime, timezone
from uuid import uuid4
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from donna.workspaces.models import Workspace, WorkspaceMembership
from donna.chat.models import Channel, ChannelMembership, AgentSession
from donna.chat.services import ChannelService
from donna.cortex.models import CortexEntity

User = get_user_model()

# --- workspace + user + membership ---
ws, _ = Workspace.objects.get_or_create(slug="qa-test", defaults={"name": "QA Test"})
user, created = User.objects.get_or_create(
    email="rares@example.com",
    defaults={"name": "Rares"},
)
if created:
    user.set_password("qatest")
    user.save()
WorkspaceMembership.objects.get_or_create(workspace=ws, user=user)

# --- DM channel (1-member DM works for testing) + agent session ---
dm = Channel.objects.create(
    kind=Channel.Kind.DIRECT,
    visibility=Channel.Visibility.PRIVATE,
    workspace=ws,
)
ChannelMembership.objects.create(channel=dm, user=user)
session = AgentSession.objects.create(channel=dm, name="Donna")
print(f"DM channel id: {dm.id}")
print(f"Agent session id: {session.id}")

# --- seed a cortex entity Donna can find ---
body = (
    "# Acme Corp payment terms\n\n"
    "Acme pays Net-30 from invoice date. Late fees waived for the first "
    "occurrence each quarter (per Q3 2025 agreement). Wire transfers only — "
    "no ACH. Invoice contact: ap@acme.example.\n\n"
    "Source: manual://seed/qa-test-acme-terms"
)
body_bytes = body.encode()
entity = CortexEntity(
    id=uuid4(),
    workspace=ws,
    type="doc",
    author="human",
    source="manual://seed/qa-test-acme-terms",
    bronze_storage_key="",
    content_hash=hashlib.sha256(body_bytes).hexdigest(),
    occurred_at=datetime.now(tz=timezone.utc),
    title="Acme Corp payment terms",
    body_byte_size=len(body_bytes),
    confidence="high",
    last_synthesized=datetime.now(tz=timezone.utc).date(),
    extensions={"doc_type": "spec"},
)
CortexEntity.objects.save_with_reverse_edges(entity, body_bytes=body_bytes)
print(f"Seeded entity id: {entity.id}")
print(f"Seeded entity title: {entity.title}")
```

Note: if `Workspace.slug` or `User.name` don't match your model fields,
adjust — these are common variants. Run `Workspace._meta.get_fields()`
to confirm.

## 3. Send a message → watch Donna answer

Still inside the shell (or open a fresh one):

```python
from donna.chat.models import Channel
from django.contrib.auth import get_user_model
from donna.chat.services import ChannelService

User = get_user_model()
user = User.objects.get(email="rares@example.com")
dm = Channel.objects.filter(kind=Channel.Kind.DIRECT).first()

ChannelService.send_message(
    channel=dm,
    sender_user=user,
    body="What are Acme's payment terms?",
)
```

Tail the worker in another terminal:

```bash
docker compose logs -f worker
```

Expected log sequence (rough — exact labels may vary):

```
chat.run_agent_turn[…] received
… ConversationAgent.__call__ ─ tool_calls=[{name: cortex_query, ...}]
… ToolDispatcher tool_announce tool=cortex_query
… ConversationAgent.__call__ ─ tool_calls=[{name: read_entity, ...}]
… ToolDispatcher tool_announce tool=read_entity
… ConversationAgent.__call__ ─ final_text="Acme pays Net-30… (source: manual://seed/qa-test-acme-terms)"
chat.run_agent_turn[…] succeeded
```

Verify the answer was persisted:

```python
from donna.chat.models import Message
last = Message.objects.filter(channel=dm).order_by("-created_at").first()
print(f"author_agent: {last.author_agent_id}")
print(f"body: {last.body}")
```

The body should contain "Net-30" and the citation
`(source: manual://seed/qa-test-acme-terms)`.

## 4. Variations to try

| Prompt | Expected behavior |
|---|---|
| `"What does Acme do?"` | cortex_query → no strong hits → either honest "I don't see this in cortex" OR best-effort answer + admission |
| `"Quote the Acme contact email."` | cortex_query → read_entity → answer "ap@acme.example" with source |
| `"Hello"` | No useful cortex hit → Donna replies conversationally, no tool calls (or 1 query that returns empty) |
| Second message in same DM | Branch from first turn — verify history is threaded (Donna sees prior exchange) |

## 5. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Worker logs `no_agent_session_skip_turn` | DM has no AgentSession | re-run §2 seed; confirm `session = AgentSession.objects.create(channel=dm, ...)` |
| Worker logs `turn_busy_retry` repeatedly | A previous turn's lock didn't release | `docker exec donna-redis redis-cli DEL "agent-turn:<channel_id>"` |
| Worker logs `conversation_agent_chat_failed` | LLM creds missing | check `ANTHROPIC_API_KEY` (or OpenAI key) in `.env` / docker-compose env |
| Tool result has `args_validation_failed` | model emitted malformed JSON | re-prompt or retry — should self-correct on next round |
| Agent answers without citing source | LLM ignored the citation rule | quality issue, not a wiring issue — tweak `donna/chat/agents/prompts.py CITATION_RULES` |
| `dense_channel_embed_failed` | sentence-transformers not installed → query degrades to keyword-only | `uv add sentence-transformers` then restart worker; keyword channel still works without it |
| Drive ingestion crashes with `KeyError: 'drive_file'` | already fixed (PROVIDER_TYPE_MAP) | confirm pipeline.py contains `"drive_file": "doc"` |

## 6. What landed (executed this session)

### P0 — cleanup + correctness (complete)

| Item | File(s) |
|---|---|
| #3 spawn through linter + manager (atomic write, lint gate; concept exception) | `donna/cortex/entities.py` |
| #4 GLiNER reads body via `ExtractContext.body_md` | `donna/cortex/entities.py`, `donna/cortex/pipeline.py` |
| #11 employer link: dual person+org spawn from same email → `extensions.employer_org_id` + `related` edge (never overwrites human-set); pipeline calls `resolver.resolve_batch` | `donna/cortex/entities.py`, `donna/cortex/pipeline.py` |
| #14 cosine floor (default 0.55) on `HDBSCANClusterer.assign` | `donna/cortex/clustering.py` |
| `_check_scope` relaxed — workspace-internal projects allowed | `donna/cortex/linter.py` |
| `_check_known_edges` rewritten — reject extension keys that are edge field names | `donna/cortex/linter.py` |
| `NoOpFitter` deleted; `fitter` opt-in (None default); guard clause replaces try/except | `donna/cortex/pipeline.py`, `donna/cortex/template_engine.py` |
| **Dead-code purge**: `storage.py` (whole file), `SilverEntity`, `ClusteringService`, `DerivedNamespaceView`, `tests/test_derived_view.py`, `ClusterStrategy`/`ClusterNamerStrategy` Protocols | `donna/cortex/storage.py`, `schemas.py`, `clustering.py`, `folders.py`, `tests/test_derived_view.py` |
| **`managers.py` extracted** — `CortexEntityManager` lives in its own file (Django convention); models.py imports it | `donna/cortex/managers.py` (new), `donna/cortex/models.py` |
| **`types.py` collapse** — 12 `templates/<type>.py` files → 1 declarative table; `apps.py ready()` imports `donna.cortex.types` instead of walking the dir | `donna/cortex/types.py` (new), `donna/cortex/apps.py`, deleted 12 `templates/*.py` |
| **`folders.py` classes → funcs** — 9 single-method resolvers became plain functions; `TypeSpec.folder_resolver` is now a `FolderFn` callable; pipeline calls it directly | `donna/cortex/folders.py`, `donna/cortex/registry.py`, `donna/cortex/pipeline.py` |
| **`doc_classifier.py` tier A** — heuristic MIME + filename + body-anchor classifier; runs before fit step when `cortex_type == "doc"` and connector left doc_type empty | `donna/cortex/doc_classifier.py` (new), `donna/cortex/pipeline.py` |
| **`CortexWriter` → `CortexPipeline` rename** (class + all callers + module + test references + docstrings) | `donna/cortex/pipeline.py`, `donna/cortex/__init__.py`, `embeddings.py`, `template_engine.py`, `schemas.py`, fathom + gmail `tasks.py`, `tests/test_pipeline.py` |
| **HaikuFitter sampler swap** — `text[:8000]` replaced with `TypeSpec.embedding_sampler` (default `head_tail_sampler`); pipeline passes sampler at call site | `donna/cortex/template_engine.py`, `donna/cortex/pipeline.py` |
| **Reverse-edge writer debug-raise** — missing target = structured `logger.warning` + raise `DanglingEdgeError` in `settings.DEBUG`; silent return in prod | `donna/cortex/managers.py` |

### P1 — living source + bronze (complete)

| Item | File(s) |
|---|---|
| Versioned bronze keys (sha8 in path) — Fathom, Gmail, Drive | `donna/core/integrations/bronze.py` (new), three connector `tasks.py` |
| Drive: `drive_file` → `doc` added to PROVIDER_TYPE_MAP | `donna/cortex/pipeline.py` |
| Supersession side-effect: ancestor `doc_embedding` + `cluster_id` cleared on supersede (body untouched, R1) | `donna/cortex/managers.py` |

### P4 — minimal CortexService (Q&A slice, MCP+ladder skipped intentionally)

| Item | File(s) |
|---|---|
| `CortexService.query` (RRF over dense + keyword) | `donna/cortex/services.py` (new) |
| `CortexService.read_entity` | same |
| `CortexService.get_context` | same |
| `CortexService.linter_check` (used by A2 finalize later) | same |

### A1 — chat agent Q&A runtime (complete)

| Item | File(s) |
|---|---|
| Tool base — `DonnaTool`, `Tainted`, `ToolContext`, `ToolResult` + per-tool `timeout_s` + `taint_safe` ClassVars | `donna/chat/agents/tools/base.py` (new) |
| `ToolRegistry` + `RegistryFrozenError` + `subset()` + module-level `GLOBAL_REGISTRY` | `donna/chat/agents/tools/registry.py` (new) |
| `cortex_read.py` — `CortexQueryTool`, `ReadEntityTool`, `GetContextTool`, **`PrepareContextTool`** (macro — query + parallel read_entity fan-out, single round-trip on new topics) | `donna/chat/agents/tools/cortex_read.py` (new) |
| `factory.py` — `build_registry()` subsets `GLOBAL_REGISTRY`; `register_qa_tools()` for boot wiring | `donna/chat/agents/tools/factory.py` (new) |
| Redis turn lock (SET NX EX + Lua compare-and-delete release) | `donna/chat/agents/locks.py` (new) |
| `AgentState` + `build_state` with **branch-aware Haiku compaction** (cache on `AgentSession.memory["branch_digest"]`) | `donna/chat/agents/state/builder.py` (new) |
| `prompts.py` — identity + citation rules + tool-routing hints | `donna/chat/agents/prompts.py` (new) |
| `ConversationAgent` — LLM call producing tool_calls XOR final text | `donna/chat/agents/nodes/conversation_agent.py` (new) |
| `ToolDispatcher` — args validation + **taint check** + announce + per-tool timeout-wrap + **taint-stamp** result if external | `donna/chat/agents/nodes/tool_dispatcher.py` (new) |
| `run_graph` — entry → agent ⇄ dispatcher (max 6 rounds) | `donna/chat/agents/graph.py` (new) |
| `runner.py` — `persist_agent_message`, `update_session_memory`, `emit_typing` | `donna/chat/agents/runner.py` (new) |
| Celery task `run_agent_turn` + dispatcher hook `maybe_dispatch_agent` (DM-always / @-mention) + **typing on/off wrap** (try/finally) | `donna/chat/tasks.py` (new) |
| `ChannelService.send_message` → `transaction.on_commit(_dispatch_agent_if_applicable)` | `donna/chat/services.py` |
| **`ChatConfig.ready()`** — registers tools on `GLOBAL_REGISTRY` then `freeze()` (post-boot lock) | `donna/chat/apps.py` |

## 7. Deferred (NOT in this slice)

P0 and A1 are now both **complete** (all deferred items from the first
delivery were folded in on the second pass — 2026-06-14). Only P2 /
P3 / P4 stretch / A2 / A3 remain.

| Item | Why deferred | Where it lands |
|---|---|---|
| **P1** `.extracted.md` sidecar, ocr.py delete, two-tier dedup at step 2½ | Versioned bronze + supersession side-effect cover the correctness need for testing | small follow-up |
| **P2** Canonical adapter models (CanonicalMeeting/Email/Doc/…) | Current loose-dict pipeline ingests successfully; the rewrite is a typed refactor, not a feature | dedicated session — wide blast radius |
| **P3** Cluster identity continuity | Only matters on the 2nd recluster run; this test does no reclustering | dedicated session post-P2 |
| **P4 stretch** MCP server, scope ladder T1, classifier B (kNN), heads-only partial indexes, RRF tsvector + sparsevec channels, ColBERT/cross-encoder rerank | Q&A works on dense+keyword RRF; richer retrieval is the Phase 7 arc | Phase 7 |
| **A1 cross-round taint persistence** | Current taint is one-shot within a single dispatcher pass; cross-round flow (LLM round-trips strip the marker) would need substring tracking in state. Not exploitable in Q&A slice (all tools `taint_safe=True`) | A2 — when draft tools enter that consume retrieved content |
| **A2** Document lifecycle (status/version/target_doc_type), CreateDraft/UpdateDraft/FinalizeDraft, DrafterNode | Out of Q&A scope; requires `Document` migration + `CortexService.create_entity` | dedicated A2 session |
| **A3** Rolling-summary memory compaction (separate from branch-digest), query-path Redis cache | Branch-digest covers history fit; the separate rolling summary + cache pay off on cross-session repeat queries | A3 polish session |

## 7a. Run the automated tests

Five test files cover P0 correctness + A1 runtime. Two run pure-Python
(no docker); three need Postgres + Redis (use the docker stack).

```bash
# Pure-Python (no DB/Redis needed) — runs anywhere
cd server
uv run python -m pytest donna/cortex/tests/test_p0_correctness.py -v
uv run python -m pytest donna/chat/tests/test_agents_a1.py -v
```

```bash
# DB-bound — needs docker compose up
docker exec donna-server bash -lc "cd /opt/donna && \
  DATABASE_HOST=donna-database uv run python -m django test \
    donna.cortex.tests.test_pipeline \
    donna.cortex.tests.test_managers_dangling \
    donna.chat.tests.test_state_builder_compaction \
    -v 2"
```

Test inventory:

| File | What it covers |
|---|---|
| `cortex/tests/test_p0_correctness.py` | linter scope relax, linter known-edges fix, cosine floor returns None below 0.55, cosine floor passes above, doc_classifier tier A (MIME/filename/anchor/no-match) |
| `cortex/tests/test_managers_dangling.py` | `DanglingEdgeError` raised in DEBUG; silent return in prod (via `override_settings`) |
| `cortex/tests/test_pipeline.py` | existing CortexPipeline smoke — renamed references |
| `chat/tests/test_agents_a1.py` | registry dup-name + freeze + subset; dispatcher validation/unknown-tool/timeout/success paths; taint walk + has-leaf; turn lock mutual exclusion (Redis-required, auto-skip otherwise); mention regex; anti-loop short-circuit |
| `chat/tests/test_state_builder_compaction.py` | short history → no compaction; > trigger → digest appears; second call hits cache (one LLM call total) |

## 8. Risks / known gaps to watch

- **Test DB needs `pgvector`**. Cortex models use `VectorField`; SQLite test DB won't help. Always test against the docker Postgres.
- **No tsvector index** — keyword channel is `ILIKE` on title; works for the seed entity but won't scale. Phase 7 adds tsvector.
- **First embedding load** (`BGESmallEmbedder._load()`) downloads `BAAI/bge-small-en-v1.5` (~130 MB) on first call. Slow first query if the model isn't cached.
- **Anti-loop relies on `author_agent_id`**. Don't manually `Message.objects.create(author_agent=None, body=...)` with an agent body or you'll trigger a self-reply chain.
- **DM with single user** is a valid test setup, but real product UX expects ≥1 peer + the agent. Adjust §2 if your DM model rejects single-member channels.
- **First connector ingest test** (if you skip §2's manual seed) needs OAuth tokens — see `server/plans/08a-gmail-integration.md`.

## 9. Resuming work from here

Recommended next chunks, in order of marginal value:

1. **A2 drafting** — unlocks the second flagship use case (~2d)
2. **P2 canonical adapters** — improves ingestion quality + enables typed validators (~2d)
3. **P0 refactor pass** — managers.py / types.py / folders.py / doc_classifier (~1d cosmetic)
4. **P4 stretch — tsvector + sparsevec + ColBERT rerank** (~3d) per 00f Phase 7
5. **A3 polish — Redis cache + branch compaction + memory** (~1d)
