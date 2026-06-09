# Storage — Postgres is Derived

Spec §14 (`Postgres = derived index, dispensable`) makes one specific
claim: **files in `SilverStorage` are the truth, Postgres is a
performance cache that can be rebuilt at any time.**

## Concrete shipping shape

P0.14 lands the simplest realisation: Django `FileField` on
`CortexEntity.body`, backed by `default_storage` (which already
honours `DONNA_STORAGE_BACKEND={filesystem|s3|gcs|azure}` per
`donna/settings.py`). One file per entity at
`cortex/<workspace_id>/<type>/<entity_id>.md`. Read lazily via
`entity.load_body()`. See
[`P0.14 plan`](../06%20-%20status/04-p0.14-storage-and-embedding-refactor.md).

The `SilverStorage` Protocol below is the longer-term shape for
clients that want git-commit atomicity (GitHub repo per workspace) or
S3 versioning with DynamoDB locks. Until those land, `FileField` +
`default_storage` IS the SilverStorage.

This is a big architectural commitment. It lets workspaces migrate
backends (GitHub → S3 → LocalFS) with zero schema change, survives
Postgres loss, and gives clients full ownership of their data
(their git repo, their S3 bucket).

## The Protocol

```python
class SilverStorage(Protocol):
    """Canonical Silver lives in files. Postgres is a derived index."""

    async def write(
        self,
        entity: SilverEntity,
        reverse_edges: Iterable[ReverseEdgeUpdate],
    ) -> WriteResult: ...

    async def read(self, entity_id: UUID) -> SilverEntity: ...
    async def list(self, prefix: str, since: datetime | None = None) -> list[str]: ...
    async def delete(self, entity_id: UUID) -> None: ...
    async def history(self, entity_id: UUID) -> list[Version]: ...
```

One Protocol. Three backends. Same MCP API surface.

## Three locked implementations

| Implementation | Atomicity | History | Target use |
|---|---|---|---|
| `GitHubStorage` | single commit via Git Trees API (all files in one HTTP call) | `git log` free | Self-host clients with existing GitHub repos |
| `S3Storage` | multipart batch + DynamoDB write-lock + S3 versioning | S3 versions + manifest log | Cloud clients, per-workspace bucket |
| `LocalFSStorage` | flock + atomic rename | local git optional | Dev preview / single-user offline |

Migration GitHub ↔ S3 (spec §8.2) is a config flip:

```
1. Dump source repo / bucket as tarball
2. Upload to target backend
3. Swap workspace.storage_config.backend
4. Rebuild Postgres index in background
5. Switch traffic
```

Files identical. Frontmatter identical. Cluster ids identical (rebuild
from embeddings, which are deterministic for a given model + text).

## What lives in Postgres

```
| Column                | Source             | Rebuildable? |
|-----------------------|--------------------|--------------|
| entity_id (UUID)      | sha hash of source URI | yes      |
| path (file path)      | storage backend list | yes        |
| extensions (JSONB)    | parsed YAML frontmatter | yes     |
| body_md               | file (or lazy ref)   | yes        |
| doc_embedding (vector)| model run on body_md | yes (~1¢/entity) |
| cluster_id (UUID)     | HDBSCAN on embeddings | yes       |
| entity_refs (FK array)| parsed wikilinks     | yes        |
| reverse_edges cache   | derived from sources/entity_refs reverse scan | yes |
```

**Every column is rebuildable.** `DROP TABLE cortex_entities; rebuild`
loses nothing.

```bash
# Rebuild flow
$ donna sync --workspace=qube --rebuild
  scanning SilverStorage prefix=''
  parsed 8,432 entities in 12s
  re-embedding 8,432 entities... ~14 min
  reclustering 76 scopes... ~3 min
  index ready
```

## Universal Folder Structure §9 (Variant 1)

Every workspace uses this layout regardless of backend:

```
<workspace-root>/
├── _index.md                          workspace catalog
├── _log.md                            workspace event log
├── org.md                             type: org, relationship: self
│
├── meetings/                          workspace-owner meetings
│   ├── _index.md
│   ├── _log.md
│   └── YYYY/MM/<date>-<slug>.md
│
├── chats/, docs/, notes/, decisions/, projects/
│   (workspace-owner internal content)
│
├── people/                            cross-everything curated
├── concepts/                          cross-project curated
│
├── clients/
│   └── <client-slug>/
│       ├── _index.md
│       ├── _log.md
│       ├── org.md                     type: org, relationship: client
│       └── projects/<project-slug>/
│           ├── meetings/, emails/, chats/, docs/, tickets/, clips/, notes/, decisions/
│           └── (each with _index.md + _log.md)
│
└── _meta/                             governance + extensions
    ├── convergence-rules.md
    ├── tags.md
    ├── templates/
    └── extensions/
        ├── typespecs/<workspace>/
        ├── connectors/<workspace>/
        ├── routers/<workspace>/
        └── eval/golden-questions.md
```

Same layout, GitHub or S3 or LocalFS. Differences are commit semantics
and how `_index.md` regenerates.

## `_index.md` + `_log.md` ubiquity

Every folder ships TWO meta files:

| File | Role | Update cadence |
|---|---|---|
| `_index.md` | catalog of children, auto-grouped by sub-discriminator | regenerated on every write to the folder |
| `_log.md` | append-only event feed | one line per Cortex event |

Example `_log.md`:

```markdown
- 2026-06-03T14:32:11Z — created [[meetings/2026/06/2026-06-03-cortex-kickoff]]
  (type: meeting, source: fathom://meeting/abc)
- 2026-06-03T15:01:44Z — created [[docs/2026-06-03-multi-signer-plan]]
  (type: doc, doc_type: plan, author: human)
- 2026-06-03T15:02:10Z — auto-update [[meetings/.../cortex-kickoff]]
  `applied_in` += [[docs/2026-06-03-multi-signer-plan]]
```

This is what an Obsidian user sees when they open a folder; this is
what an agent walks when answering "what happened in onboarding last
week?".

## Why "files, not database"

| Concern | Postgres-only | Files canonical |
|---|---|---|
| Backups | dump + restore | client owns their repo / bucket |
| Schema migration | careful Django migrations | none — files are inert YAML + markdown |
| Visibility for human | only via app UI | open `_index.md` in Obsidian / VS Code |
| Disaster recovery | DBA on call | clone the repo |
| Vendor lock-in | high | zero — markdown + frontmatter |
| Multi-tenant isolation | row-level | one repo / bucket per workspace |
| Audit trail | dedicated table | `git log` for GitHub, S3 versions for S3 |

The files-canonical model has a real cost — write atomicity is harder
(see `LocalFSStorage` flock dance) and queries require Postgres index
freshness. The trade is worth it because it puts the workspace owner
fully in control of their own data.

## Current implementation state

| Piece | Status |
|---|---|
| `SilverStorage` Protocol | ✅ shipped (`storage.py`) |
| `LocalFSStorage` skeleton | ✅ shipped (flock + atomic rename) |
| `LocalFSStorage` reverse-edge patcher | TODO (P9 with MCP API) |
| `GitHubStorage` | ❌ stub only |
| `S3Storage` | ❌ stub only |
| Postgres-as-derived rebuild job | ❌ TODO — `donna sync --rebuild` |
| MCP API wiring storage write | ❌ TODO P9 |

For now, the writer still goes to Postgres only. Storage backends
plug in at P9 once the MCP API ships.

## Migration path (live system)

Phase 1 (now): writes → Postgres (as today)
Phase 2 (P9): writes → SilverStorage + Postgres (dual-write)
Phase 3: writes → SilverStorage only; Postgres rebuilt on demand
Phase 4: per-workspace storage backend pluggable

Spec §20 "Adoption path for qube-digital" calls this out as the
dogfood plan.
