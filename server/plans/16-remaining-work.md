# 16 — Remaining work (verified against code)

> **Single source of truth for what's left.** Consolidated 2026-07-15 from a
> live code audit, not stale plan text. Every item below was checked against the
> actual codebase; the previous status/roadmap files
> (`15-remaining-roadmap.md`, `15-deferred-and-followups.md`,
> `cortex/06 - status/{01,02,03}`) are **deleted** — they overstated open work
> (MCP surface, `_index.md`/`_log.md` regen, async embeddings, nightly recluster,
> Gmail/Drive→cortex, S3 storage, deploy pipelines, SMTP have all shipped).
>
> Feature specs that survive (this doc links to them for detail):
> `cortex/06 - status/05-deferred-document-chunking.md`,
> `.../06-narrio-adoptions.md`, `.../06-p0.15-long-document-support.md`,
> `cortex/03 - contracts/04-linter-r1-r10.md`.

Legend: 🔴 correctness/data-integrity bug · 🟠 high-value feature · 🟡 hardening ·
🟢 small robustness · 🔵 deferred-by-design (no driver yet).
Effort = one engineer, uninterrupted.

---

## 1. Cortex — correctness / data-integrity bugs (do before multi-tenant ingest at volume)

None cause user-visible data loss (retrieval is heads-only), but they corrupt
clustering quality and scope isolation.

### 🔴 A1 — Supersede-on-rehash pollutes clustering *(live now)*
Two supersede paths disagree. The canonical `_assign_superseded_by`
(`cortex/managers.py:194`) nulls `doc_embedding` + `cluster_id` on the old head
("superseded ancestor stops participating in retrieval/clustering"). But the
pipeline's rehash block (`cortex/pipeline.py:407`) bulk-`update()`s **only**
`superseded_by`, leaving the vector + cluster on the dead head. Recluster
candidate filters (`cortex/clustering.py:117,177`, `cortex/tasks.py:144,181`)
filter `doc_embedding__isnull=False` but **never** `superseded_by__isnull=True`.

- **Failure:** re-ingest a changed doc → old head keeps its embedding → nightly
  HDBSCAN double-counts old+new of the same source in centroids; `assign()` can
  match a dead vector.
- **Already triggered** ~135× by the 2026-07-15 Fathom transcript backfill —
  those superseded heads are sitting polluted right now.
- **Fix (~5 lines):** null `doc_embedding`+`cluster_id` in the pipeline supersede
  block (mirror `_assign_superseded_by`) **and/or** add
  `superseded_by__isnull=True` to the three recluster filters. Then re-run the
  cluster assign for the affected workspace.

### 🔴 A2 — R4 `cross_refs` never scope-checked — multi-tenant leak
`_check_cross_refs` (`cortex/linter.py:110`) is shape-only; the comment defers
the pairwise intra-scope check to "the repository", but
`save_with_reverse_edges` does no scope fetch/validate either. A curated row can
`cross_ref` an entity in another client/project — the exact cross-scope
contamination R4 exists to prevent.
- **Fix:** validate each `cross_refs` target shares `(client_id, project_id)`
  scope at save time; reject `INVALID_SCOPE` otherwise. ~0.5d.

### 🔴 A3 — `INVALID_SCOPE` reject is a no-op
`_check_scope` (`cortex/linter.py:89`) just `return`s. Mostly a deliberate
2026-06-11 relaxation (project-without-client is now allowed for
workspace-internal projects), but the relaxation deleted the whole guard instead
of narrowing it, and the linter docstring + `__main__` demo
(`03 - contracts/04-linter-r1-r10.md`) still claim it rejects.
- **Fix:** either restore a narrowed guard or update the contract doc + demo to
  match reality. ~0.25d.

### 🔴 A4 — Cross-source `content_hash` collision → unhandled `IntegrityError`
Unique key is `(workspace, content_hash)` (`cortex/models.py:280`), but the
writer's dedup short-circuit matches on `source`+`hash` (`pipeline.py:321`). Two
different sources with an identical rendered body (e.g. near-empty) → the second
write isn't caught by dedup and hits the constraint; no `IntegrityError` catch in
`managers.py:148` → the connector's best-effort `except` logs and drops it. Spec
says a duplicate should return the existing `entity_id`.
- **Fix:** either widen the unique key to `(workspace, source, content_hash)` or
  catch `IntegrityError` in the writer and return the existing head. ~0.5d.

### 🔴 A5 — MCP/agent `create_entity` has no dedup or supersede
`CortexService.create_entity` (`cortex/services.py:274`) lints + saves directly —
no replay-dedup, no supersede-on-rehash (only `pipeline.write` has them). Agent/MCP
writing twice for the same `source` with a changed body → **duplicate head** (or
`IntegrityError` on identical body). The duplicate-head risk the old docs pinned
on ingest actually lives here.
- **Fix:** route MCP/agent writes through the same dedup+supersede logic as
  `pipeline.write` (extract a shared helper). ~1d.

---

## 2. Cortex — missing features (confirmed absent)

| Tier | Item | Evidence | Effort |
|---|---|---|---|
| 🟠 | **Long-document chunking / sections** (P0.15) — single `doc_embedding` only; large docs lose tail recall. Spec: `06 - status/06-p0.15-long-document-support.md` + `05-deferred-document-chunking.md`. No `chunking.py`/`CortexChunk`; migrations stop at `0002`. | — | ~3–4d |
| 🟠 | **Narrio adoptions** — patterns/narrative/synthesis layer, linter R11, `embed_policy`, `cluster_stale`/`narrative_stale`. Spec: `06 - status/06-narrio-adoptions.md`. None built (no `plans/decisions/`, no `CortexPattern`/`CortexNarrative`/`synthesis.py`). | — | (per-PR) |
| 🟡 | **R6 gold-resynth trigger** — dependent rollups regenerate when an entity changes. `last_synthesized` set at write only (`pipeline.py:355`). | absent in `tasks.py` | ~1d |
| 🟡 | **R7 contradiction detection** — the `contradicts` reverse-edge *writer* exists (`managers.py:203`) but nothing auto-detects. Needs an entailment pass. | no `contradictions.py` | ~1.5d |
| 🟡 | **R8 confidence decay** — `confidence` is static (`high` ingest / `medium` spawn). | absent in `tasks.py` | ~0.5d |
| 🟡 | **Golden-Questions eval harness** — regression coverage for cortex retrieval. | no `cortex/eval/`, no `cortex_eval` cmd | ~3d |
| 🟡 | **`cortex_sync --rebuild`** — Postgres-from-storage rebuild is a `NotImplementedError` stub (`management/commands/cortex_sync.py:35`). `--reindex-embeddings`/`--rebuild-clusters` do work. | stub | ~1d |
| 🟢 | **`self`-org uniqueness** — "exactly one org per workspace with `relationship: self`" not enforced (only unique key is `(ws, content_hash)`). | `models.py:280` | ~0.25d |
| 🔵 | **GitHub storage backend** — S3/GCS/Azure/filesystem all work via Django `default_storage`/`STORAGES` (env-driven); GitHub write-through never built. | — | ~2d |
| 🔵 | **8 ADRs** to `plans/decisions/` — folder doesn't exist. | — | ~1d |

---

## 3. Cortex — frontend gaps (no formal plan; UI built ad-hoc as `Files.tsx`)

The cortex UI is one page (`web/src/views/Files.tsx`, `/cortex`) — folder tiles
by type/org/project/people, scope nav, preview drawer with `body_md` + raw-source
link. It under-exposes the backend:

| Tier | Gap | Detail |
|---|---|---|
| 🟠 | **Search isn't semantic** | The search box hits `GET /cortex/entities/files/?q=` → `title__icontains(q)` (`cortex/api/v1/views.py:110`). The hybrid semantic search (dense+keyword+tsvector RRF) exists at the sibling `search`/`query` action (`views.py:45`) and the **agent uses it** — the human UI doesn't. Rewire the box to the semantic endpoint. ~0.5d. |
| 🟠 | **No relationship / graph view** | `getCortexContext` (depth walk over `entity_refs`/`cross_refs`) is in the client (`web/src/api/cortex.ts:67`) but never rendered. No related-entities panel. |
| 🟡 | **No cluster/theme browse** | Folders are type/org/project/people; HDBSCAN cluster names (HaikuNamer themes) aren't a browse axis. |
| 🟡 | **No timeline / log view** | No chronological surface (the `_log.md` equivalent). |

---

## 4. Non-cortex backend / infra

| Tier | Item | Evidence | Effort |
|---|---|---|---|
| 🔴 | **Open redirect** — `IntegrationRegistryService` 302s to any client-supplied `redirect_to`; no host allowlist. Actively used by the SPA now. | `integrations/api/v1/oauth.py:73,143` | ~1h |
| 🟠 | **`web_search` / Tavily `DonnaTool`** — not built; biggest agent-capability gap (Q&A + draft augmentation). Register in `chat/agents/tools/factory.py` (`taint_safe=False`). | absent | ~0.5d |
| 🟡 | **Settings split** — `donna/settings.py` still one 20KB file; split into `settings/{base,dev,cloud,self_host}.py`. | single file | ~1d |
| 🟡 | **Celery worker split** — one undivided worker (`--concurrency=2`, no `-Q`); embed/ingest/agent compete. A dedicated embed queue is cleaner at steady state. | `docker-compose.yml`, one `deployment-worker.yaml` | ~1d |
| 🟡 | **Helm `checksum/config` annotation** — ConfigMap changes don't roll pods (needed manual `rollout restart` twice). | no match under `deploy/` | ~0.5d |

---

## 5. Frontend robustness (small)

| Tier | Item | Evidence |
|---|---|---|
| 🟢 | **Refresh single-flight** — N concurrent 401s fire N `tryRefresh()` calls. Harmless while `ROTATE_REFRESH_TOKENS` is off; breaks if enabled. | `web/src/api/client.ts:50` |
| 🟢 | **Integrations store error state** — only `loading`/`loaded`; a genuine (non-workspace) failure shows "Loading…" forever. Add `error` + retry. | `web/src/state/integrations.ts` |

---

## 6. Security — secret rotations (leaked through session transcripts)

All still open. Rotate each and update SSM where relevant:

- `cube-staging` IAM **secret access key**
- Staging **DB password** + **Redis auth token** (`/staging/donna/{database,redis}/*`)
- Admin `admin@donna.ai` **superuser password** (real staging superuser)
- **Anthropic API key** (`/staging/donna/anthropic/api_key`)
- **Gmail app password** (`/staging/donna/email/password`)

Plus the 🔴 open-redirect fix in §4.

---

## 7. Deferred by design (revisit only on a real driver)

- 🔵 **Nango** long-tail connectors (Plan 11 Ph 1–3) — wait for a customer ask for a connector Donna lacks natively.
- 🔵 **Ingestion backend abstraction** (Plan 11 Ph 0) — prerequisite for Nango; pure refactor, land with it.
- 🔵 **Obsidian strict mode** (Path 1 — editable-on-disk + pre-commit) — enterprise self-host ask only.
- 🔵 **Plan 13 C-tier** UI extras — TodoWrite, named subagent mailbox, cross-agent transcripts, MCP tool proxy, feedback aggregator, slash commands, channel-resident install UI, schedule UI.
- 🔵 **Cert + Route53 to Terraform** — currently out-of-band (hybrid); backfill for reproducibility / on-prem parity.

---

## Suggested order

1. **§4 open-redirect + §6 rotations** — security, cheap, real.
2. **§1 A1** — live clustering corruption; small fix + re-cluster the backfilled workspace.
3. **§4 `web_search` tool** — biggest agent-capability unlock.
4. **§3 semantic search in the cortex UI** — backend already does the work; frontend rewire.
5. **§1 A2/A4/A5** — before multi-tenant ingest at volume.
6. Then §2 quality/eval maturity as scale demands.

## Verification discipline

- `DJANGO_SETTINGS_MODULE=donna.settings .venv/bin/python -m django check` after any `settings*`/`integrations*`/`cortex*` change.
- Re-run `chat/tests/test_agents_a2.py` after agent/tool changes.
- Once built, the Golden-Questions harness (§2) gates every cortex change.
