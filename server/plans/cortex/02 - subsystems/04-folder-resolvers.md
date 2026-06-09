# Subsystem 4 — Folder Resolvers

**Concern:** every entity row needs ONE canonical filesystem location.
The other two axes (entity, temporal) are derived query views.

## Plain English

Every Cortex row lives in exactly one folder. That folder is its
**canonical home** — what an Obsidian user sees when they open the
file tree, what `_index.md` lists, what `_log.md` appends to.

But the same row participates in three different "lenses":

| Lens | Question it answers | How it works |
|---|---|---|
| **Topical / Temporal** | "what meetings in June?" | canonical filing — the folder IS the answer |
| **Entity** | "show me everything about Acme" | derived query — scan `entity_refs` |
| **Temporal** (date-keyed) | "what happened on June 3?" | derived query — scan `occurred_at` |

The folder resolver decides where the canonical home goes. It's NOT
deciding what other queries can find the row.

## The Protocol

```python
class FolderResolver(Protocol):
    def canonical_path(
        self,
        *,
        type: str,
        occurred_at: datetime | str | None,
        extensions: dict,
        client_slug: str | None,
        project_slug: str | None,
    ) -> str: ...
```

Returns a folder path **relative to workspace root**. The writer
combines it with `slug` to get the file path.

## The seven resolvers

| Resolver | Used by | Path shape |
|---|---|---|
| `TemporalFolderResolver` | meeting, email | `<scope>/<bucket>/YYYY/MM` |
| `ChatFolderResolver` | chat | `<scope>/chats/<channel>` |
| `TicketFolderResolver` | ticket | `<scope>/tickets/<provider>` |
| `FlatFolderResolver` | doc, clip, note | `<scope>/<bucket>` |
| `PersonFolderResolver` | person | `people` (workspace root) |
| `ConceptFolderResolver` | concept | `concepts` (workspace root) |
| `OrgFolderResolver` | org | workspace root OR `clients/<slug>` |
| `ProjectFolderResolver` | project | `<scope>` (project.md at scope root) |
| `DecisionFolderResolver` | decision | `<scope>/decisions` |

## Scope prefix

```python
def _scope_prefix(client_slug, project_slug):
    if client_slug and project_slug:
        return f"clients/{client_slug}/projects/{project_slug}"
    if client_slug:
        return f"clients/{client_slug}"
    if project_slug:
        return f"projects/{project_slug}"
    return ""
```

Four scope cases handled uniformly. Workspace-owner content lives at
root; client work lives under `clients/<slug>/`.

## Concrete examples

### Meeting for Acme onboarding project

```
client_slug = "acme"
project_slug = "onboarding"
occurred_at = 2026-06-03
type = "meeting"
→ TemporalFolderResolver(bucket="meetings")
→ "clients/acme/projects/onboarding/meetings/2026/06"
```

### Workspace-owner all-hands meeting

```
client_slug = None
project_slug = None
occurred_at = 2026-06-03
type = "meeting"
→ "meetings/2026/06"     (workspace root)
```

### Person row (Alice)

```
slug = "alice-smith"
type = "person"
→ PersonFolderResolver
→ "people"               (always workspace root, cross-client)
```

### Acme org row

```
extensions.relationship = "client"
client_slug = "acme"
type = "org"
→ OrgFolderResolver
→ "clients/acme"
```

### qube-digital own org

```
extensions.relationship = "self"
type = "org"
→ "" (workspace root → org.md)
```

### Chat thread #incidents in Acme

```
extensions.channel = "incidents"
client_slug = "acme"
project_slug = "onboarding"
type = "chat"
→ ChatFolderResolver
→ "clients/acme/projects/onboarding/chats/incidents"
```

### Linear ticket ENG-1234 for workspace internal R&D

```
extensions.provider = "linear"
project_slug = "donna-dogfood"  (workspace project, no client)
type = "ticket"
→ TicketFolderResolver
→ "projects/donna-dogfood/tickets/linear"
```

## Three axes — same row, different lenses

```
            cortex_entities (ONE table)
                     │
   ┌─────────────────┼─────────────────┐
   │                 │                 │
   ▼                 ▼                 ▼
Topical/         Entity             Temporal
Temporal         (derived)          (derived)
canonical
                 WHERE              WHERE
WHERE            entity_refs @>     occurred_at
parent_path =    [<entity_uuid>]    >= ?
?
                                    ORDER BY
                                    occurred_at DESC

Example queries:

"meetings/2026/06"          → all June meetings (temporal axis,
                              canonical filing)

"clients/acme"              → all Acme content (entity axis,
                              derived view: find_referencing(acme_id))

"meetings in last 7 days"   → time slice across canonical fillings
                              (derived view: filter by occurred_at)
```

## Derived entity-axis view

```python
class DerivedNamespaceView:
    def list_entity_namespace(self, entity_id, workspace_id):
        return self._repo.find_referencing(entity_id, workspace_id)
```

`find_referencing(acme_id, ws_id)` uses the GIN index on `entity_refs`:

```sql
SELECT * FROM cortex_entities
WHERE workspace_id = ? AND entity_refs @> '["<acme-uuid>"]'
ORDER BY occurred_at DESC;
```

Same response shape as topical / temporal queries → the agent uses a
uniform navigation interface regardless of axis. Spec §4 + §9 lock
this surface.

## The `_index.md` regeneration

Each folder ships an `_index.md` that lists its children. Per spec §9.1,
it's regenerated on every write to the folder. Grouped by type +
sub-discriminator:

```markdown
# Acme Onboarding — Project Index

## project hub
- [[project|Acme Onboarding hub]] (status: active)

## decisions
- [[decisions/ADR-0001-event-sourcing]] (accepted)

## docs — plans
- [[docs/2026-06-03-multi-signer-plan]] (status: in progress)

## docs — runbooks
- [[docs/2026-05-30-onboarding-runbook]]

## meetings — recent (last 30 days)
- [[meetings/2026/06/2026-06-03-cortex-kickoff]]

## tickets — by status
### in progress
- [[tickets/linear/ENG-1234]]
```

For now this regeneration is a TODO (P9 with MCP API). The data to
build it lives in `cortex_entities` already.

## Why "one canonical path" matters

If a row had two paths, agents would never know which is the "real"
one. Two copies of the same row would diverge. Edits to one wouldn't
propagate to the other.

Cortex picks ONE path per row (the topical or temporal lens). Other
queries derive from `entity_refs`, `occurred_at`, `cluster_id`, etc.
without filesystem duplication.

## Path 1 strict

Spec §10 enforces: **all writes must go through MCP API**, never direct
file edit. The plugin / CLI / pre-commit hook block stray edits in
the canonical namespace. This ensures the folder structure stays
spec-conforming and `_index.md` stays in sync.
