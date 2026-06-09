# Implementation State

What's shipped (P0 → P0.13) and what remains.

## Phases completed

### P0 — Foundation fixes (namespace + stubs)

- `donna/core/ocr/*.py` — 6 files renamed from `docupal.core` to
  `donna.core`
- `donna/core/ocr/image_enhancement.py` — stub (raises
  NotImplementedError; default `enhance_images=False` skips the call)
- `donna/core/llm/*.py` — 7 files renamed from `docupal.core` to
  `donna.core`
- `donna/core/observability/__init__.py` + `decorators.py` — no-op
  `observe_llm` decorator stubs

### P1 — Cortex app skeleton + cortex_entity migration

- `donna/cortex/__init__.py` + `apps.py` — Django app config,
  template discovery at `apps.ready()`
- `donna/cortex/models.py` — `CortexEntity` model (spec-aligned)
- `donna/cortex/schemas.py` — Pydantic `SilverEntity` + 12 per-type
  extensions
- `donna/cortex/linter.py` — `FrontmatterLinter` with 11 individual
  checks
- `donna/cortex/repository.py` — `CortexEntityRepository` with three
  reverse-edge writers
- `donna/cortex/migrations/0001_initial.py` — pgvector + GIN + IVFFLAT
  indexes, full spec-aligned schema
- `donna/cortex/tests/test_repository.py` — 5 tests
- `donna.cortex` in `INSTALLED_APPS`
- `pyproject.toml` — `pgvector>=0.3.0` added
- `docker-compose.yml` — `postgres:17-alpine` → `pgvector/pgvector:pg17`

### P2 — OCR shim

- `donna/cortex/ocr.py` — `OCRService` thin shim around
  `donna.core.ocr.create_ocr`

### P3 — TypeSpec registry + 12 TypeSpecs + 12 Jinja templates + TemplateEngine

- `donna/cortex/registry.py` — `TypeSpec` dataclass + `register_type`
  decorator + `TemplateRegistry`
- `donna/cortex/template_engine.py` — Jinja2 `TemplateEngine` +
  `NoOpFitter` + `HaikuFitter`
- `donna/cortex/templates/__init__.py` — discovery marker
- 12 TypeSpec modules: `meeting.py, email.py, chat.py, doc.py,
  ticket.py, clip.py, note.py, person.py, org.py, project.py,
  concept.py, decision.py`
- 12 Jinja templates: matching `.j2` files
- `donna/cortex/tests/test_registry.py` — 3 tests
- `pyproject.toml` — `jinja2>=3.1.0` added

### P4 — Embed + Cluster + HaikuNamer + nightly beat

- `donna/cortex/embeddings.py` — `EmbeddingStrategy` Protocol +
  `BGESmallEmbedder` (lazy sentence-transformers)
- `donna/cortex/clustering.py` — `Scope` dataclass +
  `HDBSCANClusterer` (online assign + nightly recluster) +
  `HaikuNamer` (LiteLLM) + `ClusteringService`
- `donna/cortex/tasks.py` — Celery `recluster_workspace` +
  `recluster_fanout`
- `donna/cortex/template_engine.py` — `HaikuFitter` added
- `donna/settings.py` — `cortex-recluster-fanout` beat schedule
- `pyproject.toml` — `litellm>=1.55.0`, `python-dotenv>=1.0.0` added

### P5 — Entity extract + resolve + bidirectional edges

- `donna/cortex/entities.py` — `ProviderMetadataExtractor` +
  `GLiNERExtractor` (lazy) + `CompositeExtractor` (Chain of
  Responsibility) + `DeterministicResolver` (match or spawn)
- Spawned rows ship with full provenance (`author=donna`,
  `source=cortex://spawn/<id>`, `confidence=medium`, body footer
  `Spawned by: cortex-resolver`)

### P6 — FolderResolvers + DerivedNamespaceView

- `donna/cortex/folders.py` — 9 resolvers (`TemporalFolderResolver,
  ChatFolderResolver, TicketFolderResolver, FlatFolderResolver,
  PersonFolderResolver, ConceptFolderResolver, OrgFolderResolver,
  ProjectFolderResolver, DecisionFolderResolver`) + scope-prefix
  helper + `DerivedNamespaceView`

### P7 — CortexWriter facade + wire Fathom + end-to-end tests

- `donna/cortex/pipeline.py` — `CortexWriter` with 11-step
  `write(dp)` method, `PROVIDER_TYPE_MAP`, `PROVIDER_URI_SCHEME`
- `donna/integrations/connectors/fathom/tasks.py` — best-effort
  cortex hop appended after DeliveryPackage upsert
- `donna/cortex/tests/test_pipeline.py` — 3 end-to-end tests

### P0.5 → P0.13 — Spec alignment (the rewrite)

After P7 landed, the original plan (`peppy-sleeping-moler.md`) was
compared against the **Cortex Universal Silver Specification v1
(rev 3)** in the vault. Major divergences identified; full
remediation completed:

| Phase | Changes |
|---|---|
| **P0.5** | Type enum 9→12 (rename `message_thread→chat`, `file→doc`; add `ticket, concept, decision`) |
| **P0.6** | Add columns: `author, source, client_id, project_id, confidence, last_synthesized`, promote `bronze_storage_key + cluster_id` to columns |
| **P0.7** | Edge fields refactor: rename `related→entity_refs`; add `cross_refs, supersedes, parent, superseded_by, contradicts`; redefine `related` as curated↔curated only |
| **P0.8** | Sub-discriminators: `doc_type` (16-value Literal), `note_type` (5-value), `org.relationship` (6-value), `project.status`, `decision.adr_status`, `concept.maturity`, `ticket.provider` |
| **P0.9** | Org `self` invariant — exactly one org per workspace carries `relationship: self` |
| **P0.10** | Clustering scope: `(workspace, client, project)` tri-key in `Scope` dataclass |
| **P0.11** | Linter R1-R10 + `TYPE_AUTHORITY` 30-key numeric registry + 13 `RejectCode` values + 8 hard rejects per spec §7.2 |
| **P0.12** | `SilverStorage` Protocol + `LocalFSStorage` skeleton (flock + atomic rename); `GitHubStorage` + `S3Storage` stubbed |
| **P0.13** | Postgres-as-derived-index reframe (model.py docstring, plan docs) |

## Test status

11/11 tests pass.

```
test_pipeline.CortexPipelineTests:
  test_idempotent_first_write                              ok
  test_meeting_writes_cortex_entity                        ok
  test_person_org_spawn_and_entity_refs                    ok
test_registry.TypeSpecTests:
  test_all_twelve_types_registered                         ok
  test_meeting_renders                                     ok
  test_meeting_typespec                                    ok
test_repository.CortexRepositoryTests:
  test_find_referencing                                    ok
  test_save_creates_row                                    ok
  test_scope_filter                                        ok
  test_sources_updates_applied_in                          ok
  test_supersedes_assigns_superseded_by                    ok
```

## Files added (cortex app)

```
donna/cortex/
├── __init__.py
├── apps.py
├── models.py
├── schemas.py
├── registry.py
├── linter.py
├── repository.py
├── authority.py            (TYPE_AUTHORITY + RejectCode)
├── storage.py              (SilverStorage Protocol + LocalFSStorage)
├── folders.py
├── ocr.py                  (shim → donna.core.ocr)
├── embeddings.py
├── clustering.py
├── tasks.py
├── pipeline.py
├── template_engine.py
├── migrations/
│   ├── __init__.py
│   └── 0001_initial.py
├── templates/
│   ├── __init__.py
│   ├── meeting.py + meeting.j2
│   ├── email.py + email.j2
│   ├── chat.py + chat.j2
│   ├── doc.py + doc.j2
│   ├── ticket.py + ticket.j2
│   ├── clip.py + clip.j2
│   ├── note.py + note.j2
│   ├── person.py + person.j2
│   ├── org.py + org.j2
│   ├── project.py + project.j2
│   ├── concept.py + concept.j2
│   └── decision.py + decision.j2
└── tests/
    ├── __init__.py
    ├── test_pipeline.py
    ├── test_registry.py
    └── test_repository.py
```

## External dependencies added

| Package | Why |
|---|---|
| `pgvector>=0.3.0` | `vector(384)` column + `VectorField` Django field |
| `jinja2>=3.1.0` | TemplateEngine |
| `litellm>=1.55.0` | HaikuNamer + HaikuFitter via `LLMFactory` |
| `python-dotenv>=1.0.0` | `provider.py` import dependency |

Lazy-imported (NOT in pyproject):

| Package | Used by | Status |
|---|---|---|
| `sentence-transformers` | `BGESmallEmbedder` | install when embeddings enabled |
| `hdbscan` | `HDBSCANClusterer` | install when clustering enabled |
| `numpy` | both above | transitive of either |
| `gliner` | `GLiNERExtractor` | install when GLiNER enabled |

## Docker stack changes

| Service | Change |
|---|---|
| `database` | `postgres:17-alpine` → `pgvector/pgvector:pg17` (PG17, pgvector 0.8.2 bundled) |

Existing volume data compatible (same PG17 on-disk format).

## Files modified outside cortex/

| File | Change |
|---|---|
| `donna/settings.py` | `INSTALLED_APPS += 'donna.cortex'` + `cortex-recluster-fanout` beat schedule |
| `donna/integrations/connectors/fathom/tasks.py` | Best-effort `CortexWriter().write(package)` after DeliveryPackage upsert |
| `pyproject.toml` | 4 deps added |
| `docker-compose.yml` | DB image swap |
| `donna/core/ocr/*` (6 files) | namespace rename |
| `donna/core/llm/*` (7 files) | namespace rename |
| `donna/core/observability/*` (2 new files) | stub decorator |
| `donna/core/ocr/image_enhancement.py` (new) | stub module |

## What "in P7" means right now

Run `docker exec donna-server python manage.py test donna.cortex.tests -v 2`
and you get 11/11 green:

- 1 Fathom-shaped DeliveryPackage → cortex_entity persisted
- Spawned person + org rows via the extractor pipeline
- Bidirectional edges (sources↔applied_in, supersedes↔superseded_by)
- Scope filter query works
- All 12 TypeSpecs register at app startup
- Meeting Jinja template renders with closed-vocab frontmatter

## What "NOT YET" looks like

- No MCP API endpoints exist (`/cortex/index`, `/cortex/log`,
  `/cortex/entity/{id}`)
- No `SilverStorage` writes (Postgres-only today)
- Gmail + Drive connectors not yet wired
- No `_index.md` / `_log.md` auto-regeneration
- No Obsidian plugin / CLI / pre-commit hook (Path 1 strict)
- R6, R7, R8 background workers not implemented
- No real-data run yet — only test fixtures
