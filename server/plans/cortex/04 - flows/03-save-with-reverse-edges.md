# `save_with_reverse_edges` — Atomic Bidirectional Writes

The single mutating method in `CortexEntityRepository`. Maintains the
bidirectional edge invariants per spec §4 inside one Postgres
transaction.

## Why one method, not two writes

Naive:
```python
M.save()                              # write forward
D.applied_in.append(M.id); D.save()   # patch reverse
```

Three failure modes:

1. **Crash between writes** → `applied_in[]` never updated → forever
   inconsistent
2. **Concurrent writer races** D's `applied_in[]` between read and save
   → lost update
3. **M writes succeed but D doesn't exist** (referenced wrong id) →
   silent half-graph

`save_with_reverse_edges` wraps it all in `transaction.atomic()`:

```python
def save_with_reverse_edges(self, entity: CortexEntity) -> CortexEntity:
    sources     = self._uuids(entity.sources)
    supersedes  = self._uuids(entity.supersedes)
    contradicts = self._uuids(entity.contradicts)

    with transaction.atomic():
        entity.save()                                    # write forward
        for target_id in sources:
            self._append_applied_in(target_id, entity.id)
        for target_id in supersedes:
            self._assign_superseded_by(target_id, entity.id)
        for target_id in contradicts:
            self._append_contradicts(target_id, entity.id)
    return entity
```

Three guarantees:

- **Atomic** — savepoint rollback drops all writes on any failure
- **Serialised** — `SELECT FOR UPDATE` locks target row; concurrent
  writers queue
- **Idempotent** — dedupe via `if str(id) not in applied_in`

## How "which reverse edges" is determined

The forward → reverse mapping is **hardcoded by spec §4**. Only three
forward fields trigger reverse maintenance:

```python
sources     = entity.sources       # → _append_applied_in
supersedes  = entity.supersedes    # → _assign_superseded_by
contradicts = entity.contradicts   # → _append_contradicts
```

The other forward edges (`entity_refs`, `cross_refs`, `parent`,
`related`) do NOT have reverse writes. They're derived at read time.

| Forward | Reverse maintained? | Why not |
|---|---|---|
| `sources` | ✅ append `applied_in` | citation graph |
| `supersedes` | ✅ assign `superseded_by` | version chain |
| `contradicts` | ✅ append `contradicts` (symmetric) | linter R7 |
| `entity_refs` | ❌ derived | high cardinality (5000× per person) |
| `cross_refs` | ❌ derived | symmetric by query |
| `parent` | ❌ derived | reverse is `WHERE parent = me` |
| `related` | ❌ derived | curated-to-curated, low volume |

## The three reverse writers

### `_append_applied_in(target_id, source_id)`

Shape: append-list with dedupe.

```python
def _append_applied_in(self, target_id: UUID, source_id: UUID) -> None:
    try:
        target = CortexEntity.objects.select_for_update().get(id=target_id)
    except CortexEntity.DoesNotExist:
        return
    applied_in = list(target.applied_in or [])
    if str(source_id) not in [str(x) for x in applied_in]:
        applied_in.append(str(source_id))
    target.applied_in = applied_in
    target.save(update_fields=["applied_in", "updated_at"])
```

Why `select_for_update`: another writer ingesting a meeting that also
cites the same decision must queue. Without the lock, both writers
read the same `applied_in`, both append, both save — one append is
lost.

### `_assign_superseded_by(target_id, source_id)`

Shape: scalar UUID (1:1 cardinality).

```python
def _assign_superseded_by(self, target_id: UUID, source_id: UUID) -> None:
    target = CortexEntity.objects.select_for_update().get(id=target_id)
    if target.superseded_by != source_id:           # idempotent
        target.superseded_by = source_id
        target.save(update_fields=["superseded_by", "updated_at"])
```

Each row has at most one replacement. If a doc is superseded twice,
the LATER write wins — but spec §3 R3 expects you to chain
(old → newer → newest), each step with one `supersedes`.

### `_append_contradicts(target_id, source_id)`

Shape: append-list with dedupe. Symmetric write — both sides updated.

```python
def _append_contradicts(self, target_id: UUID, source_id: UUID) -> None:
    target = CortexEntity.objects.select_for_update().get(id=target_id)
    contradicts = list(target.contradicts or [])
    if str(source_id) not in [str(x) for x in contradicts]:
        contradicts.append(str(source_id))
    target.contradicts = contradicts
    target.save(update_fields=["contradicts", "updated_at"])
```

The writer's own `contradicts[]` is set during build; the repository
writes the reverse direction.

## Silent skip on missing target

```python
try:
    target = CortexEntity.objects.select_for_update().get(id=target_id)
except CortexEntity.DoesNotExist:
    return       # silent skip
```

Why silent: spawned entities might be created within the same pipeline
run AFTER the source row. Strict raise would break the writer for
legitimate spawn cases. The linter can flag later (planned).

## Concrete walk: ADR replaces older ADR

```
ADR-W001 "use PG-only" exists.

You write ADR-W002 "use PG + pgvector":
  supersedes = [ADR-W001.id]

save_with_reverse_edges:
  BEGIN
    INSERT ADR-W002 (supersedes=[ADR-W001.id], ...)
    SELECT FOR UPDATE ADR-W001
    UPDATE ADR-W001 SET superseded_by = ADR-W002.id
  COMMIT
```

After commit:

```
ADR-W001.superseded_by = ADR-W002.id   ← back-pointer
ADR-W002.supersedes    = [ADR-W001.id] ← forward
```

When an agent reads ADR-W001 it sees `superseded_by` and follows the
chain to current truth.

## Performance characteristics

| Operation | Cost |
|---|---|
| INSERT new entity | O(1) + index updates |
| `_append_applied_in` per target | O(1) — read + write one row |
| `_assign_superseded_by` per target | O(1) |
| `_append_contradicts` per target | O(1) |
| Total per write | O(1 + |sources| + |supersedes| + |contradicts|) |

In practice `|sources|` is 0-5, `|supersedes|` is 0-1,
`|contradicts|` is 0 (R7 not enabled). Most writes pay only the
entity INSERT.

## Concurrency

```
Writer A: M cites D
Writer B: M' cites D

Without lock: both read D.applied_in, both append, both save → one update lost
With select_for_update:
  A acquires lock on D
  B queues
  A appends + commits + releases
  B acquires lock, reads updated state, appends + commits
```

Postgres `SELECT FOR UPDATE` guarantees serialised access per row.

## Why JSONB arrays, not edge tables

| Choice | Pros | Cons |
|---|---|---|
| Edge table (`cortex_edge`) | classical N:M | extra JOIN per query, more migrations |
| JSONB array on entity | one round-trip, GIN-indexable | array updates need read-modify-write |

For the volumes involved (bounded `applied_in` per target,
bounded `supersedes` chains), JSONB wins on query speed at the cost of
slightly more careful writes. The cost is paid here in
`save_with_reverse_edges`.

## Failure recovery

If `transaction.atomic()` rolls back:

- The entity INSERT is reverted (no row in `cortex_entities`)
- All reverse-edge UPDATEs are reverted (targets unchanged)

The caller (Fathom task) catches the exception, logs, and the next
ingest of the same DeliveryPackage will retry — idempotent via
`unique (workspace_id, content_hash)`.

## What's still NOT covered

- **R7 contradiction detection** — auto-population of `contradicts[]`
  fields requires an entailment model. Not shipped. The repository
  WRITE path is ready; the DETECT path isn't.
- **Cross-scope `cross_refs` reject** — linter R4 enforcement is
  at the repository level (needs to fetch the target's scope). Not
  shipped.
- **MCP API update path** — `cortex.update_entity` mutating `body_md`
  / `extensions` triggers re-embed + re-cluster + reverse-edge
  refresh. P9.

## Reads — using the back-links

| Read | How |
|---|---|
| "Who cited this decision?" | `decision.applied_in` (already a list) |
| "Is this doc stale?" | `doc.superseded_by IS NOT NULL` |
| "What conflicts with this email?" | `email.contradicts` (already a list) |

No extra index needed — these are columns on the row itself.
