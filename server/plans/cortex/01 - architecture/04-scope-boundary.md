# Scope Boundary

Spec §6 mandates a tri-key scope tuple. **Clusters NEVER traverse it.**
Acme content never bleeds into Stripe clusters even when the latent
topic looks similar.

## The tuple

```
(workspace_id, client_id, project_id)
```

| Boundary | Field | Rule |
|---|---|---|
| **1** | `client_id` | NULL = workspace-owner content. Set = client-scoped. |
| **2** | `project_id` | NULL = client-root context. Set = inside a project. |

R-INVALID_SCOPE: `project_id` MUST be NULL if `client_id` is NULL.
Linter rejects partial scopes.

## Four valid combinations

| Scope name | `client_id` | `project_id` | Example | Path prefix |
|---|---|---|---|---|
| Workspace root | NULL | NULL | qube-digital all-hands meeting | `meetings/2026/06/` |
| Workspace project | NULL | `<X>` | Donna dogfood internal project | `projects/donna-dogfood/` |
| Client root | `<X>` | NULL | Acme org page itself, first sales meeting | `clients/acme/` |
| Client project | `<X>` | `<Y>` | Acme onboarding project work | `clients/acme/projects/onboarding/` |

The folder resolver maps scope → path prefix; all four work the same
way.

## Why scope is enforced at clustering, not at query

| Concern | Where enforced |
|---|---|
| **Cluster boundary** | `HDBSCANClusterer.recluster(scope)` filters queryset to tuple. Centroids per scope. |
| **Folder placement** | `FolderResolver.canonical_path(client_slug, project_slug, …)` |
| **Pydantic schema** | `R-INVALID_SCOPE` linter check |
| **Read API** | callers pass scope to `find_in_scope(workspace, client, project)` |

A meeting carries its `client_id` + `project_id` at write time. After
that, every cluster operation, every folder lookup, every API query
respects the boundary. **No global cross-client cluster ever exists.**

## Curated exceptions (cross-scope)

Some curated types live ABOVE the scope boundary because they're
cross-cutting by nature:

| Type | Scope | Why |
|---|---|---|
| `person` | always workspace root | One Alice across all clients you do work for |
| `concept` | always workspace root | Patterns reusable across projects |
| `org` (relationship=self) | workspace root | The workspace owner — one row total |
| `org` (other relationships) | under `clients/<slug>` | client/vendor/partner orgs are scope-tied |
| `project` | per its own scope | the row IS the scope |
| `decision` | per scope, ADR-W prefix workspace-internal | `ADR-W001` distinct from `ADR-0001` to avoid collision |

Spec §6 calls these out explicitly. The folder resolver routes them to
workspace root; clustering doesn't apply (curated rows aren't
clustered — too low volume).

## ADR numbering: `ADR-W` vs `ADR-NNNN`

| Scope | Prefix | Example |
|---|---|---|
| Workspace-internal decision | `ADR-W` | `ADR-W001-use-postgres-plus-pgvector` |
| Client project decision | `ADR-` | `ADR-0001-event-sourcing` |

Reason: client ADRs may `sources` a workspace ADR ("we follow company
stack standard W007"). Distinct prefixes prevent id collision when
mixed.

## Concrete walk: Acme onboarding meeting

```
DeliveryPackage(
    provider = "fathom",
    provider_item_type = "meeting",
    workspace_id = ws-qube,
    metadata = {host: alice@acme.com, ...},
)
```

CortexWriter sees `acme.com` in the host email. The resolver matches
or spawns the `org` row with `email_domains=["acme.com"]`.

But the meeting itself — at the moment of write — has NO `client_id`
because the writer doesn't auto-link mention → scope (would be
ambiguous: Bob is from example.com too).

**Resolution policy (current):** writer leaves `client_id = NULL`.
The agent (Path 1 strict, P9) is responsible for promoting the
meeting to scope when the human says "yes, this Acme meeting is part
of the Onboarding project".

Per spec §6: a meeting without scope still works. It surfaces in:

- workspace-root meetings folder (`meetings/2026/06/`)
- entity-axis derived view at `clients/acme/_index.md` (via `entity_refs`)

Promotion to client scope = a deliberate human/agent decision, never
implicit.

## How clustering respects scope

```python
class HDBSCANClusterer:
    def _scoped_queryset(self, scope):
        qs = CortexEntity.objects.filter(workspace_id=scope.workspace_id)
        qs = qs.filter(client_id=scope.client_id) if scope.client_id else qs.filter(client_id__isnull=True)
        qs = qs.filter(project_id=scope.project_id) if scope.project_id else qs.filter(project_id__isnull=True)
        return qs
```

Centroids are computed scope-by-scope; the online `assign` only sees
centroids in the calling scope. Cluster ids are stable UUIDs derived
via `uuid5(namespace=scope-uuid, label_int)` so identity persists
across reclusters.

## How the read API respects scope

The repository helper:

```python
def find_in_scope(self, workspace_id, client_id=None, project_id=None):
    qs = CortexEntity.objects.filter(workspace_id=workspace_id)
    qs = qs.filter(client_id=client_id) if client_id else qs.filter(client_id__isnull=True)
    if project_id is not None:
        qs = qs.filter(project_id=project_id)
    elif client_id is None:
        qs = qs.filter(project_id__isnull=True)
    return list(qs)
```

The MCP API (P9) accepts the tuple as part of every filter; agents
pick which scope to navigate.

## Cross-scope queries (allowed)

Some edges legitimately cross scope:

| Edge | Cross-scope? | Notes |
|---|---|---|
| `entity_refs` → curated row | ✅ | meeting (workspace) mentions org (client) |
| `sources` → workspace decision | ✅ | client doc cites workspace ADR |
| `cross_refs` | ❌ | strictly intra-scope (R4) |
| `parent` | ❌ | parent must share scope |

The linter R4 enforces `cross_refs` scope. Other edges are checked at
the read/render layer.

## Why this matters

Without scope:
- Cluster "Customer Onboarding" merges Acme + Stripe + WaW content
- Agent answering "what's happening with Acme onboarding?" returns Stripe stuff
- Wrong answers ship → trust collapses

With scope:
- One "Customer Onboarding" cluster PER `(workspace, client, project)`
- Agent stays inside scope; cross-scope visible only via curated
  `person`/`org` entity-axis views
- Right answers ship → trust compounds
