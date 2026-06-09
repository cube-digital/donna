# 3 Reverse Backlinks — Plain English

The Cortex layer maintains exactly three **automatic** reverse-edge
back-writes:

| Forward | Reverse | Shape | Why this one back-writes |
|---|---|---|---|
| `sources[]` | `applied_in[]` | append list | citation graph — "who used me?" |
| `supersedes[]` | `superseded_by` | scalar UUID | version chain — "what replaced me?" |
| `contradicts[]` | `contradicts[]` (symmetric) | symmetric list | linter R7 — "what disagrees with me?" |

The other six edges (`entity_refs`, `cross_refs`, `parent`, `related`,
plus the two reverse-only pairs already covered) are **derived at read
time** — no write-time back-link.

## Why three different shapes

Different questions need different storage:

| Question | Best shape | Example |
|---|---|---|
| "Who cited this decision?" | append list | ADR-W007 cited by 12 different docs |
| "Was this doc replaced?" | scalar | doc v1 has at most one v2 |
| "What conflicts with this email?" | symmetric list | both emails carry the other |

Trying to use one shape for all three would force compromises.

## 1. `applied_in` — "Who used me?"

### Plain English

A meeting cites a decision and a doc. Three months later you open the
decision and want to see: "every row that depended on this decision".
Without a back-link, you'd have to scan every meeting + doc + email
looking for the decision id. With back-link, you read the decision's
`applied_in` directly.

Same idea as academic citations: a paper has a bibliography (sources)
AND a "cited by" list (applied_in). Both views matter.

### Real-life analogy

You write a contract. Years later, someone asks "what other documents
reference this contract?". You want a back-pointer, not a scan.

### Shape: append-list

A decision can be cited by hundreds of rows over time. Each citation
just appends.

```python
ADR-W007.applied_in = [
    meeting_id_1,
    doc_id_a,
    meeting_id_2,
    email_id_xyz,
    ...
]
```

### Idempotency

```python
if str(source_id) not in [str(x) for x in applied_in]:
    applied_in.append(str(source_id))
```

Same `(source, target)` written twice = one entry. Repeated ingest
doesn't bloat the list.

### Maintenance — repository.py

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

`select_for_update()` locks the row — concurrent writers queue, no
lost updates.

## 2. `superseded_by` — "What replaced me?"

### Plain English

You wrote a plan in May. In June you wrote a better plan that supersedes
it. The May plan is now stale. When an agent reads the May plan, you
want it to IMMEDIATELY know "this is stale; here's the June one":
that's the back-link.

### Real-life analogy

Software version history. v1 says "I superseded by v2". Reading v1's
docs you NEED to know v2 exists before you follow stale instructions.

### Shape: scalar UUID nullable

A doc has at most ONE replacement. (If multiple revisions exist, they
form a chain: v1 → v2 → v3, each with `supersedes = [previous]`.)

```python
class CortexEntity(...):
    superseded_by = models.UUIDField(null=True, blank=True)
```

### Maintenance — repository.py

```python
def _assign_superseded_by(self, target_id: UUID, source_id: UUID) -> None:
    target = CortexEntity.objects.select_for_update().get(id=target_id)
    if target.superseded_by != source_id:
        target.superseded_by = source_id
        target.save(update_fields=["superseded_by", "updated_at"])
```

Idempotent. If you re-ingest v2, it doesn't double-update v1.

### Why scalar, not list

Spec rule R3: explicit chain — no deletes, no silent rewrites. If a
doc is "superseded" twice, that's a misuse — the LATER chain link
wins, but really the spec expects you to chain them properly.

For real branching cases (rare), `cross_refs` is the right edge.

## 3. `contradicts` — "What disagrees with me?"

### Plain English

Two emails disagree about who handles refunds. Neither is the "source"
of the other — they just have conflicting facts. You want BOTH to know
the other exists so an agent surfaces them in an "Open Questions"
view. Symmetric: A contradicts B AND B contradicts A.

### Real-life analogy

Two witnesses give opposite accounts of the same event. The court
records both; the judge resolves later.

### Shape: symmetric list

Both rows carry each other's id in their `contradicts[]`.

```python
email_v1.contradicts = [email_v2.id]
email_v2.contradicts = [email_v1.id]
```

### Maintenance — repository.py

```python
def _append_contradicts(self, target_id: UUID, source_id: UUID) -> None:
    target = CortexEntity.objects.select_for_update().get(id=target_id)
    contradicts = list(target.contradicts or [])
    if str(source_id) not in [str(x) for x in contradicts]:
        contradicts.append(str(source_id))
    target.contradicts = contradicts
    target.save(update_fields=["contradicts", "updated_at"])
```

The writer's own `contradicts[]` is set during build (linter R7);
the repository back-writes the reverse direction.

### When R7 detection ships

R7 currently has no implementation — spec §7 calls it out as a
post-v1 feature. The plumbing is there (field exists, repository
writer exists, lint reject code exists); the actual entailment model
that detects contradictions hasn't been wired.

## Why these three back-write, others don't

The decision is volume × query-frequency × derivation-cost:

| Edge | Volume per target | Query frequency | Derivation cost | Verdict |
|---|---|---|---|---|
| `sources → applied_in` | bounded (decisions cited tens of times) | high ("what uses this?") | row scan | **back-write** |
| `supersedes → superseded_by` | at most 1 | very high ("am I stale?") | chain walk | **back-write** |
| `contradicts ↔ contradicts` | rare | medium (open questions view) | requires entailment | **back-write** |
| `entity_refs → applied_in` (rejected) | UNBOUNDED (Alice mentioned 5000×) | very high | GIN index = fast | **derive** |
| `cross_refs` | bounded but symmetric | low | trivial scope filter | **derive** |
| `parent → children[]` | varies | medium | `WHERE parent = ?` | **derive** |
| `related` (curated↔curated) | bounded (curated low vol) | low | trivial JSONB scan | **derive** |

## The atomicity guarantee

All three back-writes happen inside ONE Postgres transaction:

```python
def save_with_reverse_edges(self, entity: CortexEntity) -> CortexEntity:
    sources     = self._uuids(entity.sources)
    supersedes  = self._uuids(entity.supersedes)
    contradicts = self._uuids(entity.contradicts)

    with transaction.atomic():
        entity.save()
        for target_id in sources:
            self._append_applied_in(target_id, entity.id)
        for target_id in supersedes:
            self._assign_superseded_by(target_id, entity.id)
        for target_id in contradicts:
            self._append_contradicts(target_id, entity.id)
    return entity
```

Either all writes commit or none do. The graph never half-writes — no
"meeting cites decision but decision doesn't know about it" gap.

## Failure cases

| Failure | Behaviour |
|---|---|
| Target row doesn't exist | silent skip (`except DoesNotExist`) — spawned curated rows may not be in DB yet at the same write |
| Concurrent writer racing same target | `select_for_update` queues; second writer reads the updated state |
| Crash mid-write | savepoint rollback — every field returns to pre-txn state |

## Reading the back-links

| Read | How |
|---|---|
| "Who cited decision D?" | `D.applied_in` (already a list) |
| "Is doc X stale?" | `X.superseded_by != null` |
| "What conflicts with email E?" | `E.contradicts` (already a list) |

No extra index needed for `applied_in` / `contradicts` (they're columns
on the row). `superseded_by` has a btree index for sparse lookups.

For the **inverse** "everything Alice mentioned" use the GIN index on
`entity_refs` — derived, fast.
