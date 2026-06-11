---
title: "Cortex Universal Silver Specification v1"
date: 2026-06-02
author: claude
tags:
  - type/doc
  - domain/cortex
  - domain/ai-platform
  - status/growing
project: [[Architecture]]
doc_type: spec
spec_version: "1.0.0-draft+rev3"
supersedes: []
deciders: [[Rareș Istoc]]
revision_history:
  - rev 1 (2026-06-02): initial spec, 7 Silver + 5 Gold types
  - rev 2 (2026-06-02): collapsed Gold into Silver, 12 unified types, Path 1 strict, _index/_log ubiquitous
  - rev 3 (2026-06-02): workspace-owner entities at root (flat), internal projects supported, OrgExtensions.relationship adds "self"
---

# Cortex Universal Silver Specification v1

> Locked entity schema, relationships, and storage contract that applies identically across all Cortex workspaces — self-hosted (GitHub-backed) and cloud (S3-backed). Same Pydantic models. Same edge types. Same MCP API. Different `SilverStorage` implementation per backend.

Companion docs:
- [[Cortex Layer Plan]] — pipeline + subsystems + connectors
- [[Architecture]] — Donna system topology
- [[Communication Platform Plan]] — agent layer that consumes this Silver

---

## 1. Purpose

A single entity schema that:

1. Works the same across every client (tech-only, business-only, solopreneur, agency).
2. Captures all knowledge accrual without bespoke per-client folder structures.
3. Lets Donna agents query rich context without hallucination.
4. Lets human technical contributors add curated knowledge without disturbing accrued Silver.
5. Survives storage backend migration (GitHub → S3 or reverse) with zero schema change.

---

## 2. Closed-vocabulary surface (locked)

Any addition requires a spec amendment + ADR.

| Surface | Count | Notes |
|---|---|---|
| Silver entity types | **12** | 7 accrued + 5 curated; unified — NO separate Gold layer |
| Edge types | **9** | forward + reverse + linter-derived |
| Storage backends | **3** | `GitHubStorage`, `S3Storage`, `LocalFSStorage` — same API |
| Extension points | **4** | typespecs, connectors, routers, eval |
| `doc_type` sub-discriminator | **16** | enumerated |
| `note_type` sub-discriminator | **5** | enumerated |
| MCP API methods | **8** | uniform across backends |

**Why no Gold layer:** lifecycle distinction (accrued vs curated) is captured via `type` + `author` field, not via layer split. One `SilverEntity` Pydantic model. Uniform edges. Uniform storage. Uniform MCP API. Curated entities (was Gold) have type-specific decay rules and higher `TYPE_AUTHORITY` weight.

---

## 3. The 12 canonical Silver entity types

### 3.1 Accrued (Donna connectors write automatically, high volume)

| type | sources | required `extensions` fields | default `author` |
|---|---|---|---|
| `meeting` | Fathom, Zoom, Meet, Teams, Whereby | `attendees: List[Attendee]`, `duration_min: int` | `donna` |
| `email` | Gmail, Outlook, IMAP | `thread_id: str`, `participants_emails: List[Participant]` | `donna` |
| `chat` | WhatsApp, Slack, Discord, Telegram, Signal | `channel: str`, `participants: List[str]` | `donna` |
| `doc` | Google Drive, Notion, SharePoint, OneDrive, Dropbox | `doc_type: <enum>`, `mime: str`, `author_email: str` | `donna` (or `human` for manual create) |
| `ticket` | Jira, Linear, GitHub Issues, Asana, ClickUp | `provider: <enum>`, `external_id: str`, `status: str` | `donna` |
| `clip` | Web Clipper, Pocket, Readwise, Raindrop | `url: str`, `why_captured: str` | `donna` or `human` |
| `note` | manual via MCP or UI | `note_type: <enum>`, `why: str` | `human` or `agent` |

### 3.2 Curated (human-written or agent-synthesized, low volume, high authority)

| type | role | scope rules | default `author` |
|---|---|---|---|
| `person` | individual (employee, client contact, consultant) | cross-client allowed; `touchpoints` derived per `(client_id, project_id)` | `human` |
| `org` | company (client, vendor, partner, internal, **self**) | cross-client; `email_domains: List[str]` enables domain-based routing; one `org` per workspace carries `relationship: self` representing the workspace owner | `human` |
| `project` | engagement with a client (replaces `Architecture.md`) | scoped to `(workspace_id, client_id)`; one per discrete engagement | `human` |
| `concept` | technical idea, pattern, framework | cross-project allowed; cited by decisions + project pages | `human` |
| `decision` | ADR | scoped to `(workspace_id, client_id, project_id)`; carries `adr_status` | `human` |

### 3.3 `doc_type` registry (closed-vocab, 16 values)

```
offer
requirements
spec
contract
handover
technical_analysis
internal_memo
presentation
signed_document
runbook
plan
integration_spec
checkpoint
architecture_note
design_note
other
```

### 3.4 `note_type` registry (closed-vocab, 5 values)

```
brainstorm
checkpoint
journal
action_item
open_question
```

---

## 4. The 9 edge types

Every edge has a canonical name + direction + semantic. Linter rejects ad-hoc edges (`UNKNOWN_EDGE_TYPE`).

| edge | from | to | semantic | maintenance |
|---|---|---|---|---|
| `entity_refs` | any Silver | curated (`person`, `org`, `concept`, `project`, `decision`) | "this entity mentions this curated entity" | manual at write |
| `sources` | any | any | "this entity was informed by these" | manual at write |
| `cross_refs` | any | any | "related context in same `(workspace, client, project)` scope" | manual or detector |
| `supersedes` | any | any (same type) | "explicit replacement chain" | manual at write |
| `parent` | any | any | "child of (e.g. clip from meeting, email from thread)" | manual at write |
| `related` | curated | curated | "cross-link between curated entities (`person↔org`, `concept↔concept`)" | manual at write |
| `contradicts` | any | any | "linter detected conflicting claims" | auto by linter |
| `applied_in` | reverse of `sources` | — | "entities that cite this one" | auto-maintained by repository |
| `superseded_by` | reverse of `supersedes` | — | "newer entity that replaced this" | auto-maintained by repository |

**Derived (not stored as edges):**
- `touchpoints` on curated `person` / `org` = reverse lookup over `entity_refs` scoped per `(client, project)`, computed lazy at read time.

---

## 5. SilverEntity Pydantic model (canonical)

```python
class SilverEntity(BaseModel):
    # Identity
    id: UUID
    type: Literal[
        # accrued
        "meeting", "email", "chat", "doc", "ticket", "clip", "note",
        # curated
        "person", "org", "project", "concept", "decision",
    ]

    # Authorship & provenance — anti-hallucination
    author: Literal["donna", "human", "agent"]
    source: str                          # e.g. fathom://meeting/<id>, gmail://thread/<id>, manual://, cortex://synth/<run>
    bronze_storage_key: Optional[str]    # raw Bronze blob pointer (accrued types only)
    content_hash: str                    # SHA256(body_md) — dedup primary key after id

    # Temporal
    occurred_at: datetime                # event time (meeting start, doc created, decision decided)
    synthesized_at: datetime             # write time

    # Scope (boundary contract)
    workspace_id: UUID
    client_id: Optional[UUID]            # boundary 1 — NEVER traverse for clustering
    project_id: Optional[UUID]           # boundary 2 — must be null if client_id is null

    # Topical
    cluster_id: Optional[UUID]           # assigned post-write, scoped to (workspace, client, project)
    embedding: List[float]               # 384-dim BGE-small default; configurable

    # Edges — forward
    entity_refs: List[UUID]              # curated entities mentioned
    sources: List[UUID]                  # what informed this entity
    cross_refs: List[UUID]               # related entities, same scope
    supersedes: List[UUID]               # explicit replacement chain (same type)
    parent: Optional[UUID]               # parent (e.g. email from thread root, clip from meeting)
    related: List[UUID]                  # curated-to-curated cross-link

    # Edges — reverse (auto-maintained by repository)
    applied_in: List[UUID]               # entities citing this
    superseded_by: Optional[UUID]        # newer entity that replaced this
    contradicts: List[UUID]              # linter-detected conflicts

    # Confidence & decay
    confidence: Literal["high", "medium", "low"]
    last_synthesized: date

    # Content
    title: str
    body_md: str                         # template-rendered (Jinja2 per type) + linted

    # Extension (per-workspace TypeSpec validates against `type` discriminator)
    extensions: Dict[str, Any]
```

No `GoldEntity` class. Lifecycle distinction captured by `type` + `author` field, plus decay rule selected per `type` in linter.

### 5.1 Type-specific extensions (Pydantic discriminated unions)

```python
# Accrued
class MeetingExtensions(BaseModel):
    attendees: List[Attendee]
    duration_min: int
    recording_url: Optional[str]
    # connector-specific: fathom_meeting_id, zoom_meeting_uuid, ...

class EmailExtensions(BaseModel):
    thread_id: str
    participants_emails: List[Participant]
    # connector-specific: gmail_message_ids, outlook_conversation_id, gmail_labels

class ChatExtensions(BaseModel):
    channel: str
    participants: List[str]
    # connector-specific: slack_channel_id, whatsapp_group_id

class DocExtensions(BaseModel):
    doc_type: Literal[<16 values above>]
    mime: str
    author_email: str
    # connector-specific: drive_file_id, notion_page_id

class TicketExtensions(BaseModel):
    provider: Literal["jira", "linear", "github", "asana", "clickup"]
    external_id: str
    status: str
    assignees: List[str]
    parent_epic_id: Optional[str]

class ClipExtensions(BaseModel):
    url: str
    why_captured: str
    captured_by: str                     # user identifier
    # connector-specific: pocket_id, readwise_id

class NoteExtensions(BaseModel):
    note_type: Literal[<5 values above>]
    why: str
    is_open_question: bool = False       # for derived view

# Curated
class PersonExtensions(BaseModel):
    full_name: str
    primary_email: Optional[str]
    role: Optional[str]
    employer_org_id: Optional[UUID]
    cross_workspace_aliases: List[str]

class OrgExtensions(BaseModel):
    legal_name: str
    email_domains: List[str]             # enables domain-based routing fallback
    industry: Optional[str]
    relationship: Literal["client", "vendor", "partner", "competitor", "internal", "self"]
    # "self" = the workspace owner's own company; exactly one org per workspace carries this

class ProjectExtensions(BaseModel):
    status: Literal["proposed", "active", "shipped", "archived"]
    target_ship_date: Optional[date]
    repo_url: Optional[str]
    deployed_url: Optional[str]
    stack: List[str]

class ConceptExtensions(BaseModel):
    aliases: List[str]
    domain: str
    maturity: Literal["seed", "growing", "evergreen"]

class DecisionExtensions(BaseModel):
    adr_status: Literal["proposed", "accepted", "superseded"]
    deciders: List[UUID]                 # person ids
    context_sources: List[UUID]          # alias for `sources` at the ADR level
    supersedes_adr: Optional[UUID]
```

---

## 6. Boundary contract (cluster scope)

```
workspace_id
 └── client_id           ← boundary 1 — NEVER traverse for clustering
      └── project_id     ← boundary 2 — null only if client_id is null
           └── cluster_id (HDBSCAN scoped here)
                └── SilverEntity (1..N)
```

**Exceptions (intentional):**
- `concept` is cross-project allowed.
- `person` is cross-client allowed; `touchpoints` are grouped per `(client_id, project_id)` so cross-client analysis stays decomposable.

---

## 7. Linter rules — R1 through R10 (locked, code-enforced)

R1. Silver immutable after first write. Only auto-maintained edges (`applied_in`, `superseded_by`, `contradicts`) may be appended post-write.

R2. Every entity carries `occurred_at` + `synthesized_at`. Both ISO 8601.

R3. Explicit supersession: newer entity carries `supersedes`; older gets `superseded_by` auto. No deletion.

R4. `cross_refs` for related entities in same `(workspace, client, project)` scope.

R5. Source hierarchy by `TYPE_AUTHORITY` numeric registry (closed, below). On conflict, highest authority wins.

R6. Gold-resynth trigger (applies to `project`, `concept`): N new sources in same cluster since `last_synthesized` → queue resynth.

R7. Contradiction = `Silver A` claims X vs `Silver B` claims ¬X → row appended to derived "Open Questions" view, NEVER auto-merged.

R8. Confidence decay: `high → medium → low` over 6 months unless reaffirmed by newer source citing it.

R9. Touchpoints on curated `person` / `org` accrue per Silver `entity_refs` reverse lookup; derived, not stored.

R10. Plan shipped (`doc.doc_type: plan` with `extensions.status: shipped`): supporting Silver immutable; downstream ADR `adr_status` → `accepted`.

### 7.1 TYPE_AUTHORITY registry (closed, numeric)

```python
TYPE_AUTHORITY = {
    "decision": 100,                  # ADR
    "doc:contract": 95,               # signed contracts
    "doc:signed_document": 95,
    "doc:offer": 80,                  # sent / agreed offers
    "project": 75,                    # Architecture / project hub
    "doc:spec": 70,
    "doc:requirements": 70,
    "concept": 65,
    "person": 60,                     # identity facts
    "org": 60,
    "meeting": 55,
    "doc:handover": 55,
    "doc:integration_spec": 55,
    "doc:runbook": 55,
    "doc:plan": 50,
    "doc:technical_analysis": 50,
    "email": 50,
    "doc:internal_memo": 45,
    "doc:architecture_note": 45,
    "doc:design_note": 45,
    "ticket": 45,
    "note:checkpoint": 40,
    "note:action_item": 40,
    "note:open_question": 40,
    "note": 35,                       # default for note without note_type
    "doc:presentation": 35,
    "chat": 30,
    "doc:other": 25,
    "clip": 20,
    "note:journal": 15,
}
```

### 7.2 Hard write-time rejects

| Rule | Reject code |
|---|---|
| `doc` missing `doc_type` | `MISSING_REQUIRED_EXTENSION` |
| `note` missing `note_type` | `MISSING_REQUIRED_EXTENSION` |
| `concept` with `sources.length < 2` | `INSUFFICIENT_EVIDENCE` |
| `decision` missing `context_sources` | `MISSING_REQUIRED_EXTENSION` |
| Duplicate `content_hash` | `DUPLICATE` — returns existing `entity_id` |
| Silver missing `entity_refs` after content scan finds named entities | `MISSING_ENTITY_REFS` (warning, flagged in derived Open Questions) |
| Body contradicting newer Silver without `supersedes` | `IMPLICIT_CONTRADICTION` |
| Ad-hoc edge name not in registry | `UNKNOWN_EDGE_TYPE` |

---

## 8. Storage backend contract

```python
class SilverStorage(Protocol):
    """Canonical Silver lives in files. Postgres is a derived index."""

    async def write(
        self,
        entity: SilverEntity,
        reverse_edges: List[ReverseEdgeUpdate],
    ) -> WriteResult:
        """
        Atomic: write entity file + update all reverse-edge targets in one transaction.
        Backend-specific atomicity:
          - GitHub: single commit with N file changes via Git Trees API
          - S3:     multipart batch + DynamoDB write-lock + idempotency token
          - LocalFS: flock + rename
        """

    async def read(self, entity_id: UUID) -> SilverEntity:
        """Path resolved from id via index (Postgres) or by walking (cold-start)."""

    async def list(self, prefix: str, since: Optional[datetime] = None) -> List[Path]:
        """List files; used for cold-start index rebuild."""

    async def delete(self, entity_id: UUID) -> None:
        """Hard delete; rare. Use `supersedes` for replacements."""

    async def history(self, entity_id: UUID) -> List[Version]:
        """git log / S3 versions / filesystem mtime."""
```

### 8.1 Three implementations (locked)

| Impl | Atomicity | History | Target use |
|---|---|---|---|
| `GitHubStorage` | single commit via Git Trees API | `git log` free | self-host clients with existing GitHub repos |
| `S3Storage` | multipart batch + DynamoDB lock + S3 versioning | S3 versions + manifest log | cloud clients, per-workspace bucket |
| `LocalFSStorage` | flock + rename | optional local git | dev preview / single-user offline |

### 8.2 Migration GitHub ↔ S3 — zero schema change

```
1. Dump source repo / bucket as tarball
2. Upload to target backend
3. Swap workspace.storage_config.backend
4. Rebuild Postgres index in background
5. Switch traffic
```

Files identical. Frontmatter identical. Cluster IDs identical (rebuild from embeddings).

---

## 9. Universal folder structure (canonical Variant 1)

Every Cortex workspace uses this structure regardless of backend (GitHub repo OR S3 bucket). Workspace owner entities (own company meetings, internal chats, handbook, internal ADRs) live **flat at root** alongside `clients/`.

```
<workspace-root>/
├── _index.md                          # workspace catalog
├── _log.md                            # workspace event log
├── org.md                              # type: org, relationship: self — workspace owner own org
│
├── meetings/                           # workspace-owner internal meetings (all-hands, sprint, retro)
│   ├── _index.md
│   ├── _log.md
│   └── YYYY/MM/<date>-<slug>.md        # type: meeting, client_id: null, project_id: null
│
├── chats/                              # workspace-owner internal chats (Slack #general, etc.)
│   ├── _index.md
│   ├── _log.md
│   └── <channel>/YYYY-MM-DD.md         # type: chat, client_id: null, project_id: null
│
├── docs/                               # workspace-owner internal docs (handbook, policies)
│   ├── _index.md                       # auto-grouped by doc_type
│   ├── _log.md
│   └── <date>-<slug>.md                # type: doc, client_id: null, project_id: null
│
├── notes/                              # workspace-owner internal notes, journals, brainstorms
│   ├── _index.md                       # auto-grouped by note_type
│   ├── _log.md
│   └── <date>-<slug>.md                # type: note, client_id: null, project_id: null
│
├── decisions/                          # workspace-internal ADRs (stack standard, billing, hiring)
│   ├── _index.md
│   ├── _log.md
│   └── ADR-WNNN-<slug>.md              # type: decision; ADR ID prefixed `W` to distinguish from client ADRs
│
├── projects/                           # workspace-internal projects (R&D, dogfood, internal tools)
│   ├── _index.md
│   ├── _log.md
│   └── <project-slug>/
│       ├── _index.md
│       ├── _log.md
│       ├── project.md                  # type: project, client_id: null, project_id: <X>
│       ├── meetings/  emails/  chats/  docs/  tickets/  clips/  notes/  decisions/
│       │   └── (each with _index.md + _log.md)
│
├── people/                             # cross-everything (employees + client contacts + consultants)
│   ├── _index.md
│   ├── _log.md
│   └── <slug>.md                       # type: person
│
├── concepts/                           # cross-project technical ideas, patterns, frameworks
│   ├── _index.md
│   ├── _log.md
│   └── <slug>.md                       # type: concept
│
├── clients/                            # external clients (real client engagements)
│   ├── _index.md
│   ├── _log.md
│   └── <client-slug>/
│       ├── _index.md
│       ├── _log.md
│       ├── org.md                      # type: org, relationship: client|vendor|partner
│       └── projects/
│           ├── _index.md
│           ├── _log.md
│           └── <project-slug>/
│               ├── _index.md           # project catalog (auto-generated, grouped by type/sub-discriminator)
│               ├── _log.md             # project event log
│               ├── project.md          # type: project, client_id: <X>, project_id: <Y>
│               ├── meetings/
│               │   ├── _index.md
│               │   ├── _log.md
│               │   └── YYYY/MM/<date>-<slug>.md     # type: meeting
│               ├── emails/
│               │   ├── _index.md
│               │   ├── _log.md
│               │   └── YYYY/MM/<date>-<slug>.md     # type: email
│               ├── chats/
│               │   ├── _index.md
│               │   ├── _log.md
│               │   └── <channel>/YYYY-MM-DD.md      # type: chat
│               ├── docs/
│               │   ├── _index.md       # auto-grouped by doc_type
│               │   ├── _log.md
│               │   └── <date>-<slug>.md              # type: doc
│               ├── tickets/
│               │   ├── _index.md
│               │   ├── _log.md
│               │   └── <provider>/<external-id>.md   # type: ticket
│               ├── clips/
│               │   ├── _index.md
│               │   ├── _log.md
│               │   └── <date>-<slug>.md              # type: clip
│               ├── notes/
│               │   ├── _index.md       # auto-grouped by note_type
│               │   ├── _log.md
│               │   └── <date>-<slug>.md              # type: note
│               └── decisions/
│                   ├── _index.md
│                   ├── _log.md
│                   └── ADR-NNNN-<slug>.md            # type: decision
│
└── _meta/
    ├── _index.md
    ├── convergence-rules.md            # R1-R10 reference
    ├── tags.md                         # closed-vocab tags
    ├── templates/                      # Jinja2 templates per type
    └── extensions/
        ├── typespecs/<workspace>/
        ├── connectors/<workspace>/
        ├── routers/<workspace>/
        └── eval/golden-questions.md
```

### 9.0 Scope cases — four valid combinations

| Scope | `client_id` | `project_id` | Example path |
|---|---|---|---|
| Workspace root (own company general) | `null` | `null` | `meetings/2026/06/2026-06-03-all-hands.md` |
| Workspace internal project | `null` | `<X>` | `projects/donna-dogfood/meetings/2026/06/...` |
| Client root (client-level context, no project yet) | `<X>` | `null` | `clients/teach-for-romania/org.md` |
| Client project (real client engagement work) | `<X>` | `<Y>` | `clients/teach-for-romania/projects/tfr-cortex-mvp/meetings/...` |

Cluster boundary remains `(workspace_id, client_id, project_id)`. All four combos generate distinct clusters.

### 9.0.1 Workspace ADR numbering convention

Workspace-internal ADRs use prefix `ADR-W` (e.g. `ADR-W001`, `ADR-W002`) to distinguish from client project ADRs (`ADR-NNNN` without `W`). This avoids ID collision when a client ADR cites a workspace ADR via `sources`.

Bronze stored separately:
```
<bronze-root>/   (separate repo or S3 bucket)
└── (raw artifacts: PDFs, audio, attachments) referenced by `bronze_storage_key`
```

Postgres index is NOT a folder — it is derived state.

### 9.1 `_index.md` auto-generated structure

Regenerated by Donna on every write. Groups children by `type` + sub-discriminator (`doc_type`, `note_type`, etc.).

Example for a project folder:

```markdown
---
title: "<Project> — Project Index"
date: <auto>
type: index
auto_generated: true
project_id: 01HX...
last_refresh: <iso>
---

# <Project> — Project Index

## project hub
- [[project|<Project> project hub]] (status: ...)

## decisions
- [[decisions/ADR-0001-<slug>]] (accepted)
- [[decisions/ADR-0002-<slug>]] (proposed)

## docs — plans
- [[docs/<date>-<plan-slug>]] (in progress)
- [[docs/<date>-<plan-slug>]] (shipped)

## docs — runbooks
- [[docs/<date>-<runbook-slug>]]

## docs — integration specs
- [[docs/<integration-name>]]

## docs — offers / contracts
- [[docs/<date>-<offer-slug>]]

## notes — checkpoints
- [[notes/<date>-<topic>]]

## notes — open questions (derived)
- [[notes/<date>-<question>]] (raised <date>)
- [[meetings/.../<meeting>#open-questions]] (from meeting)

## meetings — recent (last 30 days)
- [[meetings/YYYY/MM/<date>-<slug>]]

## emails — recent (last 30 days, top N)
- ...

## chats — channels
- [[chats/<channel>/]]

## tickets — by status
### in progress
- [[tickets/<provider>/<id>]]

## clips — last 30 days
- [[clips/<date>-<slug>]]
```

User navigates via `_index.md` instead of folder tree. Wiki-grade navigation despite flat canonical structure.

### 9.2 `_log.md` event log

Append-only, scoped to its folder. Donna writes one line per entity created / updated.

```markdown
---
title: "<Scope> — Event Log"
type: log
auto_generated: true
---

# <Scope> — Event Log

> Append-only. One line per Cortex event in this scope.

- 2026-06-15T14:32:11Z — created [[meetings/2026/06/2026-06-15-sprint-review]] (type: meeting, source: fathom://...)
- 2026-06-15T15:01:44Z — created [[docs/2026-06-15-multi-signer-plan]] (type: doc, doc_type: plan, author: human)
- 2026-06-15T15:02:10Z — auto-update [[meetings/.../2026-06-15-sprint-review]] `applied_in` += [[docs/2026-06-15-multi-signer-plan]]
```

Same at every scope (project, client, workspace).

### 9.3 Open Questions = derived view, not file

Replaces LEAN's `Open Questions.md`. The "Open questions" section in each `_index.md` is derived by query:

- entities flagged via `extensions.is_open_question: true` (any type), OR
- entities of `type: note, note_type: open_question`

No standalone `Open Questions.md` file. Cleaner — every claim has provenance.

---

## 10. Path 1 strict — write contract

### 10.1 What writes are allowed and how

| Actor | Write targets | Mechanism |
|---|---|---|
| Donna connectors (Fathom, Gmail, Drive, …) | `meetings/`, `emails/`, `chats/`, `docs/` (auto-imported), `tickets/`, `clips/` | `cortex.create_entity` via MCP, `author: donna` |
| Human technical contributor | `decisions/`, `project.md`, `concepts/`, `people/`, `clients/<X>/org.md`, `notes/`, `docs/` (manual) | Plugin Obsidian / CLI `donna` / Claude Code MCP → all hit `cortex.create_entity` with `author: human` |
| Cortex agent (sub-task) | rare: `notes/` with `note_type: action_item` post-meeting | `cortex.create_entity` with `author: agent` |
| Direct git push / file edit bypass | **BLOCKED** at pre-commit hook | reject if frontmatter invalid OR file in Donna namespace |

### 10.2 MCP API (locked)

```
cortex.create_entity(payload: SilverEntityInput) → {entity_id, path, version}
  • validates Pydantic
  • applies linter R1-R10 + TYPE_AUTHORITY conflict check
  • maintains reverse edges atomically
  • storage backend write
  • refreshes parent _index.md
  • appends to relevant _log.md
  → returns canonical path or rejects with code

cortex.update_entity(entity_id, patch: BodyOrExtensionsPatch) → updated entity
  • only `body_md` and `extensions` are mutable
  • `type, author, source, occurred_at, edges` are immutable (use supersedes for replacement)
  • re-embeds + re-clusters + refreshes derived edges

cortex.read_entity(entity_id: UUID) → SilverEntity

cortex.query(filters: QueryFilters) → List[EntitySummary]

cortex.get_context(entity_id, depth=2, edges?=[...]) → ContextGraph

cortex.eval_run(workspace_id, golden_set?) → EvalReport

cortex.linter_check(payload: SilverEntityInput) → LinterResult       # dry-run

cortex.health() → {storage_status, postgres_status, last_sync, ...}
```

Same surface for coding agents (Claude Code, Cursor), business assistant agent (Donna web UI), CLI, future integrations.

### 10.3 Pre-commit hook (git-level safety net)

```bash
#!/usr/bin/env bash
# .pre-commit-hooks/cortex-schema-check.sh
git diff --cached --name-only --diff-filter=ACM | while read file; do
  if [[ "$file" == *.md ]]; then
    if is_in_canonical_namespace "$file"; then
      donna lint "$file" || exit 1
    fi
  fi
done
```

Rejects commits with invalid frontmatter in canonical namespace. Forces writes through MCP.

### 10.4 Obsidian plugin — must-have features

| Feature | Detail |
|---|---|
| Create entity wizard | `Cmd+Shift+P → Donna: Create Entity` → dropdown type → auto-fill frontmatter per discriminator → body editor → submit via MCP |
| Type selector | 12 types + sub-discriminators (`doc_type`, `note_type`, ticket provider, etc.) |
| Entity refs autocomplete | `@<name>` → autocomplete from `people/`, `clients/`, `concepts/` → insert UUID + wikilink |
| Source / cross_ref picker | UI selector for existing entities |
| Save interceptor | `Cmd+S` on existing canonical file → diff body → MCP `update_entity({body_md: ...})` → frontmatter untouched |
| Frontmatter readonly | YAML block locked to direct edit; mutations only via form dialog |
| Inline linter | live highlight of claims without source backing (R1 anti-hallucination) |
| Query bar | `Cmd+Shift+F` → cortex query → results in right pane |
| Auto `_index.md` refresh | post-write regenerate parent `_index.md` with grouping by `doc_type` / `note_type` |
| Donna namespace lock | files in `meetings/`, `emails/`, `chats/`, `clips/`, `tickets/` → plugin blocks direct edit, redirects to MCP `update_entity` |

### 10.5 CLI `donna`

```
donna create doc --type=plan --project=docupal --title="..."
donna create note --type=checkpoint --project=docupal --title="..."
donna create decision --project=docupal --title="..." --deciders=... --adr-status=proposed
donna query "..." --workspace=qube --client=docupal --top=10
donna lint <path>                       # dry-run validate file
donna sync                              # force reindex (recovery, rare)
donna export <entity-id> --format=md
```

### 10.6 What is NOT allowed

- ❌ Free file edit in canonical namespace bypassing MCP
- ❌ Daily reconciliation sync (eliminated — Path 1 is sync-free; writes are integrated at write time)
- ❌ Mutating `type`, `author`, `source`, `occurred_at`, `edges` post-write (use `supersedes`)
- ❌ Ad-hoc folders outside the canonical tree (`Plans/`, `Runbooks/`, `Checkpoints/` etc. — absorbed via `doc_type` / `note_type`)

---

## 11. Connector mapping — current and locked roadmap

### 11.1 Currently active in Donna

| Connector | Donna integration | Maps to | Required `extensions` keys |
|---|---|---|---|
| `Fathom` | meeting recordings + transcripts + auto-summaries via Fathom API | `meeting` | `fathom_meeting_id`, `attendees_emails`, `duration_min`, `recording_url`, `fathom_summary_text` |
| `Gmail` | thread-level ingest via Gmail API (one entity per thread, NOT per message) | `email` | `gmail_thread_id`, `gmail_message_ids`, `gmail_labels`, `participants_emails: List[{name, addr, role}]` |
| `Google Drive` | file-level via Drive API + on-change webhook | `doc` | `drive_file_id`, `mime`, `owner_email`, `parent_folder_id`, `doc_type` (REQUIRED, closed-vocab) |

### 11.2 Locked roadmap (build order TBD per client demand)

| Connector | Source | Maps to | Trigger to build |
|---|---|---|---|
| `WhatsApp Business` | WA Business Cloud API | `chat` | first cloud client requesting WA |
| `Slack` | Slack API + Events | `chat` | first tech client needing it |
| `Linear` | Linear API + webhooks | `ticket` | qube-digital (we use Linear internally) |
| `Jira` | Jira Cloud REST + webhooks | `ticket` | first client with Jira |
| `GitHub Issues` | GitHub REST + webhooks | `ticket` | qube-digital OSS workflows |
| `Web Clipper` | browser extension → REST endpoint | `clip` | tech team research workflow |
| `Manual API` | MCP `cortex.create_note` | `note` | always available, no separate connector |

No other connectors without spec amendment.

---

## 12. Extension points (4, locked surface)

Companies extend WITHOUT touching the canonical schema.

```
_meta/extensions/
├── typespecs/<workspace>/<type>.py        # subclass extensions per type; validate JSON
├── connectors/<workspace>/<source>.py     # custom adapter; must emit canonical SilverEntity
├── routers/<workspace>/<rule>.py          # custom routing (e.g. label rules, [URGENT] prefix → ticket)
└── eval/<workspace>.md                    # Golden Questions, min 10
```

Workspace boot reads its `extensions/<workspace>/` directory. Each extension validated at load time.

### Example: qube-digital extensions

```
typespecs/qube-digital/doc.py
  • validates doc.extensions.{legal_jurisdiction?, signed_party?, contract_type?} (Docupal-specific)
  • validates doc.extensions.{client_engagement_id?}

connectors/qube-digital/linear.py
  • Linear adapter for our internal tracking
  • extensions.linear_team_id, linear_cycle_id, linear_state

routers/qube-digital/urgent_to_ticket.py
  • Email subject contains `[URGENT]` → also create ticket linked via `parent: <email-id>`

eval/qube-digital.md
  • Golden Questions, see §13
```

---

## 13. Golden Questions contract

Every workspace declares `extensions/eval/<workspace>.md` with min 10 questions. Each carries:

- `question_text`
- `expected_evidence: List[entity types]` — which Silver/curated entities must be findable
- `evaluator: rubric | exact | semantic`
- `min_confidence: 0.0-1.0`

Eval runs nightly. Drift = answer confidence drops > 0.1 between runs. Triggers alert.

### 13.1 qube-digital Golden Questions v1

1. **„Ce fond tehnic a stat în spatele ofertei pentru clientul X?"**
   - expected_evidence: `[meeting, doc:technical_analysis, clip]`
   - evaluator: rubric — must cite at least 1 meeting + 1 doc + 1 clip
2. „Câte ore de discuție am avut cu clientul X în ultima lună?"
   - expected_evidence: `[meeting filtered by client_id + last 30d, sum duration_min]`
   - evaluator: exact (numeric)
3. „Ce decizii s-au luat în proiectul Y săptămâna trecută?"
   - expected_evidence: `[decision created last 7d for project_id]`
   - evaluator: rubric
4. „Ce integrări active are clientul X cu sistemele externe?"
   - expected_evidence: `[project + doc:integration_spec]`
   - evaluator: rubric
5. „Care e ultima conversație unde s-a menționat tehnologia Z?"
   - expected_evidence: `[latest meeting/email/chat with entity_refs containing concept-z]`
   - evaluator: rubric
6. „Ce documente am livrat clientului X în Q1?"
   - expected_evidence: `[doc with doc_type in (offer, handover, contract) + client_id + occurred_at in Q1]`
   - evaluator: rubric
7. „Care sunt blocajele active în proiectul Y?"
   - expected_evidence: `[note:open_question + ticket with status in (blocked, paused) for project_id]`
   - evaluator: rubric
8. „Cine din echipă a vorbit ultima dată cu <persoană> de la clientul X?"
   - expected_evidence: `[meeting + email with person + group by participants → most recent]`
   - evaluator: rubric
9. „Care e diferența între propunerea inițială și ofertă finală pentru clientul X?"
   - expected_evidence: `[doc with doc_type:offer + supersedes chain → earliest vs latest]`
   - evaluator: rubric (semantic diff)
10. „Ce learnings tehnice s-au generat din proiectul Y care pot fi reaplicate?"
    - expected_evidence: `[concept cross-referenced to project_id + recent doc:technical_analysis]`
    - evaluator: rubric

---

## 14. Postgres = derived index, dispensable

Postgres holds:

| Column | Source | Rebuildable? |
|---|---|---|
| `entity_id` (UUID) | derived from `source` URI hash | yes |
| `path` (file path in storage) | direct from storage list | yes |
| `frontmatter` (JSONB) | parsed YAML | yes |
| `body_md` | file OR lazy reference | yes |
| `embedding` | model run on body_md | yes (cost ~1¢/entity) |
| `cluster_id` | HDBSCAN on embeddings | yes |
| `entity_refs` (FK array) | parsed wikilinks | yes |
| `reverse_edges` cache | derived from `sources` / `entity_refs` reverse scan | yes |

`DROP TABLE cortex_entity` → run rebuild job → iterates `storage.list('/')` + re-embeds + re-clusters. <10k entities = minutes; <1M = hours.

**Postgres = performance cache. Files = truth.**

---

## 15. ADRs baked into this spec (to be written separately)

The following are NOT open questions — they are spec decisions captured in companion ADRs:

| ADR | Decision |
|---|---|
| **ADR-001** | Silver canonical = files in `SilverStorage` backend. Postgres = derived index. Files survive Postgres loss. |
| **ADR-002** | 12 unified Silver types + 9 edges = closed vocabulary. No Gold layer split. Extension via type-discriminated `extensions: Dict[str, Any]` only. |
| **ADR-003** | Cluster boundary = `(workspace, client, project)`. Never traverse client/project. |
| **ADR-004** | Bronze stored separately from Silver (separate repo / bucket). Pointer-only reference via `bronze_storage_key`. |
| **ADR-005** | Atomic writes per backend: GitHub single-commit / S3 multipart+DynamoDB / FS flock+rename. |
| **ADR-006** | Golden Questions mandatory contract per workspace. Nightly eval. Drift threshold = 0.1 confidence drop. |
| **ADR-007** | MCP API surface uniform across backends. Implementation swap = zero schema migration. |
| **ADR-008** | Path 1 strict: all writes via MCP. No daily reconciliation sync. Plugin Obsidian + CLI + pre-commit linter as enforcement. |

---

## 16. LEAN → canonical migration mapping (qube-digital reference)

For migrating our existing LEAN rev 2 vault to this spec. Same mapping reusable for any onboarding client coming from a LEAN-style structure.

| LEAN concept | Canonical path | Type | Sub-discriminator |
|---|---|---|---|
| `Architecture.md` | `projects/<X>/project.md` | `project` | — |
| `Decisions/ADR-*.md` | `projects/<X>/decisions/` | `decision` | — |
| `Plans/<slug>.md` | `projects/<X>/docs/` | `doc` | `doc_type: plan` |
| `Runbooks/<task>.md` | `projects/<X>/docs/` | `doc` | `doc_type: runbook` |
| `Integrations/<X>.md` (project-scoped) | `projects/<X>/docs/integration-<X>.md` | `doc` | `doc_type: integration_spec` |
| `Integrations/<X>.md` (cross-project framework, e.g. LangGraph) | `concepts/<X>.md` | `concept` | — |
| `Checkpoints/<date>-<topic>.md` | `projects/<X>/notes/` | `note` | `note_type: checkpoint` |
| `Onboarding.md` | `projects/<X>/docs/onboarding.md` | `doc` | `doc_type: handover` |
| `Open Questions.md` | **NO file** — virtual view from `extensions.is_open_question: true` OR `note_type: open_question` | virtual | — |
| `Meetings/*` (project-scoped) | `projects/<X>/meetings/YYYY/MM/` | `meeting` | — |
| `Messages/email/*` | `projects/<X>/emails/YYYY/MM/` | `email` | — |
| `Messages/{whatsapp,slack,discord}/*` | `projects/<X>/chats/<channel>/` | `chat` | — |
| `Docs/<slug>.md` (client deliverables) | `projects/<X>/docs/` | `doc` | per business meaning |
| `01 - Projects/<NN>/CLAUDE.md` | **NOT canonical entity** → `_meta/agent-rules/clients/<X>/projects/<Y>.md` | — | governance |
| `05 - People & Orgs/<person>/<person>.md` | `people/<slug>.md` | `person` | — |
| `05 - People & Orgs/<org>/<org>.md` (external clients) | `clients/<slug>/org.md` | `org` | `relationship: client\|vendor\|partner` |
| `05 - People & Orgs/qube-digital/qube-digital.md` (workspace owner) | `org.md` at workspace root | `org` | `relationship: self` |
| `03 - Concepts/` | `concepts/` | `concept` | — |
| `02 - Library/Clips/` | `projects/<X>/clips/` (project-scoped) or `_meta/library/clips/` (cross-project) | `clip` | — |
| `02 - Library/{Articles,Papers,Books,Videos,Offers,Legal,Sales,Vendor Docs,Code Reviews}/` | `_meta/library/<subtype>/` or absorbed into `clip` with subtype extension | `clip` | extension subtype |
| `06 - Meetings/` (cross-project) | `meetings/` at workspace root (workspace-owner own company meetings) | `meeting` | — |
| `08 - Meta/` | `_meta/` | — | governance |
| `07 - Templates/` | `_meta/templates/` | — | governance |
| `09 - Assets/` | `_meta/assets/` | — | governance |
| `10 - Messages/` (cross-project chats) | `chats/` at workspace root (workspace-owner internal Slack/WA/Discord) | `chat` | — |
| `11 - Docs/` (org-wide handbooks) | `docs/` at workspace root | `doc` | `doc_type: internal_memo` |
| `Daily/` (daily journals) | `_meta/journals/<author>/YYYY/MM/` OR `notes/` with `note_type: journal` | `note` | `note_type: journal` |

### 16.1 Migration execution (separate plan)

Out of scope for this spec. Migration is a separate plan + separate session:

1. Walk current LEAN vault
2. For each file: determine target canonical type + sub-discriminator via table above
3. Mint UUID per entity
4. Resolve current wikilinks to new entity IDs
5. Rewrite frontmatter to canonical schema
6. Write each entity via `cortex.create_entity` (no shortcut — keeps reverse-edge invariants)
7. Generate `_index.md` + `_log.md` per folder
8. Archive old LEAN structure under `_archive/lean-rev2/` for fallback

Estimate: ~2 days work once Donna Cortex MCP + plugin exist.

---

## 17. Open Spec Questions (deferred — to resolve before v1.0.0 stable)

| Q | Question | Default if undecided |
|---|---|---|
| Q1 | Embedding model default: BGE-small (free, local, 384-dim) or OpenAI text-embedding-3-small (1536-dim, hosted)? Per-workspace override? | BGE-small + workspace override flag |
| Q2 | HDBSCAN `min_cluster_size` default: 5 or 10? | 5 (more granular clusters) |
| Q3 | Cluster rename collision: when Haiku renames two clusters to same name, what's the resolution? | Append `-<short-uuid>` suffix; both kept |
| Q4 | Cross-workspace person identity: same human at 2 of our clients = 1 `person` Gold (shared) or 2 (isolated)? | 2 (isolated); link via `cross_workspace_aliases` |
| Q5 | Spec versioning: semver. How do we evolve without breaking existing workspaces? | semver, with `spec_version` frontmatter; migration recipes per major bump |

---

## 18. Invariants — what stays the same across ALL clients

1. 12 canonical Silver types (closed)
2. 9 edge types (closed)
3. `SilverEntity` Pydantic schema (core fields immutable)
4. R1-R10 linter rules
5. `TYPE_AUTHORITY` numeric registry for conflict resolution
6. 4 extension points
7. MCP API surface (8 methods)
8. Storage abstraction (3 backends)
9. Bronze separation
10. Golden Questions contract (min 10, nightly eval)
11. Universal folder structure (Variant 1, `_index.md` + `_log.md` ubiquitous)
12. Path 1 strict (MCP-only writes)
13. **Workspace owner entities live flat at root** (`/meetings/`, `/chats/`, `/docs/`, `/notes/`, `/decisions/`, `/projects/`, `org.md`). Schema unchanged; `client_id: null` distinguishes from client work.
14. **Internal workspace projects supported** via `/projects/<X>/` at root with `client_id: null, project_id: <X>`. Mirror client project structure (same sub-folders, same MCP surface).
15. **Exactly one `org` per workspace** carries `relationship: self` — the workspace owner's own org entity at root `org.md`.
16. **Workspace-internal ADR numbering** uses prefix `ADR-W` (e.g. `ADR-W001`) to distinguish from client project ADRs (`ADR-NNNN`).

---

## 19. What varies per workspace

1. Storage backend (`GitHubStorage` | `S3Storage` | `LocalFSStorage`)
2. TypeSpec extensions (per-type extra fields)
3. Custom connectors (proprietary sources)
4. Router rules
5. Golden Questions content (not contract)
6. Embedding model (BGE-small | OpenAI | workspace pref)
7. Cluster strategy (HDBSCAN | KMeans | flat)

---

## 20. Adoption path for qube-digital (first client, dogfood)

1. Implement `SilverStorage` interface + `GitHubStorage` impl in Donna
2. Implement Pydantic `SilverEntity` + linter + `TYPE_AUTHORITY` registry
3. Wire current 3 connectors (Fathom, Gmail, Google Drive) to emit canonical `SilverEntity`
4. Wire MCP server `cortex.*` surface
5. Build Obsidian plugin (create wizard, save interceptor, autocomplete, query bar)
6. Build CLI `donna`
7. Build pre-commit hook
8. Write qube-digital Golden Questions → `extensions/eval/qube-digital.md`
9. **Migrate existing vault** from LEAN rev 2 → canonical (separate plan, ~2 days)
10. Backfill: ingest historical emails/meetings/docs (last 90 days) via Donna → Silver in new canonical structure
11. Eval baseline run
12. Iterate connector quality / Golden Questions success rate over 60-90 days

After 90 days of dogfooding → onboard second client (cloud, S3 flavor) using same code. Diff: storage config + extensions only.

---

## 21. Companion artifacts to create after this spec lands

- `01 - Projects/08 - Donna AI/Decisions/ADR-001-cortex-storage-canonical.md` through `ADR-008-path-1-strict-mcp-writes.md`
- `01 - Projects/08 - Donna AI/Plans/Cortex Vault Migration Plan.md` (qube-digital LEAN → canonical)
- `01 - Projects/08 - Donna AI/Plans/Cortex MCP Server Plan.md` (API + Pydantic + linter)
- `01 - Projects/08 - Donna AI/Plans/Cortex Obsidian Plugin Plan.md` (UI for Path 1)
- `01 - Projects/08 - Donna AI/Plans/Cortex Storage Backends Plan.md` (GitHub + S3 + LocalFS impls)
- `extensions/eval/qube-digital.md` (Golden Questions v1)

---

## 22. Edge rules — workspace ↔ clients (clarification, Rev 3)

Most rules unchanged. Concrete table for the workspace-owner case:

| Edge | Allowed? | Notes |
|---|---|---|
| `meeting (workspace)` → `entity_refs` → `person` | ✅ | curated cross-scope allowed |
| `meeting (workspace)` → `entity_refs` → `org` (any client) | ✅ | curated cross-scope allowed (e.g. workspace meeting discusses client X) |
| `decision (workspace)` ← `sources` ← `decision (client)` | ✅ | client decisions reference workspace standard ADR — knowledge inheritance |
| `meeting (workspace)` → `cross_refs` → `meeting (client)` | ❌ | `cross_refs` strictly intra-scope (same `client_id` + `project_id`) |
| `doc (workspace)` → `entity_refs` → `concept` | ✅ | cross-project concepts |
| `note (workspace)` → `parent` → `meeting (workspace)` | ✅ | intra-scope (same workspace root scope) |
| `note (workspace)` → `parent` → `meeting (client)` | ❌ | parent strictly intra-scope |

**Key value:** workspace `decisions/` (own standards: stack, billing, hiring, security policy) get cited as `sources` by client work. Standards propagate down through citations, never copy-pasted. Single source of truth at workspace scope.

## 23. Revision history (Rev 1 → Rev 2 → Rev 3)

| Rev | Date | Change |
|---|---|---|
| 1 | 2026-06-02 | Initial spec: 7 Silver + 5 Gold types, `SilverEntity` + `GoldEntity`, Mode A vault projection |
| 2 | 2026-06-02 | Collapsed Gold into Silver. 12 unified types, single `SilverEntity`, `TYPE_AUTHORITY` registry. Path 1 strict (MCP-only writes, no daily sync). `_index.md` + `_log.md` ubiquitous. Plugin Obsidian + CLI + pre-commit linter as enforcement. Extended `doc_type` to 16 values, new `note_type` registry (5 values) |
| 3 | 2026-06-02 | **Workspace owner entities at root (flat).** Added `org.md`, `meetings/`, `chats/`, `docs/`, `notes/`, `decisions/`, `projects/` at workspace root for own-company info. Added `relationship: "self"` to `OrgExtensions`. Added workspace ADR prefix `ADR-W`. Internal projects supported via `projects/<X>/` at root with `client_id: null`. Updated LEAN → canonical mapping for `06 - Meetings/`, `10 - Messages/`, `11 - Docs/`, qube-digital own org |

## See also

- [[Cortex Layer Plan]] — 9-step pipeline + 5 subsystems (pre-existing)
- [[Architecture]] — Donna system topology
- [[Communication Platform Plan]] — agent layer that consumes this Silver
- [[Open Questions]] — workspace-level unresolved items
