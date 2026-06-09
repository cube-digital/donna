# Spec Gap Analysis

Where the current implementation matches the spec, where it diverges,
and what's deliberately deferred.

## Spec source

`01 - Projects/08 - Donna AI/Plans/Cortex Universal Silver Specification.md`
(vault, rev 3, 2026-06-02). The implementation was retroactively
realigned in phases P0.5-P0.13 after the initial P0-P7 build.

## Matches (locked invariants per spec §18)

| Invariant | Status |
|---|---|
| 12 canonical Silver types (closed) | ✅ matches |
| 9 edge types (closed) | ✅ matches |
| `SilverEntity` Pydantic schema core fields | ✅ matches (`SilverEntity` model in schemas.py) |
| R1 — immutability | ⚠️ enforced at MCP API layer (P9); pre-MCP, every write creates new row |
| R2 — both timestamps | ✅ enforced (`occurred_at` required, `created_at` auto) |
| R3 — explicit supersession | ✅ enforced (no delete path; chain via `supersedes`) |
| R4 — `cross_refs` intra-scope | ⚠️ shape check only; scope check deferred |
| R5 — `TYPE_AUTHORITY` | ✅ registry exists; conflict resolution helper ready |
| R6 — Gold-resynth trigger | ❌ not implemented |
| R7 — contradiction detection | ❌ not implemented (auto-detect missing); plumbing ready |
| R8 — confidence decay | ❌ not implemented |
| R9 — touchpoints derived | ✅ derived via `find_referencing` |
| R10 — plan shipped immutability | ⚠️ enforced at MCP API layer (P9) |
| `TYPE_AUTHORITY` 30-key registry | ✅ matches |
| 4 extension points | ⚠️ schemas extensible per type; physical extension folder structure not yet built |
| MCP API surface (8 methods) | ❌ not built (P9) |
| Storage abstraction (3 backends) | ⚠️ `SilverStorage` Protocol + `LocalFSStorage` skeleton only; GitHub/S3 stubbed |
| Bronze separation | ✅ DeliveryPackage + default_storage separate from cortex_entities |
| Golden Questions contract | ❌ no eval harness yet |
| Universal folder structure | ⚠️ folder resolvers compute paths; `_index.md` / `_log.md` regeneration deferred |
| Path 1 strict (MCP-only writes) | ❌ not enforced; Obsidian plugin + pre-commit hook not built |
| Workspace owner entities at root | ✅ folder resolvers handle null-scope cases |
| Workspace ADR `ADR-W` prefix | ✅ `DecisionFolderResolver` honours scope distinction |
| Exactly one org per workspace `relationship: self` | ⚠️ schema allows it; uniqueness check deferred |

## Per-type schema matches

| Type | Match? | Notes |
|---|---|---|
| `meeting` | ✅ | `MeetingExtensions` matches |
| `email` | ✅ | `EmailExtensions` matches |
| `chat` | ✅ | `ChatExtensions` matches (was `message_thread` in original P0-P7) |
| `doc` | ✅ | `DocExtensions` matches; `doc_type` 16-value Literal |
| `ticket` | ✅ | `TicketExtensions` matches; 5-value provider Literal |
| `clip` | ✅ | matches |
| `note` | ✅ | `note_type` 5-value Literal |
| `person` | ✅ | matches |
| `org` | ✅ | 6-value `relationship` Literal incl. `self` |
| `project` | ✅ | `status` 4-value Literal |
| `concept` | ✅ | `maturity` 3-value Literal |
| `decision` | ✅ | `adr_status` 3-value Literal; `context_sources` required |

## Per-edge field matches

| Edge | Status | Notes |
|---|---|---|
| `entity_refs` | ✅ shipped | column on row; GIN-indexed |
| `sources` | ✅ shipped | column; back-write to `applied_in` atomic |
| `cross_refs` | ✅ shipped | column; R4 scope check deferred |
| `supersedes` | ✅ shipped | column; back-write to `superseded_by` atomic |
| `parent` | ✅ shipped | column UUID, btree-indexed |
| `related` | ✅ shipped | column; restricted-to-curated rule not enforced yet |
| `applied_in` | ✅ shipped | reverse-edge column; atomic update via `select_for_update` |
| `superseded_by` | ✅ shipped | reverse-edge column |
| `contradicts` | ✅ shipped | reverse-edge column; symmetric write atomic |

## Major divergences (now resolved by P0.5-P0.13)

These were the original P0-P7 divergences identified vs spec; all
fixed in the spec-alignment pass:

| Original P0-P7 | Spec | Fixed in |
|---|---|---|
| 9 types | 12 types | P0.5 |
| 3 edge fields (`sources, applied_in, related` misnamed) | 9 edge fields | P0.7 |
| No `author/source/confidence/last_synthesized` columns | required by spec | P0.6 |
| No `client_id/project_id` columns | required by spec §6 | P0.6 |
| `bronze_storage_key + cluster_id` in JSONB | columns per spec | P0.6 |
| No sub-discriminators (`doc_type`, `note_type`, etc.) | required by spec §3.3-3.4 | P0.8 |
| Linter: 3 generic checks | 11 checks + R1-R10 | P0.11 |
| No `TYPE_AUTHORITY` registry | required by R5 | P0.11 |
| Clustering scoped to workspace only | scope tri-key required | P0.10 |
| No org `relationship: self` invariant | required by spec §3.2 + §18 | P0.9 |
| No `SilverStorage` abstraction | required by spec §8 | P0.12 |

## Remaining gaps (deferred)

| Gap | Phase to fix | Priority |
|---|---|---|
| MCP API endpoints (`/cortex/index`, `/cortex/log`, `/cortex/entity/{id}`) | P9 | high |
| `cortex.create_entity` API method | P9 | high |
| `cortex.update_entity` (R1 immutability enforcement) | P9 | high |
| `cortex.query` (with scope filters) | P9 | high |
| `cortex.linter_check` (dry-run) | P9 | medium |
| `cortex.health` | P9 | low |
| `_index.md` / `_log.md` auto-regeneration | P9 + P10 | high (Mode A vault) |
| GitHub + S3 storage backends | post-v1 | medium (cloud clients) |
| Obsidian plugin (Path 1 strict UI) | post-v1 | medium |
| CLI `donna` | post-v1 | medium |
| Pre-commit hook | post-v1 | low |
| R6 — Gold-resynth Celery task | post-v1 | medium |
| R7 — contradiction-detection entailment model | post-v1 | medium |
| R8 — confidence decay Celery task | post-v1 | low |
| R10 — plan-shipped immutability | P9 (MCP API) | medium |
| Golden Questions eval harness | post-v1 | medium |
| Workspace `_meta/extensions/` discovery | post-v1 | low |
| Gmail + Drive ingest connectors wired | P8 | high |
| Slack / WhatsApp / Linear / Jira / GitHub connectors | per client demand | varies |
| Postgres-rebuild-from-storage job (`donna sync --rebuild`) | post-v1 | medium |

## Minor known issues

| Issue | Impact | Fix |
|---|---|---|
| `DocExtensions.doc_type` is required; spawned `doc` rows (if any) would need it | currently no spawn path for `doc` type | n/a — extractor doesn't spawn docs |
| `ConceptExtensions` allows spawn even with <2 sources | linter rejects via R-INSUFFICIENT_EVIDENCE; spawn path bypasses linter | document; flag for human review |
| `R-DUPLICATE` is enforced by PG unique constraint; not by linter dry-run | upsert behaviour differs from spec's stated "returns existing entity_id" | P9 will return existing on conflict |
| Synthesized concept naming has no R6 trigger | concepts can sit at `maturity: seed` forever | post-v1 |

## Pre-spec scope (out of scope for v1)

The spec is intentionally narrow. These are explicitly OUT of v1:

- **Agent orchestrator** (route planner, parallel subagents over `/cortex/*` API). Separate plan.
- **Chunk-level embeddings + chunk kNN retrieval.** Agent navigates `_index.md` + `_log.md` instead.
- **Dynamic ontology** (LLM proposes new types). Stage 3.
- **FalkorDB / graphiti bi-temporal graph layer.** Stage 3.
- **File-watcher reverse-sync** (vault edits → Cortex). Post-v1.

## Acceptance verdict

| Section | Verdict |
|---|---|
| Data model (§3, §5) | ✅ matches |
| Edges (§4) | ✅ matches |
| Scope boundary (§6) | ✅ matches |
| Linter R1-R10 (§7) | ⚠️ R1, R4, R6-R8, R10 partial or deferred |
| Storage (§8) | ⚠️ Protocol shipped, only LocalFS stub |
| Folder structure (§9) | ⚠️ paths computed; `_index.md` deferred |
| Path 1 strict (§10) | ❌ not enforced |
| Connector mapping (§11) | ⚠️ Fathom wired; Gmail + Drive next |
| Extension points (§12) | ⚠️ schemas extensible; folder structure deferred |
| Golden Questions (§13) | ❌ not built |
| Postgres derived (§14) | ✅ documented; storage-backed write deferred to P9 |
| ADRs baked (§15) | ❌ 8 ADRs not yet written to `decisions/` |
| LEAN migration (§16) | n/a — separate plan |
| Open spec questions (§17) | deferred |
| Invariants (§18) | ✅ schema-level all in place |

**Net:** schema + Pydantic + edges + clustering + linter all
spec-aligned. MCP API + storage write + R6/R7/R8 + Path 1 enforcement
are the next phases.

See [`03-roadmap-remaining-work.md`](./03-roadmap-remaining-work.md)
for prioritised next steps.
