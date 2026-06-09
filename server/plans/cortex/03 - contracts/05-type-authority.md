# TYPE_AUTHORITY Registry

Closed numeric registry from spec §7.1. Used by linter R5 to decide
who wins when two entities conflict.

**Higher = more authoritative.** Code: `donna/cortex/authority.py`.

## The 30-key registry

```python
TYPE_AUTHORITY = {
    "decision":              100,    # ADRs — highest
    "doc:contract":           95,
    "doc:signed_document":    95,
    "doc:offer":              80,
    "project":                75,
    "doc:spec":               70,
    "doc:requirements":       70,
    "concept":                65,
    "person":                 60,
    "org":                    60,
    "meeting":                55,
    "doc:handover":           55,
    "doc:integration_spec":   55,
    "doc:runbook":            55,
    "doc:plan":               50,
    "doc:technical_analysis": 50,
    "email":                  50,
    "doc:internal_memo":      45,
    "doc:architecture_note":  45,
    "doc:design_note":        45,
    "ticket":                 45,
    "note:checkpoint":        40,
    "note:action_item":       40,
    "note:open_question":     40,
    "note":                   35,     # default for note without note_type
    "doc:presentation":       35,
    "chat":                   30,
    "doc:other":              25,
    "clip":                   20,
    "note:journal":           15,     # lowest
}
```

## Lookup logic

```python
def authority_for(entity_type: str, sub_discriminator: str | None = None) -> int:
    if sub_discriminator:
        key = f"{entity_type}:{sub_discriminator}"
        if key in TYPE_AUTHORITY:
            return TYPE_AUTHORITY[key]
    return TYPE_AUTHORITY.get(entity_type, 0)
```

Tries the sub-discriminated key first (`doc:contract`), then the bare
type (`doc`). Returns 0 for unknown types — linter would already have
rejected upstream.

## Why specific weights

The numbers encode the **trust hierarchy** a human would use:

| Tier | Range | Examples | Reason |
|---|---|---|---|
| **Top — formal decisions** | 95-100 | `decision`, `doc:contract`, `doc:signed_document` | Legally / governance binding |
| **High — formal docs** | 70-80 | `doc:offer`, `doc:spec`, `doc:requirements`, `project` | Agreed scope or product spec |
| **Curated** | 60-75 | `concept`, `person`, `org`, `project` | Human-vetted ground truth |
| **Event records** | 50-55 | `meeting`, `doc:handover`, `doc:plan` | First-hand evidence |
| **Working docs** | 45 | `doc:internal_memo`, `doc:architecture_note`, `doc:design_note`, `ticket` | Intent + WIP |
| **Notes** | 35-40 | `note:*` variants | Personal / inflight |
| **Casual sources** | 15-30 | `chat`, `clip`, `note:journal` | Lossy, opinionated, contextual |

## Where it's used

### R5 — conflict resolution

When two entities make contradictory claims about the same fact, the
higher-authority entity's claim wins. Example: a `decision` (ADR
`100`) and a `chat` (`30`) disagree on which payments provider to use →
the ADR wins; the chat goes to Open Questions for human review.

### R7 — contradiction detection (future)

When the entailment model fires R7, it consults `TYPE_AUTHORITY` to
decide which entity gets the warning surfaced first.

### Agent ranking (future)

When the read API returns N candidates for a query, the agent can
sort by `TYPE_AUTHORITY` to read the most trustworthy first.

## Sub-discriminator weight rationale

### `doc:*` (16 sub-types)

The `doc` family has the widest weight spread (25-95). A signed
contract is 95; a random PDF without doc_type drops to 25 (`doc:other`).

The deltas matter:
- `doc:contract` (95) > `doc:offer` (80) — signed > proposed
- `doc:spec` (70) > `doc:plan` (50) — spec is what was agreed, plan
  is how we'd do it
- `doc:internal_memo` (45) > `doc:presentation` (35) — slides drift
- `doc:other` (25) — unclassified, lowest doc weight

### `note:*` (5 sub-types)

- `note:checkpoint` (40) — recorded "where we are"
- `note:action_item` (40) — explicit TODO
- `note:open_question` (40) — flagged unresolved
- `note` (35) — bare note without sub-type
- `note:journal` (15) — personal stream-of-thought, lowest

## Why these are static numbers, not learned weights

A learned-from-data weight would shift over time and break the
deterministic guarantee. Linter behaviour MUST be reproducible across
runs. Static numbers = deterministic R5/R7 behaviour.

Workspaces can override via `_meta/extensions/typespecs/<workspace>/`
to tweak per-workspace (rare but supported).

## Amendments

Adding a new key requires a spec amendment + ADR. Spec §2 lists
`TYPE_AUTHORITY` as a closed surface.

Current 30 keys cover all 12 types + their sub-discriminators. New
types or sub-types would need new entries — held to the spec gate.
