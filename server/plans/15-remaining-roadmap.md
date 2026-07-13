# Plan — Remaining roadmap (consolidated)

> Source of decisions: 2026-06-28 audit across [`11-nango-integration.md`](11-nango-integration.md), [`12-deployment-pipelines.md`](12-deployment-pipelines.md), [`13-agent-runtime-maturity.md`](13-agent-runtime-maturity.md), [`14-frontend-integration.md`](14-frontend-integration.md), and [`cortex/06 - status/03-roadmap-remaining-work.md`](cortex/06%20-%20status/03-roadmap-remaining-work.md).
> Out of scope: anything already shipped (Plan 13 v1 S+A tier, Plan 14 P0/P1/P3–P7, cortex P0.0–P0.13, ingestion framework for Fathom/Gmail/Drive/Notion/WhatsApp).
> Cross-link: this is the parent index — each phase delegates to the originating plan for full detail.

---

## Context

### Why this consolidation exists

The v1 product surface is shipped (chat + drafting + memory + ambient agent
status + cowork file panel). The remaining work spans five different plans
with overlapping dependencies — e.g., Plan 11 Phase 0 (ingestion backend
abstraction) unblocks Nango but also resolves the multi-backend gap flagged in
Plan 05; Plan 12 Phase 0 (settings split) is a prerequisite for *every* cortex
P9 MCP API endpoint to be deployable on cloud.

Rather than execute each plan in isolation and rediscover the dependencies
mid-flight, this doc collapses them into one sequenced roadmap with a single
priority order. Each phase here is a *pointer* to the originating plan section;
edits should keep the per-plan source-of-truth, not duplicate prose here.

### Tiers

| Tier | Meaning |
|---|---|
| **S** | Ship-blocker — must land before the next paying customer |
| **A** | High value — quality + reach within 1 quarter |
| **B** | Useful but deferrable — wait for signal before committing |
| **C** | Speculative — revisit only if an explicit driver emerges |

### Effort scale

Days are *one engineer working uninterrupted*. Multiply by your reality.

---

## Phase shape

| # | Title | Tier | Effort | Source plan | Blocks |
|---|---|---|---|---|---|
| 1 | Deployment pipelines foundation | S | ~6.5d | [12](12-deployment-pipelines.md) | Cloud rollout, self-host releases, cortex P9 ship |
| 2 | Cortex P0.14 storage + sampled embeddings | S | ~3d | [cortex/06-03](cortex/06%20-%20status/03-roadmap-remaining-work.md) | P8/P9, real-world body sizes |
| 3 | Plan 13 v1 gap fillers | A | ~1d | [13](13-agent-runtime-maturity.md) | Drafter style coverage; bundled subagent demo |
| 4 | Cortex P8 — Gmail/Drive ingestion → cortex | A | ~0.5d | [cortex/06-03](cortex/06%20-%20status/03-roadmap-remaining-work.md) | Real-data demos |
| 5 | Cortex P9 — MCP API surface | A | ~3d | [cortex/06-03](cortex/06%20-%20status/03-roadmap-remaining-work.md) | Public agent reads from cortex |
| 6 | Frontend P2 — Pinned channels UI | A | ~0.5d | [14](14-frontend-integration.md) | Sidebar polish |
| 7 | Ingestion backend abstraction (Plan 11 Ph 0) | A | ~2d | [11](11-nango-integration.md) | Any non-Donna OAuth/fetch transport |
| 8 | Nango pilot connector (Plan 11 Ph 1–3) | B | ~5d | [11](11-nango-integration.md) | Long-tail connector reach |
| 9 | Cortex quality workers (R6 / R7 / R8) | B | ~4d | [cortex/06-03](cortex/06%20-%20status/03-roadmap-remaining-work.md) | Knowledge accuracy at scale |
| 10 | Cortex Golden Questions eval harness | B | ~3d | [cortex/06-03](cortex/06%20-%20status/03-roadmap-remaining-work.md) | Regression-proof cortex |
| 11 | Plan 13 B-tier (runtime hygiene + multi-audience) | B | ~5d | [13](13-agent-runtime-maturity.md) | Agent reliability at scale |
| 12 | Plan 13 C-tier (UI extras + speculative) | C | ~6d | [13](13-agent-runtime-maturity.md) | Polish only |
| 13 | Path 1 strict mode (Obsidian + pre-commit) | C | ~2d | [cortex/06-03](cortex/06%20-%20status/03-roadmap-remaining-work.md) | Enterprise compliance story |
| 14 | Storage backends (S3 / GitHub) | C | ~3d | [cortex/06-03](cortex/06%20-%20status/03-roadmap-remaining-work.md) | Non-LocalFS deployments |

**Totals.** S = ~9.5d. A = ~7d. B = ~17d. C = ~11d. *Grand: ~44.5d.*

---

## Phase 1 — Deployment pipelines foundation (S, ~6.5d)

**Why now**: Without this, the cloud can't auto-deploy and self-host can't
release. Every other phase that ships customer-facing behaviour depends on a
working pipeline.

Full scope lives in [`12-deployment-pipelines.md`](12-deployment-pipelines.md).
Sub-tasks in order:

1.1 Settings split — `donna/settings.py` → `donna/settings/{base,dev,cloud,self_host}.py` (~1d).
1.2 Dockerfile + entrypoint hardening — `DONNA_DEPLOYMENT` aware, multi-stage build (~0.5d).
1.3 Compose split — dev `docker-compose.yml` vs `deploy/self_host/docker-compose.yml`; **must align with [Plan 13 §3.4](13-agent-runtime-maturity.md#34-celery-worker-split) worker split** (~1d).
1.4 Self-host CI — `.github/workflows/ci.yml` (lint+test on PR) + `release.yml` (tagged release → GHCR + Helm chart publish) (~2d).
1.5 Cloud CI — `.github/workflows/cloud-deploy.yml` → push tag → trigger `donna-cloud-infra` via repository_dispatch (~1d).
1.6 Helm chart skeleton — `deploy/self_host/helm/donna/` with values for the new compose split (~1d).

Verification: tag `v0.0.1` → release workflow publishes Docker image + Helm
chart → pull on fresh host → `helm install` brings up identical stack to
local compose. Cloud-side green main pushes to staging cluster within 10 min.

---

## Phase 2 — Cortex P0.14 storage + sampled embeddings (S, ~3d)

**Why now**: Current `Entity.body` is a `TextField`; large emails / docs blow
out row size and embedding cost. Plan 12 ships, then this lands so cloud
storage works.

Full scope in [`cortex/06 - status/03-roadmap-remaining-work.md`](cortex/06%20-%20status/03-roadmap-remaining-work.md) (P0.14 section).

Sub-tasks:

2.1 Migrate `Entity.body` → `FileField` backed by `default_storage` (compose with Plan 12 §1.2 `DONNA_STORAGE_BACKEND`).
2.2 Sampled-embeddings strategy — head + middle + tail chunks per entity, store as `EmbeddingChunk` rows.
2.3 Retrieval — `EntityRepository.semantic_search` reads chunks, dedupes by entity, ranks by max sim.
2.4 Backfill migration for existing entities.

Verification: ingest a 500KB markdown doc, confirm 3 chunks land, similarity
search returns the doc within top-5 for both head and tail content queries.

---

## Phase 3 — Plan 13 v1 gap fillers (A, ~1d)

**Why now**: Two small audit-flagged gaps from the 2026-06-28 status pass.

3.1 Bundle `legal.md` output style (mirror `concise.md`'s structure) — drafter mode coverage gap (~0.25d).
3.2 Bundle one demo subagent def under `chat/agents/subagents/bundled/` (e.g. `research_assistant.md`) so the loader has at least one file to discover (~0.5d).
3.3 Add `AGENTS.md` at repo root — short pointer to the agent runtime + how to add styles/subagents (~0.25d).

Verification: drafter picks `legal` style on `@donna draft a legal brief…`; AgentTool spawn finds the bundled subagent; new contributor reads `AGENTS.md` and writes a custom style without docs spelunking.

---

## Phase 4 — Cortex P8 — Gmail/Drive ingestion → cortex (A, ~0.5d)

**Why now**: Cortex P0.13 is done but no real-data path lands entities. Gmail
+ Drive connectors *already produce DeliveryPackages*; the missing piece is
the cortex bridge.

Full scope in [`cortex/06 - status/03-roadmap-remaining-work.md`](cortex/06%20-%20status/03-roadmap-remaining-work.md) (P8).

4.1 Hook `cortex.ingest_delivery_package(pkg)` into `integrations/google/{mail,drive}/tasks.py` post-store.
4.2 Folder-resolve via existing `GmailFolderResolver` / `DriveFolderResolver`.
4.3 Entity extraction + dedup runs naturally through the existing pipeline.

Verification: send an email → Gmail webhook → cortex Entity row appears with
correct folder + extracted facts.

---

## Phase 5 — Cortex P9 — MCP API surface (A, ~3d)

**Why now**: Without an MCP endpoint, only in-process agents can read cortex.
Closing this unlocks `mcp_tool` proxies (Plan 13 §5.5, currently deferred)
and external tools.

Full scope in [`cortex/06 - status/03-roadmap-remaining-work.md`](cortex/06%20-%20status/03-roadmap-remaining-work.md) (P9). Eight methods to implement:

5.1 `search_entities(query, type?, scope?, limit)` — semantic search via sampled embeddings.
5.2 `read_entity(id)` — full body + metadata, respects authority/scope.
5.3 `list_folders(workspace_id, prefix?)` — folder tree slice.
5.4 `list_entities(folder, since?, limit)` — paginated folder listing.
5.5 `prepare_context(query, budget_tokens)` — multi-entity context budget builder.
5.6 `get_meta(id)` — metadata-only (cheap).
5.7 `lint_entity(id)` — run linter against an entity.
5.8 `propose_entity(payload)` — write path (gated by workspace permission).

Verification: external MCP client (Claude Desktop) connects, runs all 8
methods, gets sensible responses; permission boundary holds when invoked
without an auth token.

---

## Phase 6 — Frontend P2 — Pinned channels UI (A, ~0.5d)

**Why now**: Backend `Channel.is_pinned` + pin button exist; sidebar lacks
the "Pinned" group. Tiny lift.

Full scope in [`14-frontend-integration.md`](14-frontend-integration.md) (P2).

6.1 Split `Sidebar.tsx` channel list into Pinned + Channels groups, ordered by `is_pinned ? 0 : 1`.
6.2 Drag-reorder optional (defer to v2).

Verification: pin a channel, sidebar groups it under Pinned with collapse
chevron; unpin moves it back.

---

## Phase 7 — Ingestion backend abstraction (A, ~2d)

**Why now**: Unblocks Nango (Phase 8) AND closes the structural gap flagged
in Plan 05 (single-backend assumption baked into framework primitives).

Full scope = Plan 11 Phase 0 in [`11-nango-integration.md`](11-nango-integration.md).

7.1 Add `OAuthBackend` Protocol to `core/integrations/oauth.py`; keep the
existing Donna implementation as `DonnaOAuthBackend`.
7.2 Add `WebhookBackend` Protocol — current code becomes `DonnaWebhookBackend`.
7.3 Add `FetchBackend` Protocol — new abstraction over the polling/fetch path.
7.4 Per-connector setting: `backend: "donna" | "nango"` (default `donna`).
7.5 No behaviour change for existing connectors — pure refactor.

Verification: every existing connector still works unchanged; `python -m
django check` clean; one synthetic test wires a stub `NoOpBackend` and
asserts the registry routes correctly.

---

## Phase 8 — Nango pilot connector (B, ~5d)

**Why now**: Only land this when there's a customer ask for a connector
Donna doesn't have native (Notion sync was the originating use case).

Full scope = Plan 11 Phases 1–3 in [`11-nango-integration.md`](11-nango-integration.md).

8.1 Nango SDK integration + secret management (Cloud + self-host parity).
8.2 `NangoOAuthBackend` + `NangoWebhookBackend` + `NangoFetchBackend`.
8.3 First connector via Nango (Notion or Linear) end-to-end.

Verification: OAuth → first sync → DeliveryPackage lands → cortex entity
appears, identical shape to a native connector.

---

## Phase 9 — Cortex quality workers (B, ~4d)

**Why now**: At small scale these aren't hit; at scale they protect data
integrity. Land before any customer crosses ~10k entities.

Full scope in [`cortex/06 - status/03-roadmap-remaining-work.md`](cortex/06%20-%20status/03-roadmap-remaining-work.md):

9.1 R6 Gold-resynth trigger — when an entity changes, dependent Gold rollups regenerate (~1.5d).
9.2 R7 Contradiction detection — flag entities whose linked facts disagree (~1.5d).
9.3 R8 Confidence decay — periodic background sweep ages low-touch entities (~1d).

Verification: synthetic dataset with contradictions raises flags; decay sweep
demotes entities below a threshold without deleting them.

---

## Phase 10 — Cortex Golden Questions eval harness (B, ~3d)

**Why now**: Regression coverage for cortex. Future cortex changes break
silently otherwise.

Full scope in [`cortex/06 - status/03-roadmap-remaining-work.md`](cortex/06%20-%20status/03-roadmap-remaining-work.md).

10.1 `cortex/eval/golden_questions.yaml` — canonical Q→expected entity ids.
10.2 Eval runner CLI: `python -m django cortex_eval` → per-question pass/fail.
10.3 GitHub Action runs against a seeded fixture workspace on every cortex change.

Verification: intentional regression in the linter trips the harness in CI;
green run on main blocks no PRs.

---

## Phase 11 — Plan 13 B-tier (runtime hygiene + multi-audience) (B, ~5d)

**Why now**: Defer until v1 cowork loop is in real customer hands and shows
the specific reliability cracks each sub-section addresses.

Full list of sub-sections in [`13-agent-runtime-maturity.md`](13-agent-runtime-maturity.md):

- 3.1 Output cap recovery
- 3.2 Stop-reason handling
- 3.3 Tool dispatcher partition + concurrency safety
- 3.4 Celery worker split — note Plan 12 §1.3 already lays the compose ground for this
- 4.3 Memory write tooling (`update_memory_fact`)
- 6.3 Multi-audience drafter (defer per current scope lock; revisit when sales asks for it)

---

## Phase 12 — Plan 13 C-tier (UI extras + speculative) (C, ~6d)

Speculative — revisit only when a customer signal demands one of these:

- 1.4 TodoWrite (in-channel task list)
- 5.2 Named subagent mailbox
- 5.3 Cross-agent visibility transcripts
- 5.5 MCP tool proxy (depends on Phase 5 P9 MCP API)
- 7.3 Feedback aggregator
- 8.1 Slash commands (dropped earlier; reinstate only with a real need)
- 8.3 Channel-resident install UI
- 8.4 Schedule UI

---

## Phase 13 — Path 1 strict mode (Obsidian plugin + pre-commit) (C, ~2d)

**Why now**: Only land if an enterprise self-host customer asks for the
"editable on disk + commit to git" workflow.

Full scope in [`cortex/06 - status/03-roadmap-remaining-work.md`](cortex/06%20-%20status/03-roadmap-remaining-work.md).

13.1 Obsidian plugin — read-only vault renderer that respects cortex
permissions.
13.2 Pre-commit hook — lint vault `_index.md` / `_log.md` before allowing a
commit.

---

## Phase 14 — Storage backends (S3 / GitHub) (C, ~3d)

**Why now**: Plan 12 §1.2 surfaces `DONNA_STORAGE_BACKEND`. Beyond LocalFS
the stubs need real implementations; only matters when a customer can't use
LocalFS.

Full scope in [`cortex/06 - status/03-roadmap-remaining-work.md`](cortex/06%20-%20status/03-roadmap-remaining-work.md).

14.1 S3 backend — boto3, signed URLs, multipart for large bodies.
14.2 GitHub backend — write-through to a customer-supplied repo (read-only).

---

## Open questions

1. **Cloud vs self-host parity for cortex P9 MCP** — does the cloud expose a
single MCP URL per workspace or per user? Decide before Phase 5.
2. **Nango cost model** — Nango bills per connection-month. Confirm a price
ceiling acceptable to a self-host customer before Phase 8 commits.
3. **Eval harness blocking PRs** — Phase 10 says "block no PRs" by default;
revisit when the harness is stable (move to "block on red" after 1 month
clean runs).
4. **Pinned channels — drag-reorder?** — Phase 6.2 marked optional. Decide
when a customer asks for stable channel ordering across devices.

---

## Verification (whole-plan)

- Phase 1 must land before Phase 2 (settings split shapes storage backend wiring).
- Phase 2 must land before Phase 4 (FileField body is the on-disk format
P8 ingestion writes to).
- Phase 5 must land before Phase 12 §5.5 (MCP tool proxy depends on the API).
- Re-run `python -m django check` after every phase touches `donna/settings*`
or `donna/integrations/*`.
- Re-run `server/donna/chat/tests/test_agents_a2.py` after every Plan 13
phase to confirm drafting backbone stays green.
- Eval harness (Phase 10) gates every cortex change after it lands.
