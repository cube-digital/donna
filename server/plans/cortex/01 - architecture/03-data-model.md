# Data Model

The Cortex layer has **one** Postgres table: `cortex_entities`. Twelve
closed types live in it. Same row shape regardless of type — what
differs is the `extensions` JSONB blob (Pydantic-validated per-type).

The **rendered markdown body lives in SilverStorage** (S3 / filesystem /
GCS / Azure — driven by `STORAGES["default"]`) via a Django
`FileField`, not in a Postgres TEXT column. Postgres is a derived
index per spec §14. See
[`P0.14`](../06%20-%20status/04-p0.14-storage-and-embedding-refactor.md)
for the storage refactor and
[`P0.15`](../06%20-%20status/05-deferred-document-chunking.md) for the
deferred chunk-table plan.

## Why one table

| Alternative | Why we rejected it |
|---|---|
| One table per type (meetings, emails, …) | Twelve tables = twelve query plans. Joins across types become painful. JSONB on one row is far easier. |
| Documents + chunks split | Chunk embeddings are overkill — the agent navigates `_index.md` + `_log.md` instead. One row per artifact suffices. |
| Sub-typed inheritance (Django MTI) | Hidden JOIN per query. Schema migration churn when adding a type. |
| EAV pattern | Lossy types, slow queries, no FK constraints. |

One row per artifact. Spec §3 + §14.

## Top-level columns

```sql
CREATE TABLE cortex_entities (
    -- Identity
    id              UUID PRIMARY KEY,
    type            VARCHAR(16) NOT NULL,    -- 12-value Literal

    -- Authorship & provenance (anti-hallucination)
    author          VARCHAR(8)  NOT NULL,    -- donna | human | agent
    source          VARCHAR(512) NOT NULL,    -- URI: fathom://meeting/<id>
    bronze_storage_key VARCHAR(500),          -- pointer to default_storage
    content_hash    VARCHAR(64) NOT NULL,    -- sha256(body_md)

    -- Temporal
    occurred_at     TIMESTAMPTZ NOT NULL,    -- when the event happened
    created_at      TIMESTAMPTZ NOT NULL,    -- synthesized_at (TimestampsMixin)
    updated_at      TIMESTAMPTZ NOT NULL,

    -- Scope boundary (spec §6)
    workspace_id    UUID NOT NULL REFERENCES workspaces(id),
    client_id       UUID,                    -- NULL = workspace-owner content
    project_id      UUID,                    -- NULL only if client_id is NULL

    -- Topical (clustering)
    cluster_id      UUID,
    doc_embedding   vector(384),             -- pgvector

    -- Edges — forward (6)
    entity_refs     JSONB NOT NULL DEFAULT '[]'::jsonb,
    sources         JSONB NOT NULL DEFAULT '[]'::jsonb,
    cross_refs      JSONB NOT NULL DEFAULT '[]'::jsonb,
    supersedes      JSONB NOT NULL DEFAULT '[]'::jsonb,
    parent          UUID,
    related         JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Edges — reverse (3, auto-maintained)
    applied_in      JSONB NOT NULL DEFAULT '[]'::jsonb,
    superseded_by   UUID,
    contradicts     JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Confidence & decay
    confidence      VARCHAR(8) NOT NULL DEFAULT 'high',
    last_synthesized DATE,

    -- Content
    title           VARCHAR(500) NOT NULL,
    body_md         TEXT NOT NULL,

    -- Per-type extensions (Pydantic-validated)
    extensions      JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Idempotency
    CONSTRAINT uq_cortex_entity_ws_hash UNIQUE (workspace_id, content_hash)
);

-- The rendered body markdown does NOT live in this table. It lives in
-- SilverStorage (S3 / filesystem) referenced by a Django FileField
-- column `body` (max_length=500). `body_byte_size` is a cheap stat
-- column for byte counts without opening the file.

ALTER TABLE cortex_entities ADD COLUMN body            VARCHAR(500) NOT NULL;  -- FileField path
ALTER TABLE cortex_entities ADD COLUMN body_byte_size  INTEGER      NOT NULL DEFAULT 0;
```

## Indexes

```sql
-- B-tree for type + time queries
CREATE INDEX cortex_entity_type_time
  ON cortex_entities (workspace_id, type, occurred_at DESC);

-- B-tree for scope tri-key
CREATE INDEX cortex_entity_scope
  ON cortex_entities (workspace_id, client_id, project_id);

-- GIN for entity_refs containment (entity-axis derived view)
CREATE INDEX cortex_entity_entity_refs_gin
  ON cortex_entities USING GIN (entity_refs);

-- GIN for extensions JSONB queries
CREATE INDEX cortex_entity_extensions_gin
  ON cortex_entities USING GIN (extensions);

-- IVFFLAT for ANN vector lookup
CREATE INDEX cortex_entity_doc_emb_ivf
  ON cortex_entities
  USING ivfflat (doc_embedding vector_cosine_ops)
  WITH (lists = 100);

-- Parent / superseded_by (cheap pointer queries)
CREATE INDEX ON cortex_entities (parent);
CREATE INDEX ON cortex_entities (superseded_by);
CREATE INDEX ON cortex_entities (cluster_id);
```

Five distinct access patterns, five distinct indexes. No wasted scan.

## The twelve types

| Type | Origin | Volume | Authority | Sub-discriminator |
|---|---|---|---|---|
| `meeting` | accrued | high | medium | — |
| `email` | accrued | high | medium | — |
| `chat` | accrued | very high | low | — |
| `doc` | accrued | medium | high | `doc_type` (16 values) |
| `ticket` | accrued | medium | medium | `provider` (5 values) |
| `clip` | accrued | low | low | — |
| `note` | accrued or human | low | varies | `note_type` (5 values) |
| `person` | curated | low | high | — |
| `org` | curated | low | high | `relationship` (6 values) |
| `project` | curated | low | very high | `status` (4 values) |
| `concept` | curated | very low | very high | `maturity` (3 values) |
| `decision` | curated | very low | highest | `adr_status` (3 values) |

See `donna/cortex/schemas.py` for the `Literal` definitions.

## Sub-discriminators (closed vocabularies)

These narrow a type to a precise shape and unlock the `TYPE_AUTHORITY`
registry. Adding a new value requires a spec amendment.

### `doc_type` (16 values)

```
offer · requirements · spec · contract · handover · technical_analysis
internal_memo · presentation · signed_document · runbook · plan
integration_spec · checkpoint · architecture_note · design_note · other
```

### `note_type` (5 values)

```
brainstorm · checkpoint · journal · action_item · open_question
```

### `org.relationship` (6 values)

```
client · vendor · partner · competitor · internal · self
```

Exactly **one** `org` per workspace carries `relationship: "self"` —
the workspace owner.

### `project.status` (4)

```
proposed · active · shipped · archived
```

### `concept.maturity` (3)

```
seed · growing · evergreen
```

### `decision.adr_status` (3)

```
proposed · accepted · superseded
```

### `ticket.provider` (5)

```
jira · linear · github · asana · clickup
```

## Per-type extensions — concrete shapes

Each type has a Pydantic model whose serialised form lives in
`extensions`. Examples:

### `meeting`

```python
{
    "attendees": [{"name": "Alice", "email": "alice@acme.com", "role": "host"}, ...],
    "duration_min": 30,
    "recording_url": "https://fathom.../r/abc",
    "parent_path": "clients/acme/projects/onboarding/meetings/2026/06",
    "slug": "2026-06-03-cortex-kickoff-a4b2c8e1",
    "cluster_name": "Customer Onboarding",
}
```

### `doc`

```python
{
    "doc_type": "plan",            # REQUIRED — hard reject MISSING_REQUIRED_EXTENSION
    "mime": "application/pdf",
    "author_email": "alice@acme.com",
    ...nav + parent_path + slug...
}
```

### `org`

```python
{
    "relationship": "client",      # one of 6 closed values
    "legal_name": "Acme Inc",
    "email_domains": ["acme.com", "acme.io"],
    "industry": "FinTech",
    ...
}
```

### `decision` (ADR)

```python
{
    "adr_status": "accepted",
    "deciders": ["<person-uuid-1>", "<person-uuid-2>"],
    "context_sources": ["<doc-uuid>", "<meeting-uuid>"],  # REQUIRED
    "supersedes_adr": null,
    ...
}
```

Each shape is locked by `donna/cortex/schemas.py` — the linter runs
`Pydantic.model_validate(extensions)` before persisting.

## Provenance — what every row carries

| Field | Example | Why |
|---|---|---|
| `author` | `"donna"` / `"human"` / `"agent"` | who wrote this row |
| `source` | `"fathom://meeting/rec-abc"` | URI back to the producing system |
| `bronze_storage_key` | `"ws/fathom/meetings/abc.json"` | pointer to raw blob |
| `content_hash` | `"sha256:a4b2…"` | idempotency key |
| `confidence` | `"high"` / `"medium"` / `"low"` | decays per R8 |
| `last_synthesized` | `2026-06-03` | drives R6 resynth + R8 decay |

Any row whose body footer doesn't end with `Source: <uri>` (or
`Spawned by: <id>` for resolver-spawned rows) is rejected at the
linter gate.

## Scope (the boundary contract)

```
workspace_id
 └── client_id            (boundary 1 — clusters NEVER traverse)
      └── project_id      (boundary 2 — null only if client_id is null)
           └── cluster_id (HDBSCAN scoped here)
                └── CortexEntity (1..N)
```

Four valid scope combinations:

| Scope | `client_id` | `project_id` | Example path |
|---|---|---|---|
| Workspace root | `null` | `null` | `meetings/2026/06/...` |
| Workspace project | `null` | `<X>` | `projects/donna-dogfood/meetings/...` |
| Client root | `<X>` | `null` | `clients/teach-for-romania/org.md` |
| Client project | `<X>` | `<Y>` | `clients/teach-for-romania/projects/tfr-mvp/meetings/...` |

Detail: [`04-scope-boundary.md`](./04-scope-boundary.md)

## Why columns vs JSONB

| Field | Storage choice | Why |
|---|---|---|
| `type, author, source, confidence` | column | small, common, indexed |
| `cluster_id, parent, superseded_by` | column | scalar UUIDs, often joined |
| `entity_refs, sources, applied_in, …` | JSONB | variable-length arrays of UUIDs; GIN containment lookups |
| `attendees, doc_type, status, …` | inside `extensions` JSONB | type-specific shapes; Pydantic validates |

The split is: **anything queried directly is a column; anything
type-specific is inside `extensions`**.

## Postgres is dispensable

Per spec §14, this whole table is **derived**. The truth lives in
files inside `SilverStorage` (GitHub repo, S3 bucket, or local
filesystem). You can drop `cortex_entities` and rebuild by walking the
storage backend; <10k entities → minutes, <1M → hours.

Detail: [`05-storage-postgres-derived.md`](./05-storage-postgres-derived.md)
