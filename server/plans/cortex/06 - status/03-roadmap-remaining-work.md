# Roadmap — Remaining Work

What ships next, in priority order. Numbered to continue from the
existing P0 → P0.13 phases.

## P0.14 — Body to FileField + Sampled Embeddings  (NEXT)

**Goal:** move `body_md` out of `cortex_entities` (Postgres TEXT) into
`SilverStorage` via Django `FileField`; replace full-body embedding
input with per-type sampled representation.

**Files to touch:**
- `donna/cortex/models.py` — drop `body_md TEXT`; add `body FileField`
  + `body_byte_size` + `load_body()`
- `donna/cortex/migrations/0002_body_to_filefield.py` — new migration
- `donna/cortex/embeddings.py` — add 4 samplers
  (`fixed_window_sampler`, `head_heavy_sampler`, `head_tail_sampler`,
  `uniform_sampler`) + `embed_entity()` wrapper
- `donna/cortex/registry.py` — add `embedding_sampler` field to TypeSpec
- `donna/cortex/pipeline.py` — step 5 uses `embed_entity(sampler=…)`,
  step 11 writes body via FileField in same atomic txn
- `donna/cortex/templates/<type>.py` (12 files) — set per-type sampler
- `donna/cortex/tasks.py` — `reap_orphan_bodies` Celery task

**Verification:**
- `cortex_entities` no longer has `body_md TEXT` column
- `entity.body.url` returns presigned URL (S3) or filesystem URL
- `entity.load_body()` returns full markdown lazily
- Sampled embedding input ≤ 1900 chars regardless of body size
- All existing 11 tests pass + 3 new tests

**Estimated:** ~1 day.

**Plan doc:** [`04-p0.14-storage-and-embedding-refactor.md`](./04-p0.14-storage-and-embedding-refactor.md).

## P0.15 — Document chunking  (DEFERRED)

**Status:** deferred until first long-doc client. Spec'd but not built.

**Trigger:** workspace ingests a doc > 4000 tokens (~5 pages) AND
retrieval quality breaks (current full-body LLM context still works
for docs ≤ 40 pages).

**Plan doc:** [`05-deferred-document-chunking.md`](./05-deferred-document-chunking.md).

## P8 — Wire Gmail + Drive connectors

**Goal:** trigger CortexWriter from the other two active connectors.

**Files to touch:**
- `donna/integrations/connectors/google/mail/tasks.py` — append cortex hop
- `donna/integrations/connectors/google/drive/tasks.py` — append cortex hop + route through OCRService for binary mimes
- `donna/integrations/connectors/google/drive/adapter.py` — emit `mime_type` and `owner` in metadata

**No schema change needed** — `PROVIDER_TYPE_MAP` already handles
`file → doc` and `message_thread → chat`.

**Verification:**
- Ingest a Gmail thread → cortex_entity of `type=email` persists
- Ingest a Drive PDF → cortex_entity of `type=doc` with `doc_type`
  filled by HaikuFitter

**Estimated:** 2 hours.

## P9 — MCP API surface (8 methods, spec §10.2)

**Goal:** expose the 8-method MCP API as DRF endpoints so agents can
read + write Cortex entities.

| Method | URL | Verb |
|---|---|---|
| `cortex.create_entity` | `POST /cortex/v1/entities` | POST |
| `cortex.update_entity` | `PATCH /cortex/v1/entities/{id}` | PATCH (R1: only body_md + extensions) |
| `cortex.read_entity` | `GET /cortex/v1/entities/{id}` | GET |
| `cortex.query` | `POST /cortex/v1/query` | POST (filters body) |
| `cortex.get_context` | `GET /cortex/v1/entities/{id}/context?depth=2` | GET |
| `cortex.eval_run` | `POST /cortex/v1/eval` | POST (Golden Questions) |
| `cortex.linter_check` | `POST /cortex/v1/lint` | POST (dry-run) |
| `cortex.health` | `GET /cortex/v1/health` | GET |

**Files to create:**
- `donna/cortex/api/v1/{views,serializers,filters}.py`
- `donna/cortex/api/v1/urls.py`
- `donna/cortex/services.py` — `CortexService(BaseService)` per
  conventions
- Update `donna/urls.py` to mount cortex

**Plus** the three index/log/entity-by-path endpoints from the original
plan (path-axis classifier):

```
GET /cortex/index?path=<path>     → dispatches topical / entity / temporal
GET /cortex/log?path=<path>&since=<iso>
GET /cortex/entity/{id}
```

**Estimated:** 1-2 days.

## P10 — Mode A vault projection (`VaultRenderer`)

**Goal:** Mode A (enterprise self-hosted) workspaces get a live
markdown vault written to disk + git-committed on every Cortex write.

**Files to create:**
- `donna/cortex/vault_renderer.py` — Celery task walks cortex_entities
  + renders `_index.md` per folder, `_log.md` per scope, entity `.md`
  per row, `git commit` per write batch
- `donna/cortex/vault_io.py` — `VaultIORepository` Protocol +
  `LocalGitVaultIO` impl (later `S3VaultIO`)

**Schema change:**
- `workspaces/models.py` — add `vault_render_mode: Literal["off",
  "live", "on_demand"]` to `Workspace`
- migration

**Verification:**
- Toggle `vault_render_mode='live'` on a workspace
- Trigger Fathom ingest
- Inspect `<vault-root>/<workspace-slug>/clients/.../meetings/...md`
- `git log` shows a commit per write batch

**Estimated:** 2-3 days.

## P11 — Postgres-as-derived rebuild job

**Goal:** `donna sync --workspace=qube --rebuild` reads
`SilverStorage` and rebuilds the `cortex_entities` table from
scratch. Spec §14 promise.

**Files to create:**
- `donna/cortex/management/commands/sync.py` — Django management
  command with `--rebuild`, `--workspace`, `--storage-prefix` flags

**Estimated:** 1 day.

## P12 — R6, R7, R8 background workers

**Goal:** the three deferred linter rules.

### R6 — Gold-resynth trigger

For `project`, `concept`: if N new `sources` since `last_synthesized`,
queue resynth.

**Files:** `donna/cortex/tasks.py` — `resynth_curated_entities` task
+ beat schedule.

### R7 — Contradiction detection

Entailment model (Haiku-driven): pairwise check of related rows; on
detection, write symmetric `contradicts[]`.

**Files:** `donna/cortex/contradictions.py` (new) — detector +
Celery task.

### R8 — Confidence decay

Walk every row; if `last_synthesized > 6mo`, demote confidence.

**Files:** `donna/cortex/tasks.py` — `decay_confidence` task.

**Estimated:** 2-3 days total.

## P13 — Path 1 strict enforcement

**Goal:** all writes must go through MCP API. Direct file edits in
canonical namespace blocked.

**Components:**
- Pre-commit hook (`.pre-commit-hooks/cortex-schema-check.sh`)
- CLI `donna` Python entry point (Typer-based)
- Obsidian plugin (TypeScript; separate repo)

**Estimated:** 1-2 weeks for plugin; 1 day for CLI; 1 hour for hook.

## P14 — Golden Questions eval harness

**Goal:** spec §13 contract — nightly eval over a workspace's locked
question set with measurable drift detection.

**Files:**
- `donna/cortex/eval/` — `golden_questions.py`, `runners.py`,
  `metrics.py`
- `_meta/extensions/eval/golden-questions.md` per workspace
- `cortex.eval_run` MCP method (P9 dependency)

**Estimated:** 3-5 days.

## P15 — GitHub + S3 storage backends

**Goal:** `GitHubStorage` (single-commit atomicity via Git Trees API)
+ `S3Storage` (multipart batch + DynamoDB lock + S3 versioning).

**Files:** `donna/cortex/storage_github.py`, `donna/cortex/storage_s3.py`.

**Estimated:** 1 week each (lots of edge cases on atomic writes).

## P16 — File-watcher reverse-sync (post-v1)

**Goal:** human edits to vault files → Cortex re-ingests.

**Files:** `donna/cortex/watchers/` (new) — fanotify / fsevents +
canonical namespace gatekeeper.

**Estimated:** 1-2 weeks.

## Recommended next sprint

| Priority | Phase | Time |
|---|---|---|
| 1 | P8 — Wire Gmail + Drive | 2h |
| 2 | P9 — MCP API (3-4 endpoints minimum) | 1.5d |
| 3 | P10 — Mode A vault projection (`live` mode) | 2-3d |
| 4 | P11 — Rebuild job | 1d |

That sprint unblocks the chat agent layer (which needs the MCP API)
and gives Mode A clients a working vault.

After that:
- R7 contradiction detection (post-v1 in spec, but high-value)
- Obsidian plugin (parallel track — separate engineer)
- GitHub backend (for first self-host client)

## What never ships in v1

| Out of scope | Reason |
|---|---|
| Agent orchestrator | Separate plan (consumes Cortex MCP API) |
| Chunk-level embeddings | Plan says no — agent navigates indexes |
| Dynamic ontology (LLM proposes types) | Stage 3 only |
| FalkorDB / graphiti graph layer | Stage 3 only |
| Per-vault custom layouts | Universal Folder Structure §9 is locked |

## Watch list — risks

| Risk | Mitigation |
|---|---|
| R7 entailment model false positives → noisy Open Questions | start with high-confidence threshold; surface only "very likely contradictions" |
| LocalFSStorage flock doesn't scale to multi-process | switch to GitHubStorage (single-commit atomicity) for production |
| Cluster names from Haiku drift over time | name pinned to cluster UUID; only re-named when cluster changes shape |
| Workspace owner forgets to set `org.relationship: self` | bootstrap CLI / first-run wizard sets it |
| Sub-discriminator vocab evolves | spec amendment + migration to add new values |

## ADRs to write (spec §15)

The spec lists 8 ADRs baked in but not yet captured as separate
documents:

| ADR | Topic |
|---|---|
| ADR-001 | Silver canonical = files in SilverStorage; Postgres = derived |
| ADR-002 | 12 unified Silver types + 9 edges = closed vocabulary |
| ADR-003 | Cluster boundary = `(workspace, client, project)` |
| ADR-004 | Bronze separated from Silver (separate repo / bucket) |
| ADR-005 | Atomic writes per backend (GitHub commit / S3 multipart+DynamoDB / FS flock+rename) |
| ADR-006 | Golden Questions mandatory contract per workspace |
| ADR-007 | MCP API surface uniform across backends |
| ADR-008 | Path 1 strict (MCP-only writes; no daily reconciliation sync) |

Should be written to
`01 - Projects/08 - Donna AI/Decisions/ADR-NNNN-*.md` (vault) — they
encode locked design decisions for future engineers.

## Open spec questions (spec §17)

Spec rev 3 has open items at §17 that the team should resolve before
v1.0.0 stable:

- ... (left for the spec author to enumerate and assign owners)

## Summary

- Current state: P0 → P0.13 complete; 11/11 tests green
- Next sprint: P8 (Gmail/Drive) + P9 (MCP API) + P10 (vault projection)
- Post-v1: R6/R7/R8 + GitHub/S3 backends + Obsidian plugin
- Stage 3: graphiti / FalkorDB / dynamic ontology
