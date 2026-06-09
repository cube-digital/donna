# Example 4 — Contradiction → Open Questions

Scenario: two emails disagree about who handles refunds. Cortex
detects the conflict, marks both rows with `contradicts`, and surfaces
the pair in a derived "Open Questions" view for human resolution.

R7 detection is **post-v1** — the plumbing exists (field, repository
back-writer, reject code), the entailment model that triggers it
doesn't yet. This walk shows the END-TO-END design.

## The two emails

### Email v1 — Alice

```python
CortexEntity(
    id                 = email_v1_uuid,
    workspace_id       = ws-qube,
    type               = "email",
    author             = "donna",
    source             = "gmail://email/thread-r4f1",
    title              = "Re: Refunds workflow",
    occurred_at        = 2026-06-01T09:30:00Z,
    body_md            = <body_v1>,
    extensions = {
        "thread_id":            "thread-r4f1",
        "participants_emails": [
            {"name": "Alice",   "addr": "alice@acme.com", "role": "from"},
            {"name": "Bob",     "addr": "bob@stripe-team", "role": "to"},
        ],
    },
    entity_refs = [alice_uuid, bob_uuid, acme_uuid, stripe_uuid],
)
```

Body:

```markdown
---
type: email
title: Re: Refunds workflow
thread_id: thread-r4f1
participants_emails:
  - "Alice <alice@acme.com> (from)"
  - "Bob <bob@stripe-team> (to)"
---

# Re: Refunds workflow

Confirmed in today's call: Stripe handles all refunds for Acme.
The integration ticket ENG-1234 covers the implementation.

Source: gmail://email/thread-r4f1 (ws-qube/gmail/thread-r4f1.json)
```

### Email v2 — Bob (a week later)

```python
CortexEntity(
    id                 = email_v2_uuid,
    workspace_id       = ws-qube,
    type               = "email",
    author             = "donna",
    source             = "gmail://email/thread-r4f1",  # same thread!
    title              = "Re: Refunds workflow",
    occurred_at        = 2026-06-08T14:00:00Z,
    extensions = {
        "thread_id":  "thread-r4f1",
        "participants_emails": [
            {"name": "Bob",   "addr": "bob@stripe-team", "role": "from"},
            {"name": "Alice", "addr": "alice@acme.com",  "role": "to"},
        ],
    },
    entity_refs = [alice_uuid, bob_uuid, acme_uuid, adyen_uuid],   # Adyen, not Stripe
)
```

Body:

```markdown
---
type: email
title: Re: Refunds workflow
thread_id: thread-r4f1
---

# Re: Refunds workflow

Update — after the legal review last Friday, we're going with Adyen
for refunds (not Stripe). Stripe handles other transactions only.

Please update ENG-1234 accordingly.

Source: gmail://email/thread-r4f1 (ws-qube/gmail/thread-r4f1.json)
```

Note: same `thread_id`, so each is a separate **summary** of the same
thread at different points (Gmail connector ingests on thread updates).

## R7 detection (post-v1, design)

A background job runs entailment over rows in the same scope + same
entity_refs + same thread:

```python
def detect_contradictions(workspace_id):
    for row_a in CortexEntity.objects.filter(workspace_id=workspace_id):
        # Find candidates: rows with overlapping entity_refs + recent
        candidates = find_candidates(row_a)

        for row_b in candidates:
            # Entailment via Haiku — does A claim X and B claim ¬X?
            verdict = entailment_model.check(row_a.body_md, row_b.body_md)
            if verdict == "contradicts":
                _mark_contradicts(row_a, row_b)
```

`_mark_contradicts` ends up calling the repository's symmetric
back-writer:

```python
def _mark_contradicts(row_a, row_b):
    row_a.contradicts.append(row_b.id)
    row_a.save(update_fields=["contradicts", "updated_at"])
    # Repository takes care of the symmetric back-write:
    #   row_b.contradicts.append(row_a.id)
```

## The repository back-write (already shipped)

```python
def _append_contradicts(self, target_id: UUID, source_id: UUID) -> None:
    try:
        target = CortexEntity.objects.select_for_update().get(id=target_id)
    except CortexEntity.DoesNotExist:
        return
    contradicts = list(target.contradicts or [])
    if str(source_id) not in [str(x) for x in contradicts]:
        contradicts.append(str(source_id))
    target.contradicts = contradicts
    target.save(update_fields=["contradicts", "updated_at"])
```

After R7 fires:

```sql
SELECT id, title, contradicts FROM cortex_entities WHERE id IN ('email_v1_uuid','email_v2_uuid');
```

| id | title | contradicts |
|---|---|---|
| email_v1_uuid | Re: Refunds workflow | [email_v2_uuid] |
| email_v2_uuid | Re: Refunds workflow | [email_v1_uuid] |

Symmetric. Both rows know about the conflict.

## The derived "Open Questions" view

Spec §9.3 — Open Questions is NOT a stored file. It's a derived query:

```sql
SELECT * FROM cortex_entities
WHERE workspace_id = 'ws-qube'
  AND (
    array_length(contradicts::jsonb_array, 1) > 0    -- linter-detected conflict
    OR (type = 'note' AND extensions->>'note_type' = 'open_question')
    OR (extensions->>'is_open_question')::boolean = true
  )
ORDER BY occurred_at DESC;
```

The chat UI / Obsidian plugin renders this as an Open Questions panel.

## What a human sees

```markdown
# Open Questions — qube-digital workspace

## Contradictions (linter R7)
- 🔴 **Refunds workflow** (thread: thread-r4f1)
  - [[emails/2026/06/2026-06-01-re-refunds-workflow]] says: "Stripe handles all refunds"
  - [[emails/2026/06/2026-06-08-re-refunds-workflow]] says: "Adyen for refunds, not Stripe"
  - **Resolve** — pick the truth, then create a `decision` row citing both

## Explicit open questions (note_type=open_question)
- [[notes/2026-06-05-stripe-vs-adyen]] — Which payments provider should we standardise on?
- [[notes/2026-06-12-onboarding-doc-handoff]] — Do we want a single handover doc or per-feature?
```

The human reads, decides, and creates:

```python
CortexEntity(
    type     = "decision",
    title    = "ADR-0042 — Refunds use Adyen",
    author   = "human",
    extensions = {
        "adr_status":      "accepted",
        "deciders":        [alice_uuid, bob_uuid],
        "context_sources": [email_v1_uuid, email_v2_uuid],   # cite both!
    },
    body_md = """
# ADR-0042 — Refunds use Adyen

## Context
Emails from 2026-06-01 and 2026-06-08 contradicted on the refunds
provider. Legal review on 2026-06-05 confirmed Adyen for compliance
reasons.

## Decision
Refunds: Adyen. Other transactions: Stripe stays.

## Consequences
- Update ENG-1234 (Linear ticket)
- Update integration spec doc

Source: manual://adr/0042
""",
)
```

## Why neither email gets auto-merged

Spec §7 R7: "NEVER auto-merged". The system surfaces; the human
decides. Two emails are both valid first-hand evidence; choosing one
to delete would lose history.

`TYPE_AUTHORITY` (R5) would say both emails carry weight 50 (default
email). Neither dominates. Hence: NOT a write-time block, but a
surface for human attention.

For higher-authority conflicts (e.g. a `chat` says X and a `doc:
contract` says ¬X), the contract wins by weight 95 vs 30 — agents
can autoresolve in that direction. Email vs email = manual.

## Three resolution paths

| Path | Mechanism |
|---|---|
| **Decision (typical)** | New `decision` row cites both as `context_sources`, declares authoritative answer |
| **Supersession** | If email_v2 is logically a correction, the agent could rewrite it as a doc with `supersedes=[email_v1.id]` |
| **Ignore** | If both are noise, mark as `note_type: journal` so they fall out of view |

Cortex doesn't pick — it presents.

## The agent's job in answering "what's our refunds policy?"

Without R7:

```python
agent.search("refunds policy")
# → returns email_v1 (mentions Stripe), email_v2 (mentions Adyen), ENG-1234
# → agent hallucinates a confident answer like "Stripe handles refunds"
```

With R7 + Open Questions view:

```python
agent.search("refunds policy")
# → returns email_v1, email_v2, ADR-0042
# → ADR-0042 wins by TYPE_AUTHORITY (decision=100 vs email=50)
# → email_v1 carries contradicts → flag in answer
# → answer: "Refunds use Adyen per ADR-0042 (resolved on 2026-06-15;
#   superseded the earlier email_v1 claim of Stripe)"
```

The contradiction edge stays on both emails forever, even after
resolution — it's part of the audit trail.

## Why this design

| Without R7 | With R7 |
|---|---|
| Contradictions invisible | flagged in derived view |
| Agent picks arbitrarily | agent reads `contradicts` and notes uncertainty |
| Each tool re-detects independently | one canonical detection, surfaced everywhere |
| History rewritten by edits | full audit trail preserved |

Spec §7 + §9.3 lock the design. Implementation lands when the
entailment model is wired (post-v1).

## Failure modes

| Scenario | Behaviour |
|---|---|
| R7 false positive | linter mistakenly flags two emails — human un-flags by deleting the contradicts entry via MCP API |
| Three-way contradiction | R7 walks pairwise; all three rows reference the other two via `contradicts` |
| Contradiction in the same row pair detected twice | repository dedupes — idempotent append |
| Resolution via decision | decision's `context_sources` includes both contradictory rows; their `applied_in` updates atomically |
