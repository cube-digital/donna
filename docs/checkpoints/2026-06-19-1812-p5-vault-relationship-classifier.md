# 2026-06-19 18:12 — P5 Vault + Org Relationship Classifier

## Summary & Overview

Shipped **Phase 5 vault projection** (hierarchical disk render + spec §14 rebuild round-trip), **Drive OCR wire-up** (OCRService shim into ingest task), and a **multi-tier org relationship classifier** (Tier A rules + Tier B Haiku + manual CSV override with multi-label `roles[]` and indirect `client_of[]`). Cube-digital now renders to a clean `vault/<ws>/{clients,partners,vendors,peers}/<slug>/{org.md, emails/YYYY/MM/...}` hierarchy with multi-label badges (`**Also:** client`, `**Client of:** [[Weasweb]]`) in per-org `_index.md`. 25 orgs manually corrected via CSV and locked against future reclassification. Vault frontmatter now carries the relationship truth so `cortex_sync --rebuild` restores everything after a DB wipe.

End state: 366 entities rendered (279 email + 64 person + 24 org), 4 classifier-driven buckets populated, durable rebuild path proven (278 entities round-tripped, 0 errors).

## Key Learnings

- **Three-layer storage model** — Postgres is canonical for the agent, FLAT `cortex/<ws>/<type>/<id>.md` is the id-addressable physical store, hierarchical `vault/<ws>/<bucket>/<slug>/` is the human/Obsidian projection. All three coexist; flat path is what `entity.body` (FileField) points at, vault path is render-time projection. Scope changes (relationship flip) only touch JSON, never `mv` the flat copy.

- **Folder-as-LLM-contract** — wrong folder = wrong belief. Airline (Animawings) tagged `client` and filed under `clients/animawings/` meant agent answered "list our clients" with airlines. The hierarchy isn't just for humans; it's a prompt signal the LLM trusts implicitly.

- **Live recompute > cached `parent_path`** — `VaultRenderer._recompute_parent_path()` calls the folder resolver on every render instead of trusting `extensions.parent_path`. Without this, scope/relationship flips leave stale dir trees. The cached value still gets backfilled (so `render_index` queries don't iterate stale folders) but render itself is authoritative.

- **Classifier ladder** — Tier A (rules) catches ~50% with high precision and zero cost. Tier B (Haiku, ~$0.001-0.005/org) catches another ~15% but honestly returns `unknown` when signal is thin (outbound-only orgs). Tier C (manual CSV) closes the gap with 100% accuracy + `relationship_locked=True` prevents future classifier from overwriting.

- **Multi-label is real** — single-relationship field is too narrow. Robonnement and Reshapedigital are BOTH partner AND client. Schema gap solved with `roles: list[OrgRelationship]` (primary `relationship` still drives folder routing, `roles[]` powers badge display + future agent filtering).

- **Indirect relationships as graph edges** — `client_of: list[org_uuid]` captures "ki is client of weasweb". Not a tag on ki, but a directed edge ki→weasweb. Renders as `**Client of:** [[Weasweb]]` badge. Phase 7 stretch will add agent queries like "show me everything happening with our partner's clients".

- **Vault as durable truth** — relationship fields injected into org `_index.md` frontmatter (`id`, `content_hash`, `source`, `relationship`, `roles`, `client_of`, `relationship_locked`). `cortex_sync --rebuild` walks vault → parses frontmatter → recreates rows with manual overrides intact. CSV is purely operational; vault tar = full workspace knowledge.

- **Jinja template inlining bug** — pipeline-rendered bodies sometimes emit `occurred_at: 2026-05-27 12:21:30+00:00parent_path: emails/2026/05` (no newline between fields). The frontmatter parser uses `(?<![a-zA-Z_])<field>:` regex with lookahead constrained to known field names — survives the merged-line case without yaml dep.

- **InMemoryStorage for test isolation** — `sys.argv contains 'test'` → `STORAGES["default"] = InMemoryStorage` + `CORTEX_VAULT_ENABLED=False` default. Zero FS residue after a test run. Tests that exercise the renderer opt in via `@override_settings(CORTEX_VAULT_ENABLED=True)`.

- **Cluster-aware classification potential** — clusters are already named by Haiku (free signal). `cluster_name="Invoices"` → vendor; `cluster_name="Project deliverables"` → client. Plus cluster co-occurrence with `self` org (joint-work signal), cluster diversity (depth of relationship), and label propagation (40% cluster overlap with known client → strong client prior). All free. Documented in [00m §Future signals](docs/important-docs/00m%20-%20org-relationship-taxonomy.md).

## Solutions & Fixes

- **Drive ingest had OCR engine but no caller** → Recreated `OCRService` shim at `donna/core/ocr/service.py` (mirrors `core/extractors/` pattern), wired into `ingest_drive_file` after binary download. Writes OCR text as bronze sidecar at both `bin_key` + `storage_key` so pipeline tier-1 sidecar lookup finds it. Root cause: 2026-06-15 refactor deleted the cortex-side shim but kept the engine.

- **Pipeline scope step read `dp.metadata` (empty for canonical-emit adapters)** → Updated step 5 to ALSO read `canonical_payload.extensions.participants_emails` (where Gmail puts senders). Root cause: Phase 2 canonical migration moved fields but pipeline scope ladder kept the old metadata path.

- **`_spawn_org` didn't write `slug` to extensions** → Folder resolver can't compute `clients/<slug>/` without it. Root cause: spawn computed `slug` as local var only.

- **`_spawn` didn't compute `parent_path`** → Spawned person/org entities landed with NULL parent_path → vault renderer skipped them OR put them at workspace root. Root cause: `_spawn` was a side-effect-only path; only the main pipeline entity went through step 6 folder resolver. Fix: `_spawn` now runs the folder_resolver itself before save.

- **`source` empty on 278 rebuilt cortex entities** → Vault frontmatter didn't carry `source`, so `cortex_sync --rebuild` set `source=""`. Root cause: VaultRenderer injected only `id` + `content_hash`. Fix: also inject `source`.

- **`scope_slugs_for` hardcoded `clients/` prefix** → Returned `<slug>` only; pipeline appended `clients/`. After multi-bucket taxonomy, needed relationship-aware prefix. Fix: `scope_slugs_for` now returns `<bucket>/<slug>` (e.g. `"vendors/animawings"`) using folder resolver helpers, `_scope_prefix` uses it verbatim.

- **`folder_resolver` for org used CALLER's scope, not own slug** → All orgs ended up under whatever client the email was scoped to. Fix: `folders.org` now reads `extensions.slug` (own slug) and `extensions.relationship` to compute its own folder.

- **Stale `parent_path` on existing rows after relationship flip** → 89 emails still pointed at old `unknown/<slug>/emails/...`. Fix: `refresh_parent_paths.py` walks every head entity → calls `_recompute_parent_path` → saves new value. Run after any classifier change.

- **`_PROMPT.format(...)` interpreted JSON `{"relationship":...}` as format placeholder** → Tier B Haiku call crashed with `KeyError: '"relationship"'`. Fix: escape braces in prompt template.

- **`anthropic/claude-3-5-haiku-latest` 404** → Account doesn't have that exact ID. Fix: switched to `anthropic/claude-haiku-4-5-20251001`.

- **`yaml` not installed** → Frontmatter parser uses regex extractor with negative lookbehind `(?<![a-zA-Z_])` to handle digit→letter boundary in malformed `12:21:30+00:00parent_path:` strings.

## Decisions Made

- **Drop `Workspace.vault_render_mode` field** — YAGNI. Single global `CORTEX_VAULT_ENABLED` env flag instead. Per-workspace toggle deferred until a real use case appears. Migration is permanent (field stays added — workspace already has `primary_domain` next to it).

- **Vault uses `org.md`/`project.md` canonical filenames inside per-entity folder** — `clients/<slug>/org.md` not `clients/<slug>.md`. Spec-canonical, matches projects → `clients/<x>/projects/<y>/project.md`. Implemented via `_CANONICAL_FILENAMES` map in VaultRenderer.

- **Single global classifier env vs per-workspace** — same logic as vault. Add per-workspace control when there's a real second case.

- **Multi-label `roles[]` + primary `relationship`** — chose over single field + UI overrides. Folder routing uses primary; agent + Obsidian see full label set. Manual CSV import sets `relationship_locked=True` so classifier never overwrites.

- **Don't keep per-workspace correction CSVs** — each workspace has unique taxonomy, no cross-workspace reuse. Import once, delete CSV, vault frontmatter is the durable store. Per-workspace correction artifacts only exist transiently in `/tmp/` during import.

- **Cluster-aware classification deferred to Phase 6** — added as maintenance task `cluster_aware_org_reclassify` in [00f §10](docs/important-docs/00f%20-%20silver-completion-plan.md). Eval-gated; ships behind Phase 6 eval harness.

- **A + B classifier strategy** — rule-based first (free, deterministic), Haiku second (~$0.05/workspace), manual third. Skip option C (web enrichment) entirely — Haiku will keep guessing without out-of-band knowledge.

## Pending Tasks

- [ ] Re-auth Fathom OAuth in the UI → run reingest → meetings populate `<bucket>/<slug>/meetings/YYYY/MM/`. Currently 0 Fathom DPs.
- [ ] Grant Drive folder access via Picker UI (token scope is `drive.file`, can't list arbitrary folders) → re-run `/tmp/reingest_drive.py` → PDFs flow through OCR ladder → bodies populate.
- [ ] Phase 6 — eval harness (golden questions, Recall@10/MRR), then cluster-aware org reclassifier (00m §Future signals).
- [ ] Phase 6 — `train_doc_classifier` (TF-IDF + LogReg for doc_type tier B+).
- [ ] A2 — drafting layer (UC2): Document migration + 4 draft tools + DrafterNode.
- [ ] A3 — agent memory + config + polish (rolling summary, query+rewrite cache).
- [ ] Commit dirty files. Check `git status`.

## Errors & Workarounds

- **`KeyError: '"relationship"'`** — in `relationship_classifier_llm._PROMPT.format(...)`. Workaround: escaped JSON braces as `{{` `}}`. Proper fix: already applied.
- **`litellm.NotFoundError: AnthropicException - {"type":"error","error":{"type":"not_found_error","message":"model: claude-3-5-haiku-latest"}}`** — Tier B Haiku call. Workaround: switched to `anthropic/claude-haiku-4-5-20251001`. Proper fix: applied.
- **`django.db.utils.IntegrityError: null value in column "occurred_at" of relation "cortex_entities" violates not-null constraint`** — first `cortex_sync --rebuild` attempt. Workaround: added `datetime.fromisoformat(occurred_str)` parse in rebuild path with sane fallback. Proper fix: applied.
- **`django.core.exceptions.FieldError: Cannot resolve keyword 'superseded_by_id' into field`** — wrong field name in early VaultRenderer + cortex_sync. Fix: bulk sed replaced `superseded_by_id__isnull` → `superseded_by__isnull` (FK uses `_id` suffix in DB column, but Django ORM field name is `superseded_by`).
- **`HTTPStatusError: '401 Unauthorized'` on Fathom `/meetings`** — token expired. Workaround: skipped Fathom reingest; meetings remain at 0. Proper fix: user must re-auth via OAuth flow in UI.
- **`iter_folder_descendants("root")` returns 0 for Drive** — token scope is `drive.file` (per-file access only). Workaround: documented blocker. Proper fix: user grants folder access via Picker UI OR re-auths with `drive.readonly` scope.

## Files Modified

### New
- `docs/important-docs/00m - org-relationship-taxonomy.md` — full taxonomy spec + classifier ladder + Future signals (cluster-aware)
- `server/donna/core/ocr/service.py` — `OCRService` shim
- `server/donna/cortex/vault_renderer.py` — `VaultRenderer` + `_augment_frontmatter` + `parse_frontmatter` + `_recompute_parent_path` + `_org_badge_lines`
- `server/donna/cortex/relationship_classifier.py` — Tier A rule-based classifier
- `server/donna/cortex/relationship_classifier_llm.py` — Tier B Haiku classifier
- `server/donna/cortex/data/known_vendors.txt` — ~120 SaaS/airline/cloud domains
- `server/donna/cortex/tests/test_vault_renderer.py` — 12 tests including rebuild round-trip
- `server/donna/integrations/connectors/google/drive/tests/test_ocr_integration.py` — 8 tests
- `server/donna/integrations/connectors/google/drive/tests/__init__.py`
- `server/donna/workspaces/migrations/0002_workspace_primary_domain.py`
- `server/scripts/cleanup_test_residue.sh` — orphan workspace dir sweeper

### Edited
- `server/donna/cortex/schemas.py` — `OrgRelationship` adds peer/unknown; `OrgExtensions` adds `roles[]`, `client_of[]`, `relationship_*` fields
- `server/donna/cortex/entities.py` — wired Tier A into `_spawn_org`; added `slug` to `_spawn_person`; `_spawn` computes `parent_path` via folder resolver
- `server/donna/cortex/folders.py` — `org` resolver branches by relationship; `_scope_prefix` accepts relationship-aware prefix
- `server/donna/cortex/scope.py` — `scope_slugs_for` returns `<bucket>/<slug>` instead of just slug
- `server/donna/cortex/pipeline.py` — extracted `_scope_slugs` to scope.py; deleted `_build_extensions` legacy method (~125 lines); fixed scope step to read canonical_payload
- `server/donna/cortex/managers.py` — `_render_and_flag` post-commit vault hook
- `server/donna/cortex/tasks.py` — `flush_vault_indexes` Celery task; `reclassify_orgs` task; `_body_excerpt_for` helper
- `server/donna/cortex/management/commands/cortex_sync.py` — `--render`, `--rebuild`, `--reclassify-orgs`, `--no-llm`, `--correct-orgs` flags
- `server/donna/cortex/services.py` — `relationship` filter in `query` + `_filtered_heads`
- `server/donna/cortex/tests/test_pipeline.py` — fixture canonical_payload to satisfy strict pipeline
- `server/donna/cortex/tests/test_sync_command.py` — stale `--rebuild` blocked test → runs test
- `server/donna/integrations/connectors/google/drive/tasks.py` — OCR call after binary download
- `server/donna/chat/agents/tools/cortex_read.py` — `relationship` arg on CortexQueryArgs
- `server/donna/chat/agents/prompts.py` — `ORG_TAXONOMY` block
- `server/donna/workspaces/models.py` — `primary_domain` field
- `server/donna/settings.py` — `CORTEX_VAULT_ENABLED` env, beat entries, InMemoryStorage test swap
- `docs/important-docs/00f - silver-completion-plan.md` — Phase 5 marked shipped + Phase 6 cluster-aware row added
- `docs/important-docs/00i - silver-implementation-reference.md` — Phase 5 section rewritten with shipped details

### Deleted
- `server/donna/cortex/pipeline.py` `_build_extensions` + `_attendees` + `_participants` + `_emails` helpers (~125 lines, legacy pre-canonical fallback)

## Blockers & External Dependencies

- **Fathom OAuth expired** — `HTTPStatusError 401`. Unblocks when: user re-auths Fathom via OAuth flow in the UI.
- **Drive scope = `drive.file`** — token only sees files explicitly granted via Picker UI. Unblocks when: user grants folder access via Picker OR re-auths with `drive.readonly` scope.
- **Anthropic API key** — required for Tier B Haiku classifier + agent runs. Currently configured in `server/env/.env.docker`. Unblocks: already set.
- **PostgreSQL primary_domain** — set manually to `cube-digital.io` via the reclassify script. Future workspaces: needs UI onboarding step OR inferred from owner's email domain.
