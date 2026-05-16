# Data flow and storage

## The medallion thinking, simplified

When we worked through this architecture, we initially considered a full medallion (bronze/silver/gold) design adapted from data engineering: raw artifacts in bronze, normalized structured data in silver, curated audience-shaped content in gold. That model is correct for large-scale systems with heterogeneous consumers and significant query volume.

For Cube-Digital's scale — a handful of active projects, a small team, modest data volume — the full medallion is over-engineered. We collapsed it to a simpler shape that captures the essential layering without the operational overhead.

What we kept from medallion thinking:

- Raw artifacts are preserved separately from curated content, so we can regenerate the curated content when distillation logic changes
- Curated content is audience-shaped, not one-size-fits-all
- Access control happens through structural separation, not field-level filtering

What we dropped:

- A separate normalized silver layer with structured tables. Our data is mostly conversational and document-shaped; structuring it into tables adds complexity without enabling queries we actually run.
- A vector store. Markdown search and grep work at our scale. We will add semantic search if and when retrieval over flat files becomes a bottleneck.
- Multiple distillation tiers per audience. Two distillations (team and commercial) cover our access model.

The result is a two-layer system: raw artifacts on one side, distilled vaults on the other, with clear lineage from one to the other.

## What each storage location holds

The system uses four storage locations, each with a distinct role.

### The team vault (`cube-context-team`)

A private git repository containing distilled markdown content suitable for the execution team. Organized as one folder per active project plus shared resources.

```
cube-context-team/
  README.md
  CLAUDE.md                 # conventions for Claude Code sessions
  _registry.yaml            # public part of the project registry
  _playbooks/               # shared technical playbooks, conventions
  _people/                  # who is who, team-shareable info
  projects/
    acme-corp/
      _brief.md
      _status.md
      meetings/
      correspondence/
      chats/
      docs/
      decisions.md
      open-questions.md
      tasks/
    beta-health/
      ...
  archived/                 # finished or paused projects
```

This vault is what developers clone and open in Obsidian. It is what Claude Code reads when working on project code. The `CLAUDE.md` at the root documents conventions so any Claude Code session starting in this vault immediately understands the structure.

The vault is git-managed because git gives us versioning, blame, diffs, branching, and PRs for free. Every change to project context is reviewable. Reverting a bad distillation is one command. Tracing when a decision was recorded is one `git log`.

### The commercial vault (`cube-context-commercial`)

A private git repository containing everything the team vault has, plus commercial content, plus raw artifacts. Same project-folder structure, with additional folders per project:

```
cube-context-commercial/
  README.md
  _registry-commercial.yaml  # commercial extensions to the registry
  projects/
    acme-corp/
      _deal.md
      _strategy.md
      pricing.md
      client-relationship.md
      meetings-comm/         # full meeting summaries
      correspondence-comm/   # full email threads
      raw/                   # original artifacts
        fathom/
          2026-05-09.txt
          2026-05-09.json    # metadata
        gmail/
        hubspot/
          2026-05-09-snapshot.json
        whatsapp/
        drive-index.md       # links to Drive docs
```

The commercial vault is *not* a superset of the team vault in terms of identical files. The team vault has `meetings/2026-05-09.md` (team-distilled), and the commercial vault has `meetings-comm/2026-05-09.md` (commercially-distilled). Both are derived from the same raw transcript but contain different content.

Raw artifacts live only in the commercial vault. They are the source of truth from which both distillations are generated. If we change the distillation prompt, we can rebuild distillations from the raws.

### The state database (SQLite)

A single SQLite file maintained by the ingestion service. Tracks operational state:

- Processed artifacts (source + external ID + status + project + timestamp) for deduplication and audit
- Source polling state (last poll time, last seen ID per source) for incremental ingestion
- Distillation runs (input artifact ID, distiller version, output path, leakage scanner results) for replay and debugging

SQLite is chosen because it's a single file, easy to back up, requires no separate server, and is more than performant enough for our volume. If we ever need multi-writer concurrency or remote access, we can migrate to Postgres without changing the schema design.

### Drive (existing)

Drive remains where actual document files live — proposals, designs, presentations, client deliverables. The system does not copy Drive content into the vaults. It indexes Drive folders (one per project) and writes an index page to the team vault (`projects/acme/docs/index.md`) listing the documents with their titles, types, last-modified dates, and links back to Drive. Commercial documents in `Drive/Projects/Acme/Commercial/` are indexed only in the commercial vault.

This sidesteps the duplication question: Drive is the home for the actual file, the vault is the index that says "this exists, here's what it's about, here's the link."

## The lineage chain

Every distilled artifact in either vault has frontmatter that traces its origin:

```yaml
---
source: fathom
source_id: fathom-meeting-abc123
raw_path: cube-context-commercial/projects/acme-corp/raw/fathom/2026-05-09.txt
distiller: fathom_team
distiller_version: 1.2
distilled_at: 2026-05-09T14:30:00Z
routing_confidence: 0.95
routing_reasoning: "keyword match in meeting title: [acme]"
---
```

This metadata enables:

- Re-running distillation when the prompt improves
- Auditing how a piece of content arrived where it is
- Debugging when something looks wrong
- Verifying access decisions in retrospect

The lineage is not exposed to readers by default — it's frontmatter that Obsidian hides — but it's there when needed.

## How content flows in

The default flow for any source is:

1. **Capture**: The ingestion service receives an artifact (webhook or poll) and stores the raw form in the commercial vault under `projects/<slug>/raw/<source>/`. The raw is the source of truth and is committed immediately, before any distillation, so we never lose the original.

2. **Route**: The router looks at the artifact's metadata and consults the project registry to determine which project it belongs to. The routing decision is logged with a confidence score.

3. **Distill (commercial)**: The commercial distiller runs over the raw artifact and produces a summary that lands in the commercial vault under `projects/<slug>/<source>-comm/`.

4. **Distill (team)**: The team distiller runs over the raw artifact with stricter exclusion rules and produces a summary that *would* land in the team vault under `projects/<slug>/<source>/`.

5. **Validate**: A leakage scanner inspects the team distillation for content that should not be in the team vault. If anything is flagged, the team-vault commit is deferred to a pull request for human review. If nothing is flagged (and we're past the calibration period), the team distillation is committed directly.

6. **Commit**: Both distillations are committed to their respective vaults with descriptive commit messages. Commits include the source ID in the message so we can find them later.

7. **Index**: For periodic outputs like weekly status, a separate process aggregates recent commits and produces a project-level summary in `_status.md`.

## How content flows out

Consumers read from the vaults in three patterns:

**Direct file reading** is what humans and Claude Code do. Open the vault in an editor, navigate to a project folder, read the markdown. No special infrastructure required.

**Programmatic reading** is what other agents and dashboards do. They use a small library or MCP server that exposes "list projects," "get project brief," "search meetings by keyword," "get latest decisions for project X" as functions. Under the hood it's reading files; the abstraction is just for ergonomics.

**Identity-scoped reading** is for agents serving requests from multiple users. The agent's tool set is bound to the requesting user's identity. A developer's tools point only at the team vault. A manager's tools point at both. The boundary is enforced at the tool level — the agent literally cannot call a tool it wasn't given.

## What we do not store

A few specific exclusions worth naming:

**No personal correspondence.** Cube-Context indexes project-relevant emails, not personal mailboxes. Personal Gmail stays in personal Gmail.

**No financial transactions.** Invoicing, banking, AR/AP — all of this stays in the accounting system. The commercial vault may note that a contract was signed, but the contract itself and the payment records live elsewhere.

**No source code.** Code lives in its own git repos. The team vault may link to those repos and contain notes about architecture decisions, but the code itself is not duplicated.

**No client personal data beyond business contact info.** Client employees' work email and role are stored; their personal phone numbers, home addresses, or other PII are not.

**No employee personal data.** Internal HR matters, performance reviews, individual compensation — none of this is in Cube-Context. It lives in dedicated systems with appropriate access controls.

## How long we keep things

Retention defaults to forever for most content. Project history is valuable; we do not currently delete old projects, only archive them (move to `archived/` in the vault, mark `status: archived` in the registry).

Exceptions:

- **GDPR erasure requests**: when a client contact requests erasure, the operational playbook covers the deletion procedure across all relevant artifacts in both vaults.
- **Contract-mandated retention limits**: some clients may require deletion of meeting recordings or transcripts after a fixed period. These are tracked per project in the commercial vault and a scheduled job enforces deletion.
- **Failed ingestion artifacts**: artifacts that couldn't be routed and have been sitting in `unrouted/` for over 90 days are automatically purged.

Retention is reviewed annually as part of the operational playbook.

## Backup and disaster recovery

The vaults are git repos, so the primary backup is the remote (GitHub or self-hosted git). Every developer who has cloned has a copy. Loss of the central server is recoverable from any clone.

The SQLite state database is backed up nightly to encrypted storage. It can also be regenerated from scratch by re-processing the raw artifacts in the commercial vault, though this would take time and we'd prefer not to.

Raw artifacts in the commercial vault are themselves committed to git, so they have the same backup story as the rest. Large binary artifacts (audio files, PDFs) use git-lfs if needed.

The ingestion service itself is stateless apart from its SQLite file. Rebuilding the service from the source repo plus the SQLite file is straightforward. We do not need to back up the service host; we back up the data.

## Scale assumptions

This architecture is designed for our current scale and grows naturally to roughly:

- 30-50 active projects
- 5-10 distillations per day across all sources
- 5,000-10,000 markdown files per vault
- 1-2 GB of raw artifacts per active project per year

We will start to feel friction beyond these numbers, particularly with git performance and naive grep search. At that point we add:

- Sparse checkout or partial clones for git
- An indexer (ripgrep, or a proper search engine) for content search
- Possibly a vector store for semantic search
- Possibly an object store (R2/MinIO) for large raw artifacts, leaving only metadata in git

We do not build any of these upfront. We add them when the existing simple architecture stops being enough, and we will know that's happened because operations will slow down measurably.
