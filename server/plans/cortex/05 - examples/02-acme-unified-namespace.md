# Example 2 — Acme Unified Namespace

Scenario: over the course of a quarter, your team accumulates dozens of
artifacts about Acme. They come from different connectors at different
times and live in different folders. How does the Cortex layer
unify them into ONE namespace?

## The scenario

Over Q2 2026, ten artifacts land for Acme:

| # | Type | Connector | Folder (canonical) | Mentioned Acme? |
|---|---|---|---|---|
| 1 | meeting | Fathom | `meetings/2026/04/` | ✅ via entity_refs |
| 2 | meeting | Fathom | `meetings/2026/05/` | ✅ |
| 3 | meeting | Fathom | `meetings/2026/06/` | ✅ |
| 4 | email | Gmail | `emails/2026/04/` | ✅ |
| 5 | email | Gmail | `emails/2026/05/` | ✅ |
| 6 | doc:plan | Drive | `docs/` | ✅ |
| 7 | doc:contract | Drive | `docs/` | ✅ |
| 8 | clip | Web Clipper | `clips/` | ✅ |
| 9 | ticket | Linear | `tickets/linear/` | ✅ |
| 10 | chat | Slack | `chats/team-acme/` | ✅ |

Ten files, ten folders. Each mentions Acme in its metadata or body.

**Without Cortex:** the agent would need to crawl each folder, look
for "Acme" in every file, and stitch together a coherent view.

**With Cortex:** all ten are bound to ONE Acme `org` row via
`entity_refs[]`. The unified view emerges from a single GIN query.

## The Acme org row

When the first Acme-related artifact lands (let's say meeting #1), the
`DeterministicResolver` notices `acme.com` as a non-public domain in
the host email. No existing org row → spawn:

```python
acme_uuid = uuid4()
CortexEntity(
    id                 = acme_uuid,
    workspace_id       = ws-qube,
    type               = "org",
    author             = "donna",
    source             = f"cortex://spawn/{acme_uuid}",
    bronze_storage_key = "",
    content_hash       = sha256("org:acme.com"),
    occurred_at        = <now>,
    title              = "Acme",
    body_md            = "# Acme\n\n_Spawned by the Cortex resolver._\n\nSpawned by: cortex-resolver",
    confidence         = "medium",   # not human-verified
    last_synthesized   = <today>,
    extensions = {
        "relationship":  "client",   # default; human can promote later
        "legal_name":    "Acme",
        "email_domains": ["acme.com"],
        "industry":      None,
        "parent_path":   "clients/acme",
        "slug":          "acme",
    },
)
```

Meeting #1's `entity_refs` now includes `acme_uuid`.

## The next 9 ingests

When meeting #2 (May) arrives, the resolver looks up:

```sql
SELECT * FROM cortex_entities
WHERE workspace_id = 'ws-qube'
  AND type = 'org'
  AND extensions->'email_domains' @> '["acme.com"]'
LIMIT 1;
```

Finds the existing Acme row → returns `acme_uuid`. Meeting #2 gets
`entity_refs = [..., acme_uuid]`. No new spawn.

Same for meetings #3, emails #4-5, doc #6-7, clip #8, ticket #9, chat
#10. By end of quarter, all ten reference `acme_uuid`.

## The unified namespace — derived view

```sql
SELECT * FROM cortex_entities
WHERE workspace_id = 'ws-qube'
  AND entity_refs @> '["acme_uuid"]'
ORDER BY occurred_at DESC;
```

Returns all 10 artifacts in chronological order. The agent now has
"everything about Acme" in one query — no folder walks, no full-text
scans.

## How the agent navigates

The MCP API (P9) exposes this via a uniform endpoint:

```
GET /cortex/index?path=clients/acme
```

Path classifier:
- "clients/acme" doesn't match any canonical filing path
- → falls through to entity-axis derived view
- → looks up the org row for slug=acme
- → calls `find_referencing(acme_uuid, ws-qube)`
- → returns same 10 entries

Same response shape as topical / temporal queries. Agent doesn't care
about the lens — uniform interface.

## Cluster distribution

Each of the 10 artifacts also has a `cluster_id` from HDBSCAN. They
DON'T all belong to one cluster — the clustering boundary is per
scope, not per entity_refs:

| Artifact | cluster_id | cluster_name |
|---|---|---|
| meeting #1 (intro) | A | "Customer Onboarding" |
| meeting #2 (kickoff) | A | "Customer Onboarding" |
| meeting #3 (integration review) | B | "Payments Integration" |
| email #4 (welcome) | A | "Customer Onboarding" |
| email #5 (legal Q) | C | "Legal & Contracts" |
| doc #6 (project plan) | B | "Payments Integration" |
| doc #7 (signed contract) | C | "Legal & Contracts" |
| clip #8 (Stripe API doc) | B | "Payments Integration" |
| ticket #9 (integration bug) | B | "Payments Integration" |
| chat #10 (#team-acme banter) | A | "Customer Onboarding" |

Three clusters, ten artifacts, one Acme org. **The clusters cut
across; the entity_refs unify.**

## The three navigation axes — same row, different views

```
ONE ROW (meeting #3)
   │
   ├─→ Topical axis (cluster B "Payments Integration")
   │     → "01 - Clusters/Payments Integration/" — shows meeting #3, doc #6, clip #8, ticket #9
   │
   ├─→ Entity axis (entity_refs contains acme_uuid)
   │     → "clients/acme/" — shows all 10 Acme artifacts
   │
   └─→ Temporal axis (occurred_at = 2026-06-...)
         → "meetings/2026/06/" — shows June meetings (incl. meeting #3 + others)
```

Same physical row participates in all three views. None of them
duplicate the data.

## Person + org cross-cutting

Alice (host of meeting #1) also appears in:

| Where | How |
|---|---|
| meetings #1, #2, #3 | provider metadata (host) |
| email #4 (welcome) | provider metadata (sender) |
| ticket #9 | possibly assignee or watcher |

`find_referencing(alice_uuid, ws-qube)` returns all of these — Alice's
"touchpoints" view per R9.

Filter to a specific scope:

```sql
SELECT * FROM cortex_entities
WHERE workspace_id = 'ws-qube'
  AND entity_refs @> '["alice_uuid"]'
  AND entity_refs @> '["acme_uuid"]'      -- intersection
ORDER BY occurred_at DESC;
```

→ "everything about Alice at Acme" — natural set algebra over JSONB.

## Promotion to client scope

By default the meetings don't carry `client_id = acme_uuid`. They
live at workspace root (`meetings/2026/06/`). The agent can promote
them to client scope via MCP API:

```
cortex.update_entity(
  entity_id = meeting_3_uuid,
  patch = {client_id: acme_uuid, project_id: onboarding_uuid},
)
```

After promotion:
- folder moves to `clients/acme/projects/onboarding/meetings/2026/06/`
- cluster boundary changes (re-clusters within the new scope)
- still appears in Acme's entity-axis view (via entity_refs unchanged)

## The hub `_index.md` (post-MCP)

P9 auto-generates `clients/acme/_index.md`:

```markdown
---
title: "Acme — Client Index"
type: index
auto_generated: true
last_refresh: 2026-06-30T03:00:00Z
---

# Acme — Client Index

## org hub
- [[org|Acme org entity]] (relationship: client)

## meetings — recent (last 30 days)
- [[meetings/2026/06/2026-06-15-acme-integration-review]]
- [[meetings/2026/06/2026-06-03-acme-onboarding-call]]

## emails — recent (last 30 days, top N)
- [[emails/2026/05/2026-05-12-welcome-acme]]

## docs — plans
- [[docs/2026-04-15-acme-project-plan]] (status: in progress)

## docs — contracts
- [[docs/2026-04-20-acme-signed-contract]] (status: shipped)

## clips — recent
- [[clips/2026-05-22-stripe-api-docs]]

## tickets — by status
### in progress
- [[tickets/linear/ENG-1234]] (integration bug)

## chats — channels
- [[chats/team-acme/]]
```

Same data, ergonomic surface for humans and agents.

## Why this matters

Traditional file systems force a 1:1 file ↔ folder relationship. To
get the Acme view you'd either:
- copy every file into an Acme folder (data duplication, drift)
- symlink (filesystem-specific, fragile)
- keep a spreadsheet of "Acme files" by hand (decays in weeks)

Cortex's `entity_refs[]` + GIN index gives you the unified view as a
**derived query** without copying anything. The data is canonical
once; views are infinite.

Spec §4 + §6 + §9 + R9 lock this design.
