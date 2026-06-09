# Linter R1-R10

Spec §7 defines ten code-enforced rules. Implementation:
`donna/cortex/linter.py:FrontmatterLinter`.

Every reject carries a closed-vocab `RejectCode` from
`donna/cortex/authority.py:RejectCode`. See [`06-reject-codes.md`](./06-reject-codes.md)
for the full code list.

## R1 — Immutability after first write

> Silver immutable after first write. Only auto-maintained edges
> (`applied_in`, `superseded_by`, `contradicts`) may be appended
> post-write.

**Enforcement:** at the **MCP API layer** (P9). The
`cortex.update_entity(entity_id, patch)` method only accepts
`body_md` + `extensions` mutations; rejects mutations to `type`,
`author`, `source`, `occurred_at`, edge fields.

For now (pre-MCP), there's no update path — every write goes through
`CortexWriter.write(dp)` which creates a new row.

## R2 — Both timestamps required

> Every entity carries `occurred_at` + `synthesized_at`. Both ISO 8601.

**Enforcement:** `_check_temporal`:

```python
def _check_temporal(self, entity):
    if entity.occurred_at is None:
        raise LinterError(
            RejectCode.MISSING_OCCURRED_AT,
            "occurred_at is required (R2)",
        )
    # synthesized_at = created_at (TimestampsMixin auto_now_add)
    # — implicitly populated at save; no pre-save check needed
```

**Reject code:** `MISSING_OCCURRED_AT`.

## R3 — Explicit supersession

> Newer entity carries `supersedes`; older gets `superseded_by` auto.
> No deletion.

**Enforcement:** `_check_supersedes` rejects duplicate ids in the
`supersedes` array.

```python
def _check_supersedes(self, entity):
    seen = set()
    for target in entity.supersedes or []:
        if str(target) in seen:
            raise LinterError(
                RejectCode.PYDANTIC_INVALID,
                f"duplicate supersedes target {target}",
            )
        seen.add(str(target))
```

The reverse-edge invariant is enforced by `Repository._assign_superseded_by`
in the same txn.

## R4 — `cross_refs` strictly intra-scope

> `cross_refs` for related entities in same `(workspace, client, project)` scope.

**Enforcement:** `_check_cross_refs` rejects non-list shape; the
pairwise scope check against actual rows is the **repository's** job
during persist (it can fetch the target's scope).

**Reject code:** `INVALID_CROSS_REF_SCOPE` (when repo-level check fires).

## R5 — `TYPE_AUTHORITY` for conflict resolution

> Source hierarchy by `TYPE_AUTHORITY` numeric registry (closed,
> below). On conflict, highest authority wins.

**Enforcement:** NOT a linter reject — it's a **conflict-resolution**
helper used by R7 contradiction-detection and by future agent layers
that pick "the most trustworthy source" when multiple rows disagree.

`donna.cortex.authority.authority_for(type, sub_discriminator)` returns
the integer weight. See [`05-type-authority.md`](./05-type-authority.md).

## R6 — Resynth trigger

> Gold-resynth trigger (applies to `project`, `concept`): N new sources
> in same cluster since `last_synthesized` → queue resynth.

**Enforcement:** NOT a write-time linter check. Background Celery task
walks curated rows nightly and bumps `last_synthesized` after
re-running synthesis.

Implementation TODO — currently `last_synthesized` is set at first
write only.

## R7 — Contradiction detection

> `Silver A` claims X vs `Silver B` claims ¬X → row appended to
> derived "Open Questions" view, NEVER auto-merged.

**Enforcement:** background — requires entailment model. POST-V1
feature. Field + repository back-writer already exist; the detector
that triggers them is the missing piece.

Reject code reserved: `IMPLICIT_CONTRADICTION` (for synchronous use
when the writer can self-detect a contradiction).

## R8 — Confidence decay

> `high → medium → low` over 6 months unless reaffirmed by newer
> source citing it.

**Enforcement:** background Celery task scans `last_synthesized` and
decays `confidence` accordingly. TODO.

Currently every spawned row defaults to `confidence=medium`,
connector-ingested rows default to `confidence=high`.

## R9 — Touchpoints derived

> Touchpoints on curated `person` / `org` accrue per Silver
> `entity_refs` reverse lookup; derived, not stored.

**Enforcement:** NOT a linter check. Read-side: any `find_referencing`
result over a curated entity yields its touchpoints, grouped per
`(client_id, project_id)`. No back-write at write time (high
cardinality).

## R10 — Plan shipped immutability

> Plan shipped (`doc.doc_type: plan` with `extensions.status: shipped`):
> supporting Silver immutable; downstream ADR `adr_status` → `accepted`.

**Enforcement:** at MCP API layer (P9). The `update_entity` call
rejects mutations on docs whose supporting entities have shipped.
Currently not enforced.

## Plus the §7.2 hard rejects (write-time)

These ARE enforced by `FrontmatterLinter.check()` today:

### `MISSING_REQUIRED_EXTENSION`

```python
# doc missing doc_type
if entity.type == "doc" and not (entity.extensions or {}).get("doc_type"):
    raise LinterError(RejectCode.MISSING_REQUIRED_EXTENSION, ...)

# note missing note_type
if entity.type == "note" and not (entity.extensions or {}).get("note_type"):
    raise LinterError(RejectCode.MISSING_REQUIRED_EXTENSION, ...)

# decision missing context_sources
if entity.type == "decision" and not (entity.extensions or {}).get("context_sources"):
    raise LinterError(RejectCode.MISSING_REQUIRED_EXTENSION, ...)
```

### `INSUFFICIENT_EVIDENCE`

```python
if entity.type == "concept" and len(entity.sources or []) < 2:
    raise LinterError(RejectCode.INSUFFICIENT_EVIDENCE, ...)
```

### `DUPLICATE`

Enforced by `UNIQUE (workspace_id, content_hash)` Postgres constraint
+ caught by the writer (returns existing entity id).

### `MISSING_ENTITY_REFS` (warning)

Spec §7.2: "Silver missing entity_refs after content scan finds named
entities". The writer's `entity_refs` is auto-filled by the extractor
chain; this reject is a warning surfaced in Open Questions, not a
hard block.

### `MISSING_SOURCE_FOOTER`

```python
last_line = body.rstrip().splitlines()[-1]
if not (last_line.startswith("Source:") or last_line.startswith("Spawned by:")):
    raise LinterError(RejectCode.MISSING_SOURCE_FOOTER, ...)
```

### `UNKNOWN_EDGE_TYPE`

```python
ext_keys = set((entity.extensions or {}).keys())
unknown_edges = ext_keys & {"sourcs", "ref", "links"}
if unknown_edges:
    raise LinterError(RejectCode.UNKNOWN_EDGE_TYPE, ...)
```

### `INVALID_SCOPE`

```python
if entity.project_id is not None and entity.client_id is None:
    raise LinterError(
        RejectCode.INVALID_SCOPE,
        "project_id non-null but client_id is null — boundary violation",
    )
```

## Pydantic schema check

`_check_extensions` runs `EXTENSION_MODELS[entity.type].model_validate(...)`:

```python
def _check_extensions(self, entity):
    model = EXTENSION_MODELS[entity.type]
    try:
        model.model_validate(entity.extensions or {})
    except ValidationError as exc:
        missing_required = any(err.get("type") == "missing" for err in exc.errors())
        code = (
            RejectCode.MISSING_REQUIRED_EXTENSION
            if missing_required
            else RejectCode.PYDANTIC_INVALID
        )
        raise LinterError(code, f"extensions invalid for {entity.type}: {exc}")
```

Pydantic's `Literal` types reject off-vocabulary values, catching things
like `note_type="random-tag"` automatically.

## Call site

`CortexWriter.write(dp)` step 10:

```python
self.linter.check(new_entity)
```

If `LinterError` raised, the writer propagates — no DB write happens.
The connector task (Fathom et al.) catches in best-effort mode and
logs.

## Lint dry-run (P9)

Spec §10.2 includes `cortex.linter_check(payload)` as a dedicated MCP
method for clients (Obsidian plugin, CLI) to validate before
committing. Currently unwired.

## Why R1-R10 matter

| Rule | Without it |
|---|---|
| R1 | Edits to history rewrite truth — agents trust nothing |
| R2 | Time-based queries break; agents can't pick "latest" |
| R3 | Stale ADRs followed silently |
| R4 | Cross-scope contamination — Acme notes leak into Stripe queries |
| R5 | Conflict resolution arbitrary — picks whichever was last written |
| R6 | Synthesised concepts drift; no resynth ever fires |
| R7 | Contradictions hidden; agent picks one randomly |
| R8 | Old high-confidence claims out-rank new ones |
| R9 | Touchpoints stored explicitly → 5000-element JSONB arrays |
| R10 | Shipped plans rewritten retroactively → audit trail invalid |

Locked closed vocabulary + Pydantic + Postgres unique constraint =
data is trustworthy by construction.
