# 9 Edge Types

Spec §4 locks the edge vocabulary at **nine** types. Every edge has a
canonical name, direction, semantic, and maintenance rule. Linter
rejects ad-hoc edges (`UNKNOWN_EDGE_TYPE`).

## The 9

| Edge | From | To | Semantic | Maintenance |
|---|---|---|---|---|
| `entity_refs` | any Silver | curated (person/org/concept/project/decision) | "this row mentions this curated entity" | manual at write |
| `sources` | any | any | "this entity was informed by these" | manual at write |
| `cross_refs` | any | any | "related context, same scope" | manual or detector |
| `supersedes` | any | any (same type) | "explicit replacement chain" | manual at write |
| `parent` | any | any | "child of (email-in-thread, clip-from-meeting)" | manual at write |
| `related` | curated | curated | "cross-link between curated entities" | manual at write |
| `contradicts` | any | any | "linter detected conflicting claims" | auto by linter |
| `applied_in` | reverse of `sources` | — | "entities that cite this" | auto-maintained |
| `superseded_by` | reverse of `supersedes` | — | "newer entity that replaced this" | auto-maintained |

## Forward (6) vs Reverse (3)

```
Forward (writer sets, immutable per R1):
  entity_refs   ← writer drops UUIDs based on extraction
  sources       ← writer drops UUIDs based on adapter metadata
  cross_refs    ← human/agent links siblings in same scope
  supersedes    ← writer/agent declares "this replaces that"
  parent        ← writer / connector emits hierarchy
  related       ← human/agent links curated rows symmetrically

Reverse (repository auto-maintains in same txn):
  applied_in    ← appended to target's row when sources includes its id
  superseded_by ← assigned to target's row when supersedes includes its id
  contradicts   ← symmetric; appended to BOTH rows by linter R7
```

## Each edge in plain English

### 1. `entity_refs` — "mentions"

**Direction:** row → curated entity (person/org/concept/project/decision)
**Cardinality:** N:M (a meeting can mention many people; a person is mentioned in many meetings)

**Why:** unifies the entity-axis navigation. "Show me everything about
Acme" = `SELECT * FROM cortex_entities WHERE entity_refs @> [acme_id]`.

**Maintenance:** the writer sets it at write time from extractor output.
The **reverse direction** is NOT stored — it's derived via the GIN
index lookup (high cardinality would blow up the JSONB array).

**Example:**
```python
meeting.entity_refs = [alice_id, bob_id, acme_id]
# Acme's applied_in does NOT include this meeting.
# Acme's content = SELECT WHERE entity_refs @> [acme_id]
```

### 2. `sources` — "informed by"

**Direction:** row → any
**Cardinality:** N:M

**Why:** citation graph. A doc cites a meeting cites a research clip.
You can walk the chain backwards from any conclusion to its evidence.

**Maintenance:** writer sets it; repository **auto-writes `applied_in`**
on each target inside the same txn (atomic invariant).

**Example:**
```python
plan_doc.sources = [meeting_id, ticket_id]
# Repository writes:
# meeting.applied_in += plan_doc.id
# ticket.applied_in += plan_doc.id
```

### 3. `cross_refs` — "related in scope"

**Direction:** row ↔ row (same scope)
**Cardinality:** N:M
**Rule (R4):** strictly intra-scope. The linter rejects cross_refs
that span `(workspace, client, project)` boundaries.

**Why:** human/agent says "see also" between siblings. Doesn't carry
citation strength — just a hint.

**No back-write needed:** the lookup is symmetric — query
`WHERE A IN cross_refs OR B IN cross_refs`.

### 4. `supersedes` — "replaces"

**Direction:** newer → older (same type)
**Cardinality:** N:1 typically (chain)
**Rule (R3):** explicit replacement. No deletion. The chain is the
audit trail.

**Maintenance:** writer sets it; repository **auto-assigns `superseded_by`**
on each target.

**Example:**
```python
adr_v2.supersedes = [adr_v1.id]
# Repository writes:
# adr_v1.superseded_by = adr_v2.id
```

When an agent reads `adr_v1` it sees `superseded_by` and follows the
chain to current truth.

### 5. `parent` — "child of"

**Direction:** child → parent
**Cardinality:** N:1
**Rule:** parent must share scope (linter R-INVALID_SCOPE).

**Why:** structural hierarchy. Email-from-thread root. Clip extracted
from a meeting recording. Note-spawned-from-meeting.

**No back-write needed:** "all children of X" = `WHERE parent = X.id`.

**Example:**
```python
clip.parent = meeting_id      # this clip is from this meeting
```

### 6. `related` — "curated-curated cross-link"

**Direction:** curated → curated (only)
**Cardinality:** N:M
**Rule:** restricted to curated types (person/org/concept/project/decision).

**Why:** "Alice works at Acme". "Concept A relates to Concept B".
Sibling-graph between curated rows.

**No back-write needed at scale:** curated rows are low-volume; the
symmetric pair is checked at query time.

### 7. `contradicts` — "disagrees with"

**Direction:** symmetric (A contradicts B and B contradicts A)
**Cardinality:** N:M
**Rule (R7):** auto-detected by linter when entity body claims X but a
newer Silver claims ¬X without `supersedes`.

**Maintenance:** repository writes BOTH sides in same txn.

**Why:** surfaces unresolved conflicts in a derived "Open Questions"
view (spec §9.3). No auto-merging — humans decide.

**Example:**
```python
email_v2.body_md = "We agreed on Adyen, not Stripe."
# Linter R7 detects contradiction with email_v1 (says "Stripe")
# Writes:
#   email_v2.contradicts += email_v1.id
#   email_v1.contradicts += email_v2.id
```

### 8. `applied_in` — REVERSE of `sources`

**Direction:** target ← row that cited it
**Cardinality:** N:1 (one target has many citers)
**Maintenance:** repository auto-maintained.

**Why:** "what's this decision used in?" — without a back-write, you'd
scan every row looking for the decision id.

**Storage shape:** JSONB array of UUIDs.

### 9. `superseded_by` — REVERSE of `supersedes`

**Direction:** old row ← new row that replaced it
**Cardinality:** 1:1 (one target has one replacement at most)
**Maintenance:** repository auto-maintained.

**Storage shape:** scalar UUID nullable.

## What about derived edges?

Spec §4 calls out one **derived** edge — not stored:

| "Edge" | Derivation |
|---|---|
| `touchpoints` on `person` / `org` | reverse lookup over `entity_refs` scoped per `(client, project)`, computed lazily at read time |

R9 in the linter: touchpoints accrue per Silver `entity_refs` reverse
lookup; derived, not stored.

## Why these specific 3 are write-time back-written

The decision criteria:

| Edge | Volume per target | Query frequency | Cheap derivation? | Back-write? |
|---|---|---|---|---|
| `sources → applied_in` | bounded (decisions get cited tens of times) | high ("what uses this?") | needs row scan | YES |
| `supersedes → superseded_by` | at most 1 per row | high ("is this stale?") | requires walking the chain | YES |
| `contradicts → contradicts` | rare (only when linter fires) | medium ("flag conflicts") | needs entailment | YES |
| `entity_refs → applied_in` (rejected) | unbounded (Alice mentioned 5000×) | very high | GIN index = fast | NO — derive |
| `cross_refs` | bounded but symmetric | low | trivial scope filter | NO — derive |
| `parent → children[]` | varies; usually small | medium | `WHERE parent = ?` | NO — derive |
| `related` (curated↔curated) | bounded (curated low volume) | low | trivial JSONB scan | NO — derive |

**Rule of thumb:** back-write iff (a) the query is hot, (b) deriving
is expensive without an index, (c) the volume per target is bounded.

## Why three back-links, not one merged

Could conceptually merge `applied_in / superseded_by / contradicts`
into one `back_links: List[BackLink]` where each carries a kind. But:

| Concern | Single mixed list | Three separate fields |
|---|---|---|
| Storage shape | JSONB array of dicts | three fields, two are arrays + one scalar |
| Indexing | one GIN on the kind+id | three indexes, smaller scope |
| Query "who cites this?" | filter array | direct column read |
| Query "is this stale?" | scan + filter | scalar comparison |
| Pydantic shape | wider, ambiguous | per-type Literal, fits the model |

The single-list approach pushes complexity into every query. The split
keeps the contract clean.

## Linter rejects ad-hoc edges

Spec §7.2 — `UNKNOWN_EDGE_TYPE`:

```python
def _check_known_edges(self, entity):
    ext_keys = set((entity.extensions or {}).keys())
    unknown_edges = ext_keys & {"sourcs", "ref", "links", ...}
    if unknown_edges:
        raise LinterError(
            RejectCode.UNKNOWN_EDGE_TYPE,
            f"ad-hoc edge keys in extensions: {sorted(unknown_edges)}",
        )
```

A workspace cannot invent a new edge name without amending the spec
(see §7 "extensions points" — edges aren't an extension point).
