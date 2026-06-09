# Example 3 — ADR Supersession Chain

Scenario: you wrote an ADR in May. In June you realised it's wrong and
wrote a new one. Cortex tracks the supersession chain explicitly —
no deletes, no silent rewrites.

## The first ADR (May)

```python
CortexEntity(
    id                 = adr_w001_uuid,
    workspace_id       = ws-qube,
    type               = "decision",
    author             = "human",
    source             = "manual://adr/W001",
    bronze_storage_key = "",
    content_hash       = sha256(...body_md_v1...),
    occurred_at        = 2026-05-01T10:00:00Z,
    title              = "ADR-W001 — Use Postgres only for Cortex layer",
    body_md            = <body_v1>,
    confidence         = "high",
    last_synthesized   = 2026-05-01,
    extensions = {
        "adr_status":      "accepted",
        "deciders":        [alice_uuid, bob_uuid],
        "context_sources": [meeting_kickoff_uuid, technical_analysis_uuid],
        "parent_path":     "decisions",
        "slug":            "ADR-W001-use-postgres-only",
    },
)
```

Body:

```markdown
---
type: decision
title: ADR-W001 — Use Postgres only for Cortex layer
adr_status: accepted
deciders: ["alice_uuid", "bob_uuid"]
context_sources: ["meeting_kickoff_uuid", "technical_analysis_uuid"]
---

# ADR-W001 — Use Postgres only for Cortex layer

## Context
We need a fast storage layer for Cortex entities.

## Decision
Use Postgres exclusively. No pgvector, no FalkorDB, no S3.

## Consequences
- Single source of truth
- Operationally simple
- BUT: clustering / similarity search not feasible at scale

Source: manual://adr/W001
```

## A month passes — new evidence

In June someone realises clustering is critical and pgvector is the
right tool. New ADR drafted:

```python
CortexEntity(
    id                 = adr_w002_uuid,
    workspace_id       = ws-qube,
    type               = "decision",
    author             = "human",
    source             = "manual://adr/W002",
    content_hash       = sha256(...body_md_v2...),
    occurred_at        = 2026-06-03T15:30:00Z,
    title              = "ADR-W002 — Postgres + pgvector for Cortex layer",
    body_md            = <body_v2>,
    extensions = {
        "adr_status":      "accepted",
        "deciders":        [alice_uuid, bob_uuid],
        "context_sources": [
            adr_w001_uuid,                 # reference the previous
            embedding_research_uuid,
        ],
        "supersedes_adr":  adr_w001_uuid,   # spec §3.2 explicit
        "parent_path":     "decisions",
        "slug":            "ADR-W002-postgres-plus-pgvector",
    },

    # The key edge:
    supersedes = [adr_w001_uuid],
)
```

Body:

```markdown
---
type: decision
title: ADR-W002 — Postgres + pgvector for Cortex layer
adr_status: accepted
supersedes_adr: "adr_w001_uuid"
context_sources: ["adr_w001_uuid", "embedding_research_uuid"]
---

# ADR-W002 — Postgres + pgvector for Cortex layer

## Context
ADR-W001 ruled out pgvector. New evidence (embedding research)
shows ANN search via IVFFLAT is performant and operationally simple.

## Decision
Use Postgres + pgvector (IVFFLAT cosine) for Cortex layer.

## Consequences
- Cluster + similarity search now in scope
- One Docker image change (postgres:17 → pgvector/pgvector:pg17)
- Existing volume data compatible

This supersedes ADR-W001.

Source: manual://adr/W002
```

## What happens in the repository

`CortexWriter.write(<ADR-W002 DeliveryPackage-equivalent>)` reaches
step 11:

```python
self.repo.save_with_reverse_edges(new_entity)
```

Inside the repository:

```python
def save_with_reverse_edges(self, entity):
    supersedes = [adr_w001_uuid]
    contradicts = []
    sources = []

    with transaction.atomic():
        entity.save()                              # INSERT ADR-W002

        for target_id in supersedes:
            self._assign_superseded_by(target_id, entity.id)
            # → UPDATE ADR-W001 SET superseded_by = ADR-W002.id
```

After the transaction:

```sql
SELECT id, title, supersedes, superseded_by FROM cortex_entities
WHERE type = 'decision' ORDER BY occurred_at;
```

| id | title | supersedes | superseded_by |
|---|---|---|---|
| adr_w001_uuid | ADR-W001 — Use Postgres only | [] | adr_w002_uuid |
| adr_w002_uuid | ADR-W002 — Postgres + pgvector | [adr_w001_uuid] | None |

## What the agent sees when reading ADR-W001

```python
adr = repo.find_by_id(adr_w001_uuid)
print(adr.superseded_by)   # → adr_w002_uuid
```

The agent now knows: "this ADR is stale, follow superseded_by to find
the current decision". No hidden deprecation; no silent rewrite.

## The chain extends

If a third ADR comes later:

```python
ADR-W003 supersedes ADR-W002.
```

| id | supersedes | superseded_by |
|---|---|---|
| ADR-W001 | [] | ADR-W002 |
| ADR-W002 | [ADR-W001] | ADR-W003 |
| ADR-W003 | [ADR-W002] | None |

Three rows, all preserved. The chain is walkable in both directions:

- "Latest decision on this topic?" → walk `superseded_by` until None
- "What did we think before?" → walk `supersedes` backwards

## Why no delete

Spec §7 R3: explicit supersession, no deletion.

| Reason | Why deletion would break |
|---|---|
| Audit trail | Compliance / governance needs the history |
| `applied_in` integrity | Other rows cite ADR-W001 — deleting orphans references |
| Learning | "What did we change our mind about?" requires the trail |
| Time-travel queries | "What decision applied on 2026-05-15?" needs the row |

Deletion is via `cortex.delete_entity(id)` (MCP API, P9) — rare, only
for legal redaction. Default = explicit supersession chain.

## `context_sources` vs `supersedes`

These are **different** semantics:

| Edge | Meaning | Example |
|---|---|---|
| `supersedes` | "I replace this" | ADR-W002 supersedes ADR-W001 |
| `extensions.context_sources` | "Evidence I used" | ADR-W002 cited embedding_research as evidence |
| `sources` (top-level) | "I derive from these" | also valid; spec §3.2 says ADR uses `context_sources` as a more specific alias |

For ADRs the convention is `context_sources` (the spec-defined
extension field). For other types `sources` (top-level edge field) is
used.

When ADR-W002 lists `context_sources = [adr_w001_uuid, embedding_research_uuid]`:
- ADR-W001 already has `applied_in += adr_w002_uuid` from a separate
  `sources` write IF the writer chose to use that edge
- embedding_research's `applied_in` += adr_w002_uuid (citation)

In practice ADR-W002 lists ADR-W001 in BOTH `supersedes` AND
`context_sources` — explicit chain + provenance.

## What R10 (post-v1) will add

> R10. Plan shipped (`doc.doc_type: plan` with `extensions.status:
> shipped`): supporting Silver immutable; downstream ADR `adr_status`
> → `accepted`.

When a plan ships:
- supporting docs become immutable (R1 already enforces this at the
  MCP API layer)
- downstream ADRs auto-promote from `proposed` → `accepted`

Not implemented yet. Field + status enum already exist.

## How an agent answers questions

### "What's our current Cortex storage decision?"

```sql
SELECT * FROM cortex_entities
WHERE workspace_id = 'ws-qube'
  AND type = 'decision'
  AND title ILIKE '%cortex storage%'
  AND superseded_by IS NULL                -- only current versions
ORDER BY occurred_at DESC LIMIT 1;
```

Returns ADR-W002 (or W003 if it exists).

### "What did we change about Cortex storage?"

```sql
WITH RECURSIVE chain AS (
  SELECT * FROM cortex_entities WHERE id = 'adr_w003_uuid'
  UNION ALL
  SELECT e.* FROM cortex_entities e
    JOIN chain c ON e.id = ANY(c.supersedes)
)
SELECT id, title, occurred_at FROM chain ORDER BY occurred_at;
```

Returns the full chain W001 → W002 → W003 in chronological order.

## Why this design is elegant

| Without supersession | With supersession |
|---|---|
| Edit ADR-W001 → its bytes change | ADR-W001 immutable, W002 new |
| Audit trail = git log of the file | Audit trail = chain query |
| Cited references break on edit | Citations stay valid (W001's id intact) |
| "What did we decide before?" → archaeology | direct query |

The chain pattern is what every version-controlled system does. Cortex
applies it to the entity graph.
