# Agent and context layer

## Why this is a separate concern

The storage layer (the vaults) and the consumption layer (agents and humans reading) are conceptually distinct. Conflating them is one of the most common architectural mistakes in AI systems.

Storage is about what data exists and where. Consumption is about what an agent sees, when, and how. The same data can be consumed in radically different ways depending on the agent's identity, the task, and the kind of memory the agent has.

This document explains how agents consume Cube-Context, with particular attention to the distinction between **context** (what the agent retrieves to answer the current question) and **memory** (what the agent carries across questions).

## Context vs memory: the distinction

When someone says "give the agent memory," they usually mean two different things at once. Disentangling them clarifies the design.

**Context** is what the agent retrieves *for this query*. It's stateless from the agent's perspective: every query starts fresh, retrieval happens, the agent answers, and nothing is carried forward. The project's meeting summaries, the brief, the decision log — these are context. Each is fetched anew for each question that needs them.

**Memory** is what the agent carries *across queries*. It's stateful. The fact that you asked about Acme last Tuesday, the conversation history of a multi-turn task, the agent's learned model of how you like answers structured — these are memory. They persist across sessions and accumulate.

The two systems have different lifecycles, different storage, different access concerns, and different failure modes. Designing them as one thing produces either an amnesiac agent (no memory at all) or a creepy one (everything is remembered forever, with no clear retention model).

## The context layer

Context retrieval in Cube-Context happens through three paths, with the agent preferring the cheapest reliable path for any given question.

The **fastest path** is reading curated markdown from the appropriate vault directly. This is what Claude Code does when run in a project folder: it reads `_brief.md`, `meetings/`, `decisions.md`, and any other files relevant to the user's question. No special infrastructure is involved; markdown is read by the agent's standard file tools. This is the right path for the dominant use case — a developer working on a specific project who has the full vault already on their machine.

The **structured path** is querying a small set of MCP tools that expose the vault as functions: `list_projects`, `get_project_brief(slug)`, `search_meetings(slug, query)`, `list_open_questions(slug)`. These exist for agents that don't have local filesystem access (a chat agent serving requests over the web, for example) or that need to query across projects. The tools are thin wrappers over the same markdown files; they just provide an ergonomic interface.

The **freshness path** is calling source-system MCPs directly when the curated context is stale or insufficient. If a developer asks "is the Acme deal still active?" and the curated commercial brief is two days old, the agent can call the HubSpot MCP to check current deal status. This path is only available to agents whose identity allows access to the source — a manager's agent can call HubSpot, a developer's agent cannot.

The agent picks the path based on cost and reliability: if the question can be answered from the vault, answer from the vault. If the vault is insufficient and a structured tool exists, use it. If the answer requires real-time source state, query the source.

## The identity layer

Every agent interaction begins with identity resolution. Who is asking? What is their access tier? What tools are they permitted to use?

This is the single most important architectural decision in the consumption layer. We do not give an agent "all the tools" and rely on it to filter outputs. We give an agent *only the tools the requesting user is permitted to use*. The boundary is enforced at the tool level — the agent literally cannot call a tool that wasn't provided to it.

In practice, identity resolution looks like this:

A user authenticates to the consumption surface (Claude Code with their SSO, a chat agent with their session token, etc.). The identity layer maps that user to a profile: their access tier (team or commercial), their primary projects, their preferences. The agent runtime is initialized with a tool set scoped to that profile. The agent never sees that there might have been other tools available; from its perspective, the tools it has are the only tools that exist.

For a developer:

- Tools to read the team vault (all projects, all content)
- Tools to read source code repos they have access to
- Tools to query Linear, Gmail (their own mailbox), Calendar (their own)
- *No* tool for the commercial vault
- *No* tool for HubSpot
- *No* tool that exposes commercial source data

For a manager:

- All the above plus tools to read the commercial vault
- Tool for HubSpot (full access)
- Tools that combine team and commercial context

The mapping from identity to tool set is configured per role, not hardcoded per user. Adding a new role (say, "external contractor with limited access") is an entry in the config, not a code change.

## The memory layer

Memory is per-user, not per-agent. A junior developer's memory of past tasks is distinct from a co-founder's, even when they use the same agent code. This sounds obvious but is the inverse of how many "company brain" systems are built, where one global memory accumulates knowledge filtered at output time.

Memory has three tiers, each with different lifecycles and uses.

**Working memory** is the current conversation or task. The contents of the agent's context window in this session. The reasoning chain it's currently building. The scratchpad of intermediate results. Working memory dies when the session ends. This is what Claude Code already has by default; we don't need to build it.

**Episodic memory** is the log of what each agent did, when, for whom, and what happened. "Agent run on 2026-05-09 for Rares, task: draft Linear tasks from Acme meeting notes, result: 3 tasks created, 1 rejected by user." Episodic memory is append-only, audited, and primarily useful for two things: debugging when an agent did something unexpected, and giving the agent recall of "I tried this approach before and it didn't work."

Episodic memory is stored as structured records in the state database, with a per-user index. An agent run includes the user identity, the task description, the tools used, the artifacts produced, and the human approval result if any. We do not store the full conversation; we store enough to reconstruct what happened.

**Semantic memory** is the agent's distilled model of recurring patterns: this user prefers concise summaries, this team uses specific terminology, this project has a particular review process. Semantic memory is per-user, slow-changing, and updated by a periodic process that summarizes recent episodic memory into stable preferences.

Semantic memory is the trickiest tier because it has the most potential for embarrassing failures. "This user once asked about competitor pricing and we remember they care about it" is the kind of thing that should not become a permanent fact in the agent's view of someone. We mitigate by keeping semantic memory short (a few hundred tokens per user), focused on style and process preferences rather than substantive claims, and reviewable by the user.

For v1, only working memory is implemented (because Claude Code provides it). Episodic memory is added when we have enough usage to make replay valuable. Semantic memory is added when episodic memory shows clear, stable patterns worth distilling. We do not pre-build these tiers; we add them as evidence justifies.

## The write path: staging and approval

Agents in Cube-Context do not write directly to external systems. They write *proposals* to a staging area, and humans promote proposals to actions.

This is the single most important safety mechanism in the agent layer, and it deserves explicit description.

When an agent decides an external action is appropriate — creating a Linear task, drafting an email, updating a HubSpot note — it produces a proposal document in the staging area. The proposal includes:

- The intended action (which system, what operation, what payload)
- The reasoning (why the agent thinks this is appropriate)
- The context it drew from (which files, which sources)
- Any caveats or uncertainties

The proposal lands in `cube-context-team/_staging/<date>/<task-id>.md` (or the commercial vault for commercial actions). A human reviews the proposal and either:

- Approves it, triggering the actual action through a separate write path
- Modifies it (edit the payload, then approve)
- Rejects it (the proposal is archived to `_staging/rejected/`)

The agent never has a tool that performs the external write directly. The write tools are owned by the action layer, which checks for approved proposals and executes them. This means even if the agent is somehow manipulated (prompt injection, adversarial input), it cannot cause an external action without a human in the loop.

For high-trust patterns that prove themselves over time, we can add policies that auto-approve specific proposal shapes (e.g., "Linear tasks from meeting notes for projects in active state with no commercial mentions can auto-approve"). These policies live in the action layer's config, not in the agent. Adding a policy is a deliberate operational decision, not a model behavior change.

## How Claude Code fits in

Claude Code is the primary agent for developer use cases. It is not a custom agent we built; it is Anthropic's CLI tool that already exists. Our work is in the conventions and context that make it useful for Cube-Digital's projects.

When a developer runs `claude` in their local clone of the team vault, the agent has:

- The full team vault on disk (markdown files, project folders, the registry)
- A `CLAUDE.md` at the vault root that documents conventions: what `_brief.md` means, how meetings are structured, where to find decisions, what to do when starting a task on a project
- Their own code repositories accessible through Claude Code's file tools
- Optional MCP tools for Gmail, Calendar, and other sources they personally have access to

This is all the developer needs for most tasks. They can ask "what was decided about the Acme integration last meeting" and Claude Code reads the meeting summary. They can ask "draft a PR description for this change based on the project's conventions" and Claude Code reads `_brief.md` and `decisions.md` to produce something aligned with the project.

We do not build a custom agent for developer use. We build the substrate (the vault, the conventions, the `CLAUDE.md`) and let off-the-shelf agents consume it.

## How Donna fits in

Donna is the chat surface for the whole team — engineers, project managers, and co-founders alike. Where Claude Code is a developer's tool for working in a specific project folder, Donna is a shared, ambient surface for asking questions across projects, pasting ad-hoc context into a conversation, and triggering agents that produce drafts or summaries.

Donna runs as a Django web server that serves an Electron desktop client. Every user installs the client; the client authenticates via SSO and keeps a local clone of whichever vault(s) the user's identity permits, synced via background `git pull`. The same files Donna's agent reads on the server are sitting on the user's disk for Obsidian and Claude Code to consume in parallel. The Electron app exposes an "open in Claude Code" launcher that drops the user into a terminal in `~/Cube-Context/`, which is the keystone integration between Donna's chat and the developer-tier consumption surfaces.

A Donna conversation is per-user. The agent's tool set is bound to the requesting user's identity at the moment the conversation starts. A developer's Donna sees only the team vault. A co-founder's Donna can read both vaults and has additional tools (HubSpot status, commercial deal context) gated to their tier. The same architectural rule that governs Claude Code applies here: the agent cannot reach data its user is not permitted to see, because the tool simply isn't in the agent's hands.

Donna's identity-scoped tools are the same library that any other agent surface uses. There is no Donna-specific data path. Donna is a thin chat layer on top of the vault tools — it just happens to be the surface that most non-developer team members use day-to-day. Specialized future surfaces — a weekly status digest, a "projects at risk" dashboard — are built on top of the same vault-reading tools and can reuse Donna's identity layer without reuse of its chat UI.

When a user pastes ad-hoc content into Donna (a forwarded email, a transcript fragment, a screenshot of a Notion page), that content is not auto-ingested into the vault. It lives in the conversation's working context and informs the agent's response, but it does not become permanent project context unless an explicit promote-to-vault action is taken — a staged proposal that lands in the same `_staging/` folder as any other agent write. This keeps the vault's curated nature intact: the vault is what survived a human's deliberate decision to record it, not what passed through chat.

For users who prefer not to install Electron (or for any reason the desktop client isn't available), the same Django backend exposes a web client at the same URL. The web client is functionally equivalent for chat but lacks the local vault sync and the Claude Code launcher — the two features that make the desktop experience qualitatively different.

## Streaming and transport

Donna's responses stream token-by-token over Server-Sent Events from the Django backend. Browser-native `EventSource` cannot send custom HTTP headers, which conflicts with our JWT auth pattern. We resolve this with a ticket exchange: the client posts its bearer JWT to `/api/sse/ticket` and receives a short-lived (30-second) one-time ticket, which it uses as a query parameter on the SSE URL. The server validates the ticket, discards it, and opens the stream. The same channel multiplexes chat tokens, ingestion notifications (such as "a new Acme meeting brief was distilled"), and task progress for any in-flight agent runs.

In the Electron client, the SSE connection lives in the **main process** (Node, no Chromium background throttling), with events forwarded to renderer windows over IPC. This sidesteps the renderer's background-tab throttling and avoids opening multiple sockets when the user has multiple windows. The connection sends a keepalive comment every 15-20 seconds, defeating proxy buffering and idle timeouts, and supports reconnect with `Last-Event-ID` replay from Redis-buffered events.

## Multi-agent thinking

The architecture supports multiple agents but does not require multi-agent orchestration as a centerpiece.

A "multi-agent system" in the literal sense — multiple specialized agents that coordinate to solve a task — has real value for specific workflows: a planner agent that decomposes a task, sub-agents that handle each subtask, a synthesizer that combines results. We use this pattern where it earns its place, but we don't build orchestration infrastructure speculatively.

What we do have is multiple agents in the sense that different consumption surfaces run different agents: Claude Code for developer work, a chat assistant for management, scheduled distiller agents in the pipeline, possibly future agents for status reports or task generation. These agents share the vault substrate and the identity layer but don't coordinate among themselves. Each is its own thing.

If we eventually need multi-agent coordination — for example, a "research agent" that gathers context, hands off to a "drafting agent" that produces a proposal, hands off to a "review agent" that critiques the proposal — we build it when the use case is clear and well-scoped. We do not adopt a multi-agent framework as a starting point.

## Limits and known weaknesses

A few honest caveats about the agent layer:

**Retrieval quality is bottlenecked on the vault's quality.** If a project's `_brief.md` is stale or its meeting summaries are sparse, the agent's answers will be worse. The agent is only as good as the curated content it can read. This means the operational discipline of maintaining the vault matters more than the agent technology.

**Identity scoping is only as strong as the surface enforcing it.** If a developer manages to get access to the commercial vault repository (someone misconfigures GitHub permissions), the identity layer in the agent is irrelevant — they can read the files directly. This is why repository-level access control is the primary boundary, with identity-scoped tools as an additional convenience for query-time access.

**The system has no real-time guarantees.** A meeting that happened twenty minutes ago is probably not yet in the vault. An agent asked about it will say "I don't have information about today's meeting" or, worse, hallucinate. We mitigate by making the agent explicit about its context's freshness, but we cannot make it instantly current.

**Semantic memory can drift into unwanted territory.** A poorly-tuned semantic memory layer can learn things about a user that the user did not want learned. We mitigate by keeping semantic memory short, focused on process preferences rather than substantive claims, and reviewable. We do not pre-build it; we add it when the value is clear and we've thought about the failure modes.

## What v1 actually delivers

For the initial build, the agent layer is intentionally simple:

- Developers run Claude Code in their local clone of the team vault, with a `CLAUDE.md` at the root documenting conventions
- The whole team uses Donna — the Django chat server with the Electron desktop client — to ask questions across projects, paste ad-hoc context into a conversation, and trigger agent-produced drafts
- The Electron client keeps the appropriate vault(s) synced locally so Obsidian and Claude Code work against the same files Donna reads
- Identity-scoped tools are the only access control inside the agent runtime; repository-level access remains the structural boundary

We do not build, in v1:

- A custom multi-agent orchestration layer (Donna is single-agent per conversation)
- A semantic memory system (Donna conversations are stateless across sessions; episodic logs may follow once usage justifies them)
- Multi-user shared conversations (one user per conversation; collaborative chats may come in a later phase if the single-user experience earns its place)
- Auto-approval policies for agent writes (every promote-to-vault and every external action is staged)
- A polished web-only chat client (the web fallback exists but is intentionally minimal; the desktop client is the primary surface)

These come later, on evidence, as we learn what actually creates value. The bet is that 80% of the benefit comes from the substrate, and Donna is the surface that makes that substrate accessible to non-developers.
