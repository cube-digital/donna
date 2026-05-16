# Vision and principles

## The problem we're solving

Cube-Digital is a small, high-trust team building AI-driven software for clients across multiple verticals. Project context — the accumulated decisions, constraints, conversations, and history that defines what each project actually is — lives scattered across the tools we use day-to-day. Fathom holds the meeting transcripts. Gmail holds the threads with clients. HubSpot holds the commercial relationship. Drive holds the artifacts. WhatsApp and Discord hold the informal side-channels where a lot of real decisions get made.

This fragmentation creates several costs that compound as the team and client base grow:

The first cost is **time spent reassembling context**. When a developer picks up a project they haven't touched in two weeks, or a manager prepares for a client call, they spend the first thirty minutes of every session reconstructing what's happening. This is repeated work that produces no client value.

The second cost is **degraded agent assistance**. Tools like Claude Code are dramatically more useful when they can see project context. Without it, they produce generic code suggestions that miss client-specific constraints, conventions, and prior decisions. The promise of AI-assisted engineering is bottlenecked on whether the AI has the context.

The third cost is **knowledge that lives only in heads**. When a team member is unavailable, in another meeting, or out of the company, project knowledge they hold becomes inaccessible. New hires take weeks longer to ramp up because there's no readable record of "how this project actually works." This caps our ability to scale the team.

The fourth cost is **management blindness when not in the room**. Co-founders cannot attend every client call. Today the only way to know what was discussed is to ask a team member or watch a recording. Both are expensive. Both happen unreliably.

## What we're building

Cube-Context is a system that ingests artifacts from each of our existing tools, distills them into project-shaped context, and makes that context available to humans and agents through interfaces appropriate to each audience.

The design has three properties that everything else flows from:

**Project-shaped, not source-shaped.** The primary organizing key is the project, not the source tool. When you want to know about Acme Corp, you go to the Acme Corp folder, not to Gmail-filtered-by-Acme plus HubSpot-filtered-by-Acme plus Fathom-filtered-by-Acme. The cross-source join happens at ingestion time, once, so every consumer benefits.

**Curated, not raw.** Raw transcripts and email threads are signal-dense but noise-heavy. The system runs each artifact through a distillation step that extracts the durable, technical, decision-relevant content into a clean form. This is the difference between a folder of 200 unreadable transcripts and a folder of 200 useful meeting summaries.

**Trust-aware.** Project context contains both shareable execution information (technical decisions, scope, action items) and sensitive commercial information (deal terms, pricing, strategic positioning). The system separates these into two access tiers and never mixes them.

## Who this is for

Cube-Context serves two audiences with overlapping needs:

The **execution team** — developers, AI engineers, designers — uses Cube-Context as the technical brain for projects they're working on. They primarily consume context through Claude Code and Obsidian on a local clone of the team vault, planning tasks and writing code with the full project history available. They have access to the technical view of every active project. They also have Donna, the team chat application, for cross-project questions that don't fit naturally into a single project folder.

The **management team** — co-founders and anyone in a commercial role — uses Cube-Context to stay informed across all projects without attending every meeting. Their primary interface is **Donna**, a chat application that lets them ask questions across projects and receive answers drawn from whichever vault their identity permits. Some management users will also work directly in Obsidian or Claude Code against the commercial vault when they want full power-user access. They have access to both the technical and commercial views.

The system is deliberately designed so the two groups can help each other rather than work in silos. A developer can read the project brief and understand the client relationship at a high level. A manager can read the technical summary of a meeting and engage substantively with engineering tradeoffs. What management has that the execution team does not is the commercial wrapper around the project — deal economics, pricing, strategic positioning — and that is the only axis of separation.

## What this is not

It's worth being precise about what Cube-Context deliberately is not, because the temptation to scope-creep is strong:

It is not a replacement for HubSpot, Gmail, Drive, or any other source. Those tools remain the homes of their respective data. Cube-Context indexes and distills; it does not re-platform.

It is not a CRM, a project management system, or a ticketing tool. Linear remains where tasks live. The system can propose Linear tasks based on meeting notes, but it does not replace Linear.

It is not a real-time system. Distillation happens on a schedule or per-event. The context in the system lags reality by minutes to hours. For live status, the agent layer can query source systems directly via MCP, but the curated context is intentionally not real-time.

It is not a system for personal or non-project content. Personal emails, internal HR matters, individual notes — these stay where they are. Cube-Context is for client project context only.

It is not a productized SaaS offering, at least not initially. It is internal infrastructure for Cube-Digital. Some pieces may eventually be productized, but the v1 design optimizes for our team's needs, not generality.

## Design principles

A small set of principles guides every design decision in this document set. When in doubt, refer to these.

**Project is the unit.** Everything organizes around projects. Sources are inputs; projects are outputs. If something doesn't have a clear project home, it probably doesn't belong in the system.

**Distill aggressively, store thoroughly.** Raw artifacts are kept for replay and audit but are not the consumption surface. Distilled summaries are the consumption surface. We accept information loss in distillation because what we lose is mostly noise.

**Access via architecture, not policy.** Sensitive data does not live in spaces where it can be accidentally exposed. We do not rely on agents "knowing not to mention" commercial details to non-management users. We rely on those users literally not having access to the data in the first place.

**One canonical home, multiple views.** A piece of context has one source of truth. Different audiences may consume it through different surfaces — Obsidian, Cowork, a chat agent — but those are views over the same underlying truth, generated automatically. We do not maintain parallel hand-edited copies.

**Manual where automation is unreliable; automated where automation is reliable.** WhatsApp ingestion is manual because automated WhatsApp scraping is fragile. Fathom distillation is automated because the input is consistent. We make these choices source by source, not all-or-nothing.

**Ship the minimum that gives signal, expand on evidence.** The v1 build is deliberately scoped to two sources and one project. We expand only when the existing slice has proven useful. This is the anti-perfectionist posture and it is intentional.

**Every automated decision is reviewable.** Git is the substrate for project content. Every distillation, every routing decision, every change to a project's context is a commit. When something goes wrong, we can see what happened and why. When something needs to be undone, we can revert it.

## What success looks like

Six months after launch, Cube-Context is successful if:

- Every active client project has a maintained folder in the system that is the team's first stop when picking up that project
- New tech hires are productive on existing projects in days rather than weeks
- Management can answer "what's the status of X" within minutes without interrupting the execution team
- Developers using Claude Code in project folders produce code that aligns with client-specific constraints without manual context-setting
- Nothing has leaked from the commercial space into the team space, and no client has raised concerns about how their data is handled

Failure modes to watch for:

- The folders exist but are stale because ingestion or distillation broke and nobody noticed
- The team works around the system because it's faster to just ask each other
- The registry of projects drifts and routing accuracy degrades
- Sensitive content shows up in the team space despite the distiller's filtering
- The system becomes load-bearing and a single person owns all the operational knowledge

Each of these has a mitigation strategy in the operational playbook.
