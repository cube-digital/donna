# Cube-Context

The unified project context layer for Cube-Digital. One home for every project's history, accessible to both the execution team and management with appropriate access boundaries, designed to make humans and agents dramatically more productive on client work.

## What this is

Cube-Context is an internal platform that pulls project-relevant context out of the tools where it lives today — Fathom, Gmail, HubSpot, WhatsApp, Discord, Drive — and assembles it into per-project knowledge spaces that both the team and our AI agents can consume.

It is **not** a replacement for any of those tools. HubSpot stays HubSpot. Gmail stays Gmail. Cube-Context is a curated, project-shaped view of what matters across all of them.

## Why this exists

Cube-Digital builds AI-driven software for clients across HealthTech, manufacturing, and edge-AI verticals. Project context today is fragmented across six or more tools. Answering a question like *"what did we decide about the Acme integration last month?"* requires opening Fathom, searching Gmail, checking HubSpot, and asking three teammates. This costs hours per week per person, slows onboarding of new tech hires, and degrades the quality of agent assistance because Claude Code and similar tools don't have access to the full picture.

Cube-Context fixes this by giving every active project a single canonical location — a folder — where the relevant context from every source has been distilled, organized, and made queryable by both humans and agents.

## The three primary use cases

1. **Developer productivity.** A developer working on a client project opens Claude Code in the project's folder and immediately has the full technical context: meeting decisions, client constraints, architecture notes, open questions. They plan tasks, write code, and ask questions that reference the project as if Claude were a long-standing teammate.

2. **Management visibility.** A co-founder or manager asks an agent (or just reads the project folder) *"what's happening with Acme this week?"* and gets a coherent answer pulled from the latest meetings, emails, and updates — without sitting through the calls themselves.

3. **Team-wide chat surface.** Anyone on the team opens Donna — a chat application installed on every laptop — and asks the same kind of question without needing to know what Obsidian or Claude Code are. Donna's agent reads from whichever vault the asker's identity permits, streams its answer back, and exposes the same staging-and-approval pattern for any external writes the agent proposes.

## How to use this documentation

If you are new to the project, read in order:

1. [Vision and principles](docs/00-vision-and-principles.md) — what we're building and why
2. [Architecture overview](docs/01-architecture-overview.md) — the system at a glance
3. [Access and trust model](docs/02-access-and-trust-model.md) — who sees what, and how it's enforced
4. [Data flow and storage](docs/03-data-flow-and-storage.md) — where artifacts live and why
5. [Ingestion pipeline](docs/04-ingestion-pipeline.md) — how sources become project context
6. [Agent and context layer](docs/05-agent-and-context-layer.md) — how agents consume the context
7. [Implementation plan](docs/06-implementation-plan.md) — the build sequence
8. [Operational playbook](docs/07-operational-playbook.md) — running the system day-to-day
9. [Decisions and tradeoffs](docs/08-decisions-and-tradeoffs.md) — the alternatives we rejected and why

If you are a developer joining the project, start with the architecture overview and then jump to the ingestion pipeline and implementation plan.

If you are management, read vision and principles, then access and trust model, then operational playbook.

## Status

This document set describes the **target architecture** and the **initial implementation plan**. The system is being built incrementally. Refer to the implementation plan for the current build state.

## Maintainers

- Architecture and technical direction: Rares
- Access policy and operational ownership: Andreea
- Day-to-day operation of the registry: see the operational playbook
