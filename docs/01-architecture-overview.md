# Architecture overview

## The system in one paragraph

Cube-Context is a Django application that listens to webhooks and polls APIs from six source systems, normalizes the incoming artifacts, looks up the right project in a hand-maintained registry, distills each artifact through Claude (with separate prompts for team-shareable and commercial outputs), and commits the results to two git-managed markdown vaults — one for the execution team, one for management with commercial details. The same Django project also serves Donna, a chat surface for the whole team. The team vault is consumed by developers through Obsidian and Claude Code on a local clone of the vault, and by everyone else through Donna's Electron desktop client, which keeps that local clone in sync via background `git pull`. The commercial vault is consumed through the same Donna client for users whose identity grants commercial access, or directly via Obsidian and Claude Code. Agents access both vaults through identity-aware tools that scope retrieval to whatever the requesting user is permitted to see.

## The five layers

The architecture has five logical layers. Each has a distinct responsibility and a clear boundary with the others.

### Sources

The six external systems where work actually happens and where context originates:

- **Fathom** — meeting recordings and transcripts. The highest-value source because meetings are where decisions get made.
- **Gmail** — client correspondence, vendor communication, project-relevant threads.
- **HubSpot** — commercial relationship state: deals, contacts, pipeline stage, value. Commercial-tier only.
- **WhatsApp** — informal client communication. High signal but operationally difficult to ingest automatically.
- **Discord** — internal team discussion, organized by channel per project.
- **Drive** — generated artifacts: proposals, briefs, designs, deliverables. Indexed but mostly not duplicated.

These tools remain authoritative for their own data. Cube-Context never replaces them; it only reads from them.

### Ingestion

A single Python service that receives artifacts from the sources (via webhooks where possible, polling where necessary), normalizes them into a common format, routes them to a project, and prepares them for distillation. The ingestion service is the only component that talks to source APIs.

### Distillation

A small number of LLM-powered transformers that turn raw artifacts into curated markdown. Each distiller has at minimum two prompts: one for the team-shareable summary (stripped of commercial content) and one for the commercial summary (full content, restricted access). Distillation is where the cross-source noise reduction happens and where the access boundary is enforced through prompt engineering and validation.

### Storage

Two git-managed markdown vaults plus an object/file store for raw artifacts. The team vault contains distilled, technical, broadly-shareable content. The commercial vault contains everything plus the commercial details that the team vault excludes. A small SQLite database tracks ingestion state, dedup, and routing decisions. Raw source artifacts (full transcripts, original emails) live in the commercial vault under a `raw/` folder, never in the team vault.

### Consumption

Humans and agents read from the vaults through three first-class surfaces. Developers use **Obsidian** for browsing and **Claude Code** for active work, both against a local clone of the team vault. The whole team and management use **Donna** — a Django chat application delivered through an Electron desktop client. Donna lets users ask questions across projects, paste ad-hoc context into a conversation, and trigger agents that read from whichever vault the asker's identity permits. The Electron client keeps a local clone of the team vault (and the commercial vault for users with that access) synced via background `git pull`, so the same files Donna reads on the server are sitting on disk for Obsidian and Claude Code in parallel. AI agents (Claude Code in the developer flow, Donna's per-user agent in chat, future scheduled bots) access content through tools that respect the requesting identity's access tier. Writes back to source systems (creating Linear tasks, drafting emails) go through a staging area where humans approve before anything fires externally.

## How the layers connect

The flow for a typical incoming artifact:

A Fathom transcript arrives via email to the ingestion service's webhook endpoint. The service parses it into a normalized artifact, looks up the project based on the meeting title and attendees, and confirms it matches "Acme Corp." It writes the raw transcript to the commercial vault under `projects/acme-corp/raw/fathom/2026-05-09.txt`. It calls the team distiller, which uses Claude with a carefully-crafted prompt to produce a technical summary that excludes any commercial content. The team-safe summary is committed to the team vault at `projects/acme-corp/meetings/2026-05-09.md`. It calls the commercial distiller, which produces a full summary including commercial nuance, and commits that to the commercial vault at `projects/acme-corp/meetings-comm/2026-05-09.md`. A leakage scanner runs over the team summary to check for accidental inclusion of monetary figures or other red flags. If anything is flagged, the commit is held in a pull request for human review rather than auto-merged.

The next morning, a developer opens Claude Code in the team vault, navigates to the Acme project folder, and asks "what was decided in yesterday's meeting?" Claude Code reads the meeting summary from `projects/acme-corp/meetings/2026-05-09.md` and answers. Later that day, a co-founder asks an agent connected to both vaults the same question and gets a richer answer that includes the commercial context the developer didn't see.

## The two-vault model

The most important architectural decision is the split into two vaults. This is the answer to the question of how to share project context broadly while keeping commercial data restricted.

The **team vault** (`cube-context-team`) contains technical and execution context for every active project. Every member of the execution team has read access. Anyone in management has read access. The content is deliberately stripped of commercial details so it can be broadly shared without risk. This is where developers and agents working on execution operate.

The **commercial vault** (`cube-context-commercial`) contains everything: full raw artifacts, distilled commercial summaries, deal information, pricing notes, strategic context. Only co-founders and management have access. This is where the complete picture of each project lives.

The two vaults share a project structure but contain different content. The team vault's `projects/acme/meetings/2026-05-09.md` and the commercial vault's `projects/acme/meetings-comm/2026-05-09.md` are derived from the same source transcript but contain different distillations. Neither is a copy of the other.

This split is enforced at the repository level. The team vault is a private git repository whose access list does not include commercial details. The commercial vault is a separate private git repository whose access list is much smaller. We do not rely on application-level filtering to enforce access; the data simply lives in different places with different permissions.

## What the agent layer does

The agent layer is the consumption surface for AI-driven workflows. It is deliberately not the same thing as the storage layer.

When a developer runs Claude Code in their local clone of the team vault, they are using the agent layer in its simplest form: Claude Code reads markdown files from disk, including any `CLAUDE.md` convention files that explain how the vault is organized. There is no special infrastructure; it's just files and an off-the-shelf agent.

When a manager asks a chat assistant "what's happening with Acme?", that assistant is configured with tools that read from one or both vaults depending on who is asking. The assistant does not have a hardcoded view of who has access to what; it asks the identity layer at query time and gets a tool set scoped to that user's permissions. A developer asking the same question gets a tool set that can only read the team vault. A manager gets a tool set that can read both.

For more complex agentic workflows — drafting a Linear task from a meeting note, preparing a client follow-up email, generating a weekly project status — the agent reads context (from the appropriate vault) and writes a *proposal* to a staging folder. A human reviews the proposal and either promotes it (triggering the external action) or rejects it. Agents never write directly to Linear, Gmail, HubSpot, or any other external system without a human approval gate. This is the audit and safety boundary.

## What we deliberately do not build

A few things that someone might expect in this architecture but that are intentionally absent:

- **No central database.** The vaults are git repos. State is a SQLite file. Everything is text and files. This is sufficient for our scale and is dramatically easier to operate, back up, and reason about than a database-centric architecture.
- **No vector store, initially.** Search and retrieval work fine over markdown files at our scale. If volume grows to a point where semantic search becomes essential, we will add Qdrant or similar. We do not pre-build this.
- **No tier-aware retrieval inside the agent.** Access tiering is at the repository level, not the query level. An agent either has access to a vault or it does not. We never give an agent "full access with output filtering" because that is the dominant failure mode for unified-context systems.
- **No multi-tenant infrastructure.** This is for Cube-Digital. If we ever productize, that's a separate effort with its own architecture.
- **No real-time *ingestion*.** Distillation happens on a schedule or per-event with minutes-to-hours latency. The system trades ingestion latency for reliability and reviewability. Donna's chat surface streams agent responses in real time, but the underlying vault data it reads is not real-time.

## Mental model for the rest of the documentation

The remaining documents zoom in on each layer. The access and trust model document covers the two-vault split in operational detail. The data flow and storage document describes what each vault contains and how raw and distilled content relate. The ingestion pipeline document is the operational core: how each source maps to a project. The agent and context layer document explains how memory, retrieval, and writes interact. The implementation plan document sequences the build. The operational playbook covers running the system. The decisions log captures alternatives considered and rejected.
