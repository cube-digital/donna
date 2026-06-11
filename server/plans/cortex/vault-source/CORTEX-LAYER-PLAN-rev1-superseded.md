> **SUPERSEDED** — This plan (rev 1) is the original 9-step pipeline design.
> The locked contract is now `vault-source/SPEC.md` (Universal Silver Specification rev 3).
> Kept here for historical reference per ADR-0001 supersession protocol.
> Implementation expansion lives in the engineering companion docs at `server/plans/cortex/00-vision.md`, `01 - architecture/`, etc.

---

---
type: plan
domain: ai-platform
status: draft
created: 2026-06-01
updated: 2026-06-01
sources:
  - "[[01 - Projects/08 - Donna AI/Wiki/Architecture/Ingestion Pipeline - Bronze Silver Gold]]"
applied_in: []
related:
  - "[[01 - Projects/08 - Donna AI/Wiki/Architecture/_index|Architecture catalog]]"
  - "[[01 - Projects/08 - Donna AI/Donna AI]]"
tags:
  - type/plan
  - domain/ai-platform
  - domain/cortex
  - status/draft
---

# Plan — Donna Cortex Layer (Silver Tier)

A Bronze→Cortex authoring engine organized as five composable subsystems behind a single facade. Each subsystem is a Strategy with a registered default, swappable without touching the orchestrator.

## Context

Donna ingests external sources (Fathom, Gmail, Drive) into a flat **Bronze** layer: `default_storage` blob + `DeliveryPackage` row (`server/donna/integrations/models.py`). Adapters expose `to_text()` / `to_markdown()` / `metadata()` (`server/donna/core/integrations/adapter.py`). Postgres holds chat messages today; pgvector is preferred for embeddings per `server/donna/core/db/__init__.py:5-6`. FalkorDB is provisioned for a future Graph layer (`server/donna/settings.py:119-130`) but unused.

The Cortex layer turns each Bronze artifact into a structured, queryable, cluster-organized entity with bidirectional cross-references. It is the substrate the agent layer (separate follow-on plan) navigates. Five concerns drive the design:

1. **Document OCR** — heterogeneous source bytes → uniform markdown
2. **Topical Clustering** — embedding-based, emergent folder structure
3. **Entity Reference** — GLiNER + provider metadata → person / org / project graph
4. **Folder Structure Generation** — cluster + entity + temporal axes projected as folders
5. **Template Application** — Jinja templates per entity type enforce a strong convention

All five compose into one pipeline orchestrator. Each is independently testable and replaceable.

---

## Scope

**In scope**

- New Django app `donna/cortex` per `server/plans/03-conventions-and-api.md`.
- One Postgres table `cortex_entity` (+ pgvector) as source of truth; edges in `data` JSONB.
- Five subsystems behind Strategy / Registry interfaces (detailed below).
- Pydantic-validated `data` schema per type.
- Hookup: connectors call `CortexWriter().write(delivery_package)` after `DeliveryPackage` upsert.
- Three planning docs in `server/plans/`.
- Optional `vault_renderer` Celery task projecting Cortex → `_index.yaml` + `_log.yaml` + entity `.md` files + git commit (Mode A; on-demand for Mode B).

**Out of scope**

- Agent orchestrator (route planner + parallel subagents) — next plan; consumes this plan's API.
- Chunk-level embeddings + chunk kNN retrieval — agent navigates index/log instead.
- Dynamic ontology (LLM proposes new types) — Stage 3.
- FalkorDB / graphiti bi-temporal Graph layer — Stage 3.
- File-watcher reverse-sync (vault edits → Cortex) — post-v1.

---

## Architecture overview

```
                     CortexWriter           ← Facade. Single entry point.
                          │
            ┌─────────────┼─────────────┐
            │             │             │
      ┌─────▼─────┐  ┌────▼────┐  ┌─────▼──────┐
      │ OCR       │  │ Embed + │  │ Entity     │
      │ Service   │  │ Cluster │  │ Extract +  │
      │           │  │         │  │ Resolve    │
      └─────┬─────┘  └────┬────┘  └─────┬──────┘
            │             │             │
      ┌─────▼─────────────▼─────────────▼──────┐
      │ Folder Resolver  +  Template Engine    │
      │   (Strategy per type via Registry)      │
      └─────────────────┬───────────────────────┘
                        │
                  ┌─────▼──────┐
                  │ Repository │ ← Hides Django ORM. Atomic txn boundary.
                  └─────┬──────┘
                        │
                  ┌─────▼─────────┐
                  │ cortex_entity │ ← One table.
                  └───────────────┘

Async (Celery beat / on-demand):
  ClusteringService.recluster()    nightly HDBSCAN over workspace
  VaultRenderer.render_workspace() Mode A live, Mode B on demand
```

**SOLID applied:**

- **S** — Each subsystem owns one concern; `CortexWriter` only orchestrates.
- **O** — Add a new OCR backend / clustering algo / template type by adding a Strategy + registering it; orchestrator code unchanged.
- **L** — Strategies are interchangeable at the interface level (no leaked impl details).
- **I** — Extractor, Resolver, Fitter, Folder Resolver are separate small interfaces.
- **D** — Orchestrator depends on interfaces (Protocols); Strategies are constructor-injected for testability.

---

## Postgres schema (one table)

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE cortex_entity (
  id              UUID PRIMARY KEY,
  workspace_id    UUID NOT NULL REFERENCES workspaces_workspace(id),
  type            VARCHAR(32) NOT NULL,             -- Literal: meeting|email|message_thread|file|clip|person|org|project|note
  title           VARCHAR(500) NOT NULL,
  occurred_at     TIMESTAMPTZ,
  body_md         TEXT NOT NULL,
  doc_embedding   vector(384),                      -- clustering input
  data            JSONB NOT NULL,                   -- frontmatter; Pydantic-validated
  content_hash    VARCHAR(64) NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (workspace_id, content_hash)
);

CREATE INDEX cortex_entity_data_gin   ON cortex_entity USING GIN (data);
CREATE INDEX cortex_entity_type_time  ON cortex_entity (workspace_id, type, occurred_at DESC);
CREATE INDEX cortex_entity_doc_emb    ON cortex_entity USING ivfflat (doc_embedding vector_cosine_ops);
```

**`data` JSONB shape (Pydantic-validated):**

```python
class EntityData(BaseModel):
    # Navigation
    parent_path: str
    slug: str
    template_version: str
    tags: list[str]
    tldr: str | None

    # Clustering
    cluster_id: str | None
    cluster_name: str | None

    # Provider passthrough
    bronze_storage_key: str | None
    provider_metadata: dict

    # Edges (bidirectional invariant maintained in Repository txn)
    sources: list[UUID]
    applied_in: list[UUID]
    related: list[UUID]

    # Per-type nav fields (Pydantic extension per Literal type)
    # meeting: participants, host, duration_seconds
    # email: sender, recipients, thread_id
    # person: aliases, emails, org_ids
    # org: aliases, domains
```

---

## Subsystem 1 — Document OCR

**Goal:** any Bronze artifact (PDF, image, raw bytes, native API JSON) → uniform markdown the rest of the pipeline can consume.

**Interface:**

```python
class OCRStrategy(Protocol):
    def supports(self, mime_type: str) -> bool: ...
    def extract(self, blob: bytes, mime_type: str, hint: dict | None = None) -> str: ...
```

**Implementations:**

| Strategy | Handles | Notes |
|---|---|---|
| `DoclingStrategy` | `application/pdf`, `image/*` | Default. Local. Tables + structure preserved as markdown. |
| `LLMVisionStrategy` | image fallback when Docling confidence is low | Haiku vision; gated by Docling-confidence threshold |
| `NoOpStrategy` | already-markdown sources (Fathom transcript, Gmail body) | Just returns `adapter.to_markdown()` |

**Selector:** `OCRService` holds an ordered list of Strategies; first `supports(mime)` wins. Connectors call `OCRService.extract(...)` instead of inlining Docling — single boundary.

**SOLID:** Open-Closed (new format = new Strategy registered into selector; OCRService unchanged). DIP (connectors depend on `OCRService` not on Docling).

**File:** `donna/cortex/ocr.py`

---

## Subsystem 2 — Topical Clustering (embedding-driven)

**Goal:** group entities by latent topic, generating an emergent folder taxonomy without hard-coded categories.

**Interfaces:**

```python
class EmbeddingStrategy(Protocol):
    def embed(self, text: str) -> list[float]: ...           # returns 384-dim

class ClusterStrategy(Protocol):
    def assign(self, embedding: list[float], workspace_id: UUID) -> str: ...   # online nearest-centroid
    def recluster(self, workspace_id: UUID) -> dict[UUID, str]: ...            # batch, returns entity_id → cluster_id

class ClusterNamerStrategy(Protocol):
    def name(self, centroid_samples: list[CortexEntity]) -> str: ...
```

**Implementations:**

| Strategy | Default | Alternates |
|---|---|---|
| `EmbeddingStrategy` | `BGESmallEmbedder` (local, 384-dim) | `OpenAIEmbedder` (hosted, 1536-dim — set workspace flag) |
| `ClusterStrategy` | `HDBSCANClusterer` (cosine, `min_cluster_size=5`) | `KMeansClusterer` (fixed-k alternative) |
| `ClusterNamerStrategy` | `HaikuNamer` (5 samples → name via Pydantic structured output) | manual override via admin API |

**Composition:** `ClusteringService` injects all three; runs online assign on write (step 7 of pipeline) and full recluster nightly (Celery beat).

**SOLID:** SRP (embedding vs clustering vs naming are separate). DIP (orchestrator holds interfaces). OCP (swap algorithm without touching writer).

**Files:** `donna/cortex/embeddings.py`, `donna/cortex/clustering.py`

---

## Subsystem 3 — Entity Reference (GLiNER + provider metadata)

**Goal:** every entity that mentions a person / org / project gets a `data.related[]` reference to a typed entity row. Enables "all Acme stuff in one namespace" via derived view.

**Interfaces:**

```python
class EntityExtractor(Protocol):
    def extract(self, entity: CortexEntity, context: ExtractContext) -> list[ExtractedEntity]: ...

@dataclass
class ExtractedEntity:
    type: Literal["person", "org", "project"]
    label: str                # name / display
    email: str | None
    domain: str | None
    confidence: float
    span: tuple[int, int] | None      # for GLiNER body-text matches
    origin: Literal["provider", "gliner", "haiku_hint"]

class EntityResolver(Protocol):
    def resolve(self, candidate: ExtractedEntity, workspace_id: UUID) -> UUID: ...
```

**Implementations:**

| Strategy | Origin of candidates |
|---|---|
| `ProviderMetadataExtractor` | Fathom host/participants; Gmail from/to/cc; Gmail sender-domain → org; Drive owner / shared org |
| `GLiNERExtractor` | body_md NER over template-rendered content; candidate types = `["person", "org", "project"]` |
| `CompositeExtractor` | Chain of Responsibility — runs Provider first (high confidence, free), then GLiNER on gaps; dedupes |
| `DeterministicResolver` | match by lowercased email → fuzzy `(first+last)` → spawn new `person` entity row if no match; org by canonical domain → name fuzzy |

**Resolution rules:**

- person primary key: lowercased email
- person fallback: `(first + last)` against existing `data.aliases[]`
- org primary key: canonical domain
- org fallback: name against existing `data.aliases[]`
- no match → spawn new `cortex_entity` row (`type=person|org`), `bronze_storage_key=NULL`, body_md = `Spawned by: <referencing_entity_id>`
- write `entity_id` into the doc's `data.related[]`
- reverse `data.applied_in[]` on the entity row, in the same txn

**SOLID:** ISP (Extractor and Resolver are separate small interfaces). OCP (add GLiClass classification later as another Extractor without touching pipeline). Chain of Responsibility makes ordering + dedup explicit.

**File:** `donna/cortex/entities.py`

---

## Subsystem 4 — Folder Structure Generation

**Goal:** project Cortex rows into three folder lenses over the same data. One table; three navigation axes.

**Three axes:**

| Axis | Lens | Source of structure |
|---|---|---|
| **Topical** | `01 - Clusters/<cluster_name>/` | HDBSCAN clusters (Subsystem 2) |
| **Entity** | `05 - People & Orgs/<entity_slug>/` | derived: `WHERE data.related @> [entity_uuid]` |
| **Temporal** | `06 - Meetings/{YYYY}/{MM}/` | `occurred_at` per type |

**Interface:**

```python
class FolderResolver(Protocol):
    def canonical_path(self, entity: CortexEntity) -> str: ...      # primary filing
```

Per-type Strategy via Registry:

| Type | Default Resolver | Canonical filing |
|---|---|---|
| `meeting`, `email`, `message_thread` | `TemporalFolderResolver` | date-based |
| `note`, `clip`, `concept` | `ClusterFolderResolver` | cluster-based |
| `person`, `org`, `project` | `EntityTypeFolderResolver` | typed-namespace based |
| `file` | `ClusterFolderResolver` (default) — overridable per workspace | cluster-based |

**Derived views (no canonical filing — query-time projections):**

```python
class DerivedNamespaceView:
    def list_entity_namespace(self, entity_id: UUID, workspace_id: UUID) -> list[CortexEntity]:
        # WHERE data.related @> [entity_id] ORDER BY occurred_at DESC
```

`/cortex/index?path=05 - People & Orgs/acme` runs this query. Same response shape as topical / temporal index endpoints. Agent sees one uniform navigation interface regardless of axis.

**Folder layout (rendered for Mode A vault):**

```
workspace-root/
  _index.yaml              # top-level summary
  _log.yaml                # workspace-wide event feed
  00 - Inbox/              # bronze drops awaiting classify
  01 - Clusters/           # TOPICAL axis
    <cluster-name>/
      _index.yaml
  05 - People & Orgs/      # ENTITY axis (derived)
    <entity-slug>/
      _index.yaml          # derived view query
      <entity-slug>.md     # the person/org entity itself
  06 - Meetings/{YYYY}/{MM}/   # TEMPORAL axis
    _index.yaml
    <date>-<slug>.md
  10 - Messages/{channel}/     # chat threads (post-v1)
```

**SOLID:** OCP (new type → register new FolderResolver). SRP (canonical filing vs derived views are separate concerns).

**File:** `donna/cortex/folders.py`

---

## Subsystem 5 — Template Application

**Goal:** every entity type is rendered through a Jinja template that fits to a strong convention. Predictable shape → fast agent comparison.

**Three aligned contracts per type, versioned together:**

1. **Pydantic frontmatter model** (`EntityData` extension) — locks `data` shape
2. **Jinja template** — locks markdown body shape
3. **Literal taxonomy** — locks closed-vocabulary values (`type`, `tags`, `domain/*`)

**TypeSpec (composed via Factory at registration time):**

```python
@dataclass(frozen=True)
class TypeSpec:
    type: Literal["meeting","email","message_thread","file","clip","note","project","person","org"]
    frontmatter_model: type[BaseModel]      # validates EntityData extension
    fit_model: type[BaseModel] | None       # Haiku fit Pydantic; None = no LLM needed
    template_path: str                      # Jinja2 path
    nav_fields: list[str]                   # linter checks presence
    folder_resolver: FolderResolver         # subsystem-4 plug
    version: str                            # e.g. "meeting@v1"
```

**Registration via decorator:**

```python
@register_type
class MeetingSpec(TypeSpec):
    type = "meeting"
    frontmatter_model = MeetingFrontmatter
    fit_model = MeetingFit
    template_path = "meeting.j2"
    nav_fields = ["participants", "host", "duration_seconds"]
    folder_resolver = TemporalFolderResolver()
    version = "meeting@v1"
```

`TemplateRegistry` discovers `TypeSpec`s on `apps.ready()` — mirrors connector registry pattern in `server/donna/integrations/apps.py`.

**Rendering interface:**

```python
class TemplateEngine:
    def render(self, type_spec: TypeSpec, data: EntityData, body_input: str) -> str: ...

class TemplateFitter(Protocol):                     # optional, only when nav fields missing
    def fit(self, text: str, fit_model: type[BaseModel]) -> BaseModel: ...

class HaikuFitter(TemplateFitter): ...              # default — LiteLLM + Pydantic structured output
class NoOpFitter(TemplateFitter): ...               # for types that never need LLM fill
```

**When the fitter runs:** linter inspects the candidate `data` after deterministic fill from `adapter.metadata()`. If nav_fields are satisfied, `NoOpFitter` is used (Fathom + Gmail land here). If gaps remain, `HaikuFitter` runs with `fit_model` as `response_format`. Pydantic Literal locks closed-vocabulary values.

**Anti-hallucination invariants** (linter-enforced):

| Source | Field | Rule |
|---|---|---|
| `adapter.metadata()` | participants, occurred_at, sender, … | Deterministic Jinja interpolation; LLM forbidden |
| `adapter.to_markdown()` (or OCR output) | body content | Rendered verbatim |
| Haiku fit | optional `tldr`, missing nav fields | Pydantic Literal locks values; additive only |
| Body footer | bronze back-reference | Every body_md ends with `Source: <bronze_storage_key>` (or `Spawned by: <id>` for entity rows) |
| Bidirectional edges | `sources` + reverse `applied_in` | Same Postgres txn; linter rejects partial writes |

**SOLID:** OCP (new type = decorator-register a new TypeSpec; no engine code changes). SRP (registry, engine, fitter, linter are separate). DIP (engine depends on `TemplateFitter` interface).

**Files:**

- `donna/cortex/templates/<type>.py` (one per type)
- `donna/cortex/templates/<type>.j2`
- `donna/cortex/template_engine.py`
- `donna/cortex/registry.py`
- `donna/cortex/linter.py`

---

## Orchestrator — `CortexWriter` (Facade)

Single entry point. Composes all five subsystems via constructor injection. Each step delegates to one service; orchestrator owns no domain logic.

```python
class CortexWriter:
    def __init__(
        self,
        ocr: OCRService,
        embedder: EmbeddingStrategy,
        clusterer: ClusterStrategy,
        extractor: EntityExtractor,        # CompositeExtractor by default
        resolver: EntityResolver,
        registry: TemplateRegistry,
        engine: TemplateEngine,
        fitter: TemplateFitter,            # NoOp if not needed
        linter: FrontmatterLinter,
        repo: CortexEntityRepository,
    ): ...

    def write(self, dp: DeliveryPackage) -> CortexEntity:
        # 1. OCR / markdownify
        body_md = self.ocr.extract(dp.blob_bytes(), dp.mime_type, hint=dp.metadata())

        # 2. Type resolve + TypeSpec lookup
        type_spec = self.registry.get(dp.provider_item_type)

        # 3. Deterministic frontmatter fill from adapter.metadata
        data = build_frontmatter(dp, type_spec)

        # 4. Fit fallback (Haiku) ONLY when linter detects missing nav_fields
        if not self.linter.has_required_nav_fields(data, type_spec):
            fit_result = self.fitter.fit(body_md, type_spec.fit_model)
            data = merge_fit_into_data(data, fit_result)

        # 5. Embed + cluster_assign (online)
        embedding = self.embedder.embed(body_md)
        data.cluster_id, data.cluster_name = self.clusterer.assign(embedding, dp.workspace_id)

        # 6. Folder placement (canonical)
        data.parent_path = type_spec.folder_resolver.canonical_path_for(data, dp.workspace_id)
        data.slug = build_slug(data, content_hash(body_md))

        # 7. Render body
        body_md_final = self.engine.render(type_spec, data, body_md)

        # 8. Build the entity (without persisting yet)
        new_entity = CortexEntity(
            workspace_id=dp.workspace_id, type=type_spec.type,
            title=data.title, occurred_at=data.occurred_at,
            body_md=body_md_final, doc_embedding=embedding,
            data=data, content_hash=content_hash(body_md),
        )

        # 9. Entity extraction + resolution → data.related[] + reverse data.applied_in[]
        candidates = self.extractor.extract(new_entity, ExtractContext(adapter_metadata=dp.metadata()))
        for candidate in candidates:
            target_id = self.resolver.resolve(candidate, dp.workspace_id)        # matches or spawns
            new_entity.data.related.append(target_id)
            # reverse applied_in handled atomically by repository

        # 10. Linter gate
        self.linter.check(new_entity, type_spec)

        # 11. Persist atomically (writer + spawned entities + reverse edges)
        return self.repo.save_with_reverse_edges(new_entity)
```

**SOLID:** SRP (orchestration only — every domain decision delegated). DIP (all collaborators are interfaces). Facade pattern hides the subsystems behind one method.

**File:** `donna/cortex/pipeline.py`

---

## Repository (data access)

Hides Django ORM. One atomic save that maintains the bidirectional edge invariant.

```python
class CortexEntityRepository:
    def save_with_reverse_edges(self, entity: CortexEntity) -> CortexEntity:
        """In one Postgres transaction:
           - INSERT entity row
           - For each id in entity.data.related: APPEND entity.id to that target.data.applied_in
        """

    def find_by_id(self, id: UUID) -> CortexEntity | None: ...
    def find_by_path(self, workspace_id: UUID, parent_path: str) -> list[CortexEntity]: ...
    def find_referencing(self, target_id: UUID, workspace_id: UUID) -> list[CortexEntity]: ...
    # ↑ derived namespace query (Subsystem 4)
```

**SOLID:** DIP (services never touch ORM directly). Repository pattern keeps DB concerns out of domain code.

**File:** `donna/cortex/repository.py`

---

## Route-matrix API (read side)

Three endpoints. Same shape for all three axes; agents see uniform navigation.

```
GET /cortex/index?path=<path>
    → topical: WHERE parent_path = path
    → entity:  WHERE data.related @> [entity_uuid]   (path = "05 - People & Orgs/<slug>")
    → temporal: WHERE parent_path = path

    response: {
      path, parent,
      recent_activity: { last_24h, last_7d },
      cluster_summary: { cluster_id, cluster_name, member_count } | null,
      children: [ {id, type, title, occurred_at, cluster_name, tags, tldr, ...nav_fields} ]
    }

GET /cortex/log?path=<path>&since=<iso>
    → { events: [{ts, action, entity_id, type, title}], summary: {total, by_type} }

GET /cortex/entity/{id}
    → { data, body_md, created_at, updated_at }
```

Path resolver classifies the path prefix to pick the right query; response shape is invariant.

**File:** `donna/cortex/api/v1/views.py`

---

## Vault projection (optional, Mode A)

`VaultRenderer` is a Celery task that walks `cortex_entity` rows and writes the rendered folder tree to disk. Strategies for each output kind:

- `IndexFileRenderer` → `_index.yaml`
- `LogFileRenderer` → `_log.yaml`
- `EntityFileRenderer` → `<slug>.md`
- `VaultIORepository` (Strategy: `LocalGitVaultIO`, future `S3VaultIO`) handles writes + commits

Per-workspace flag `vault_render_mode = off | live | on_demand`. Mode A enterprise sets `live` — vault repo populates and commits on every Cortex write. Mode B SaaS leaves it `on_demand` — only runs when the user triggers "export workspace."

**File:** `donna/cortex/vault_renderer.py`

---

## Files

**New (server)**

```
server/donna/cortex/                                # new Django app
  __init__.py
  apps.py                                           # ready() → discover @register_type
  models.py                                         # CortexEntity
  pipeline.py                                       # CortexWriter (Facade orchestrator)
  ocr.py                                            # Subsystem 1
  embeddings.py                                     # Subsystem 2 — embed
  clustering.py                                     # Subsystem 2 — cluster + name
  entities.py                                       # Subsystem 3 — extract + resolve
  folders.py                                        # Subsystem 4 — canonical + derived
  template_engine.py                                # Subsystem 5 — render
  registry.py                                       # TypeSpec registry
  linter.py                                         # nav-field + edge invariants
  repository.py                                     # CortexEntityRepository
  vault_renderer.py                                 # Celery task; Mode A projection
  api/v1/
    __init__.py
    views.py                                        # IndexView, LogView, EntityView
    serializers.py
  urls.py
  templates/
    {meeting,email,message_thread,file,clip,note,project,person,org}.py
    {meeting,email,message_thread,file,clip,note,project,person,org}.j2
    _partials/{index_block.yaml.j2, log_line.yaml.j2, source_footer.md.j2}
  tests/
  migrations/0001_initial.py
```

**New planning docs**

```
server/plans/11-cortex-substrate.md          # schema, repository invariant, API
server/plans/12-cortex-subsystems.md         # the five Strategy interfaces + default impls
server/plans/13-cortex-templates.md          # TypeSpec, Jinja conventions, anti-hallucination rules
```

**Modified (hookup)**

```
server/donna/integrations/connectors/fathom/tasks.py            # append CortexWriter().write(dp)
server/donna/integrations/connectors/google/mail/tasks.py       # same
server/donna/integrations/connectors/google/drive/tasks.py      # same
server/donna/integrations/connectors/google/drive/adapter.py    # call OCRService for non-text mime types
server/donna/settings.py                                        # INSTALLED_APPS += 'donna.cortex'; beat schedule
server/donna/urls.py                                            # mount cortex/api/v1
server/donna/workspaces/models.py                               # add vault_render_mode field
server/pyproject.toml                                           # docling, gliner, hdbscan, sentence-transformers, pgvector, jinja2, litellm
```

---

## Patterns to reuse (existing codebase)

| Pattern | Existing example | Reused in |
|---|---|---|
| Django app layout convention | `server/plans/03-conventions-and-api.md` | All of `donna/cortex/` |
| `BaseService` | `server/donna/core/services.py` | Each subsystem service |
| `ServiceMethodMixin` auto-discovery | `server/donna/core/mixins.py` | Cortex API ViewSets |
| `@register` decorator + `apps.ready()` discovery | `server/donna/integrations/apps.py` + `donna/core/integrations/registry.py` | `donna/cortex/registry.py` |
| `workspace_id` FK + `WorkspaceMiddleware` | `server/donna/workspaces/middlewares.py` | `cortex_entity.workspace_id` |
| `TimestampsMixin` | `server/donna/core/models.py` | `CortexEntity` |
| `StandardJSONRenderer` `{data, meta, message, code}` | `server/donna/core/renderers.py` | All Cortex API responses |
| `BaseAdapter` `to_text/to_markdown/metadata` | `server/donna/core/integrations/adapter.py` | OCR input + pipeline step 1 |
| `DeliveryPackage` as bronze handle | `server/donna/integrations/models.py` | `CortexWriter.write` entry point |
| Celery `@shared_task` + per-connector `tasks.py` | `server/donna/integrations/connectors/*/tasks.py` | Hookup + nightly recluster + vault render |
| `configure_logging()` + structlog | `server/donna/core/logging.py` | Pipeline trace (replaces explicit `cortex_log` table) |

---

## Implementation phases

| Phase | Subsystem | Deliverable | Verification |
|---|---|---|---|
| **P1** | foundation | App skeleton + `cortex_entity` migration + `CortexEntityRepository` + Pydantic `EntityData` + linter | Django shell: insert + select; linter rejects bad data |
| **P2** | 1 OCR | `OCRService` + `DoclingStrategy` + `NoOpStrategy` + selector | Drive PDF → markdown roundtrip; Fathom transcript → noop |
| **P3** | 5 Template | `TemplateRegistry` + `MeetingSpec` + `meeting.j2` + `TemplateEngine` + `NoOpFitter` | Render a Fathom DeliveryPackage to markdown with valid frontmatter |
| **P4** | 2 Embed+Cluster | `BGESmallEmbedder` + `HDBSCANClusterer` + online assign + nightly recluster + `HaikuNamer` | Seed 30 entities across 3 topics; HDBSCAN finds clusters; cluster_name plausible |
| **P5** | 3 Entity | `ProviderMetadataExtractor` + `GLiNERExtractor` + `CompositeExtractor` + `DeterministicResolver` + bidirectional edge writes | Two Fathom meetings sharing a participant + a transcript naming "Acme" → ONE person row + ONE org row; `applied_in[]` populated on both |
| **P6** | 4 Folders | `TemporalFolderResolver` + `ClusterFolderResolver` + `EntityTypeFolderResolver` + `DerivedNamespaceView` | `data.parent_path` set canonically; entity-axis query returns Acme content across clusters |
| **P7** | orchestrator | `CortexWriter` facade; hook into Fathom/Gmail/Drive tasks | End-to-end Fathom ingest → cortex_entity persisted with full nav frontmatter |
| **P8** | remaining types | `email`, `message_thread`, `file`, `clip`, `note`, `project`, `person`, `org` TypeSpecs + Jinja | Each connector type ingests and renders correctly |
| **P9** | API | `/cortex/index`, `/cortex/log`, `/cortex/entity/{id}` (all three axes) | DRF schema; smoke tests for topical / entity / temporal paths |
| **P10** | vault | `VaultRenderer` + `LocalGitVaultIO` + `vault_render_mode` workspace flag | Toggle a workspace to `live`; vault directory populates with `_index.yaml`/`_log.yaml`/`.md` + git log shows commits |

P1–P7 = engine working end-to-end on one type (meeting). P8 = production data flowing for all types. P9 = agent-facing API ready. P10 = Mode A vault.

---

## Verification

### Unit (per subsystem)

- **OCR:** `DoclingStrategy` handles a fixture PDF → markdown with tables preserved; selector picks `NoOpStrategy` for `text/markdown`.
- **Embed/Cluster:** `BGESmallEmbedder` produces 384-dim vectors; `HDBSCANClusterer` returns stable cluster ids over a fixed seed dataset.
- **Entity:** `CompositeExtractor` dedupes when Provider + GLiNER both emit the same email; `DeterministicResolver` matches by lowercased email primary, fuzzy fallback.
- **Folders:** `TemporalFolderResolver` for a meeting on 2026-05-28 → `06 - Meetings/2026/05`; `EntityTypeFolderResolver` for an org → `05 - People & Orgs/<slug>`.
- **Templates:** Pydantic frontmatter rejects off-Literal `tags`; `linter.check_bidirectional()` fails when `sources` written without reverse `applied_in`; `slug` stable across re-renders for same `content_hash`.

### Integration

- `CortexWriter().write(dp)` against a Fathom meeting fixture → one row, validates, body_md verbatim with `Source:` footer, `doc_embedding` non-null, `data.cluster_id` set.
- Two meetings sharing host email → assert ONE `person` entity, both meetings reference it, person `applied_in[]` lists both — all in one Postgres txn (savepoint rollback drops all three writes).
- Fathom meeting whose transcript mentions "OpenAI" + "Stripe" → `GLiNERExtractor` surfaces both; new `org` entities spawned; `data.related[]` includes both.

### End-to-end

```
1. docker compose up --build                                       # server/
2. docker compose run --rm web shell
3. trigger Fathom ingest task on a known recording_id
4. assert DeliveryPackage row exists                              (bronze)
5. assert cortex_entity row exists                                (cortex)
   - type='meeting', data.participants populated
   - data.cluster_id + data.cluster_name set
   - data.parent_path matches "06 - Meetings/{YYYY}/{MM}"
   - doc_embedding is 384-dim
6. ingest 3 entities referencing same org (Fathom + Gmail + Drive involving someone@acme.com):
   - assert ONE cortex_entity of type='org', slug='acme' exists (spawned)
   - assert acme.data.applied_in[] lists all 3 referencing entity ids
7. GET /cortex/index?path=06%20-%20Meetings/2026/05    # temporal axis
   - children includes the meeting
8. GET /cortex/index?path=05%20-%20People%20%26%20Orgs/acme   # entity axis
   - children includes all 3 referencing entities
   - each child's data.cluster_name may differ (Sales / Legal / Onboarding) — they unite ONLY in this entity axis
9. GET /cortex/entity/{id}
   - returns body_md verbatim + Source footer
10. set workspace.vault_render_mode='live'; trigger vault_renderer
11. inspect vault dir:
    - 06 - Meetings/2026/05/{slug}.md exists
    - 05 - People & Orgs/acme/{_index.yaml, _log.yaml, acme.md} exist
    - 01 - Clusters/<cluster_name>/_index.yaml lists the meeting
    - git log shows a commit per write batch
```

### Negative checks (must NOT appear)

- No `cortex_chunk` table.
- No `cortex_edge` table.
- No `cortex_log` table.
- No FalkorDB calls.
- No agent orchestrator code (separate plan).
- No per-doc Haiku call when Fathom/Gmail metadata satisfies nav_fields.
- No connector code that imports Docling directly (must go through `OCRService`).

---

## Open knobs

1. **LLM provider for `HaikuNamer` + `HaikuFitter`** — LiteLLM (default; matches vault doc reference to `docupal.core.llm`) vs direct `anthropic` SDK. Decide in P4.
2. **Embedding model** — `BAAI/bge-small-en-v1.5` (local, 384-dim) default; `text-embedding-3-small` (hosted, 1536-dim) as alt Strategy registered behind a workspace flag.
3. **HDBSCAN params** — start `min_cluster_size=5`, `metric='cosine'`; revisit per workspace size.
4. **Cluster rename cadence** — nightly + on-demand admin trigger.
5. **Folder-name collision policy** — dedupe by cluster_id suffix; admin override via API.
6. **GLiNER label set** — start with `["person", "org", "project"]`; extend per workspace via Strategy config.
7. **Vault git repo physical layout (Mode A enterprise)** — one repo per workspace under `${VAULT_ROOT}/<workspace_slug>/`. Engine writes via `VaultIORepository` Strategy so layout is swappable.
8. **Template version bumps** — when `TypeSpec.version` changes, background re-render job; advisory lock per entity prevents race with concurrent writes.
