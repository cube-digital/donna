# Vision

## What Cortex is

The Cortex layer turns a workspace's raw, heterogeneous inputs (meeting
transcripts, emails, files, chat threads, web clips, tickets) into a
**single, queryable, cluster-organised body of structured entities**
that downstream agents can navigate without hallucinating.

It is the substrate the chat application reads when an agent answers
*"What did we ship for Acme last quarter?"* or *"Who's blocking the
TFR project?"*.

## What problem it solves

Today's status quo: raw artifacts pile up across providers (Gmail,
Drive, Slack, Linear, Fathom…). Each provider has its own URL scheme,
shape, and metadata. Agents either:

- crawl each provider live (slow, rate-limited, no joins across sources)
- dump everything into a vector store (lossy, no structure, no edges)
- maintain hand-tuned indexes per workspace (expensive, brittle)

Cortex picks a different path:

1. **Normalise** every source into one Pydantic schema (`SilverEntity`).
2. **Cluster** related entities by latent topic so navigation is
   emergent, not hand-curated.
3. **Cross-reference** every entity to typed person / org / project /
   concept / decision rows so agents can answer "what about Acme?"
   without scanning the universe.
4. **Lock the schema** behind a closed-vocabulary linter so the data is
   trustworthy without per-source code.

## The three layers

```
┌────────────────────────────────────────────────────────────────────┐
│  BRONZE — raw provider artifacts                                   │
│  ───────────────────────────────                                   │
│  Fathom transcripts (JSON), Gmail threads (JSON), Drive files      │
│  (PDF / DOCX / images), Slack threads, Linear tickets…             │
│  • One DeliveryPackage row per item + blob in default_storage      │
│  • Idempotent via (workspace, provider, provider_item_id)          │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼ CortexWriter
┌────────────────────────────────────────────────────────────────────┐
│  CORTEX (Silver) — structured, queryable entities                  │
│  ─────────────────────────────────────────────                     │
│  ONE table: cortex_entities                                        │
│  12 closed types · 9 edge fields · 384-dim embedding · JSONB        │
│  extensions                                                        │
│  • Files in SilverStorage = canonical (GitHub / S3 / LocalFS)      │
│  • Postgres = derived index (rebuildable)                          │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼ (future)
┌────────────────────────────────────────────────────────────────────┐
│  GRAPH (Gold) — temporal knowledge graph                           │
│  ──────────────────────────────────────                            │
│  Out of scope for this docs set. Reserved name: graphiti +         │
│  FalkorDB for bi-temporal reasoning. Stage 3.                      │
└────────────────────────────────────────────────────────────────────┘
```

## Glossary

| Term | Meaning |
|---|---|
| **Bronze** | The raw, unprocessed layer. `DeliveryPackage` row + blob in `default_storage`. |
| **Silver / Cortex** | The structured layer. `CortexEntity` row. Used interchangeably — *Silver* is the spec name, *Cortex* the Django app name. |
| **Gold / Graph** | The future temporal-graph layer. Not built yet. |
| **Entity** | A single Silver row. 12 types: meeting, email, chat, doc, ticket, clip, note, person, org, project, concept, decision. |
| **Accrued type** | Connector-written entity (meeting / email / chat / doc / ticket / clip / note). High volume, lower authority. |
| **Curated type** | Human or agent-authored entity (person / org / project / concept / decision). Low volume, higher authority. |
| **Edge** | A relationship between two entities. 9 types: `entity_refs`, `sources`, `cross_refs`, `supersedes`, `parent`, `related`, `applied_in`, `superseded_by`, `contradicts`. |
| **Reverse edge** | Auto-maintained edge written on the target by the repository in the same transaction. Three pairs total. |
| **Scope** | The boundary tuple `(workspace_id, client_id, project_id)`. Clusters never traverse scope. |
| **Cluster** | A group of entities with similar embeddings inside one scope. HDBSCAN-emergent; no hand-curated taxonomy. |
| **TypeSpec** | The four-aligned contract per type: Pydantic frontmatter model + Jinja template + nav fields + folder resolver. |
| **Linter** | Pre-persistence gate enforcing R1-R10 + hard rejects. Closed-vocab `RejectCode` per failure. |
| **TYPE_AUTHORITY** | Numeric registry (30 keys) used for conflict resolution. |
| **CortexWriter** | The facade that orchestrates the 11-step pipeline from `DeliveryPackage` → `CortexEntity`. |
| **SilverStorage** | Protocol with 3 implementations (`GitHubStorage`, `S3Storage`, `LocalFSStorage`). Files are canonical; Postgres is derived. |
| **MCP API** | The 8-method surface (`cortex.create_entity`, …) downstream agents call. Same across all storage backends. |

## Design principles (the "why" of the choices)

1. **One table for everything.** Twelve types share `cortex_entities`.
   Same schema for the meeting and the person it mentions. Same atomic
   query plan.
2. **Closed vocabularies for safety.** Type, edge, doc_type, note_type
   are all `Literal` — Pydantic rejects ad-hoc values at write time.
3. **Provenance is mandatory.** Every row carries `author`, `source`
   URI, `bronze_storage_key`, `content_hash`, `confidence`. No row
   without a backing trail.
4. **Postgres is dispensable.** Files in `SilverStorage` are the truth.
   `DROP TABLE cortex_entities` + rebuild = a few hours; nothing is lost.
5. **Atomic edge invariants.** Bidirectional edges are written in one
   txn so the graph never half-writes.
6. **Scope boundary is sacred.** Clusters NEVER cross client/project
   lines. Acme content doesn't leak into Stripe clusters.
7. **Anti-hallucination by construction.** Body markdown is verbatim
   source content. LLM only fills nav fields that providers can't.
   Pydantic locks vocabularies.
8. **SOLID at the seams.** Five subsystems behind Strategy/Registry
   interfaces; the orchestrator depends on protocols, not concrete
   classes. New OCR backend / clustering algo / template type = add a
   Strategy + register it; orchestrator unchanged.

## Layers of abstraction

```
        CortexWriter facade
              │
   ┌──────────┼──────────┬──────────┬──────────┐
   ▼          ▼          ▼          ▼          ▼
  OCR     Embed +    Entity    Folder    Template
        Cluster   Extract +  Resolver   Engine
                 Resolve
              │
              ▼
       Linter gate
              │
              ▼
       Repository (atomic txn)
              │
              ▼
       cortex_entities  (Postgres = derived index)
              │
              ▼
       SilverStorage   (Files = canonical store)
```

Detailed in [`01 - architecture/`](./01%20-%20architecture/).
