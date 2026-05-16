# Decisions and tradeoffs

## Why this document exists

Every architectural decision in this system was made by rejecting several alternatives. Capturing those alternatives — and the reasoning for rejection — matters for two reasons.

First, when we revisit a decision in six months, we want to know why we chose what we chose. Without this record, we'll re-derive the same conclusions or, worse, change the design on a whim and miss the original constraint.

Second, when someone new joins the team and asks "why is it built this way?", this document is the answer. It saves the synchronous explanation and makes the team's collective reasoning legible.

## The big decisions, in order

### Decision: Project-shaped storage, not source-shaped

**What we chose**: Organize all content by project. Each project has a folder that pulls in content from every relevant source. Cross-source joins happen at ingestion time.

**What we rejected**: Source-shaped storage where the agent queries each source separately at query time and stitches results together. This is how OpenClaw, Claude with MCP connectors, Glean, and most "horizontal" AI tools work.

**Why we chose this**: Cube-Digital's work is project-shaped. Almost every question starts with or implies a project. Pre-joining by project at ingest time is dramatically more efficient at query time, more reliable (no entity-resolution fuzziness across sources), and easier to access-control. The shape of the work is known in advance, and exploiting that shape is the architectural advantage.

**What we accept by choosing this**: Cross-project queries are harder. "Show me all open issues across all clients" requires either scanning all project folders or maintaining a structured layer. We accept this because cross-project queries are rare in our actual usage.

### Decision: Two vaults, repository-level access control

**What we chose**: A team vault and a commercial vault, separated as two private git repositories with distinct access lists. Repository membership is the access boundary.

**What we rejected**: A single unified store with field-level or row-level tier tagging, queried through identity-aware retrieval that filters at query time. This is how Glean, Notion AI, and serious enterprise RAG systems work.

**Why we chose this**: At our scale, the operational simplicity of repository-level access is overwhelming. One access list per vault, git's native permissions, audit logs as git history, easy revocation. No application-level filtering to maintain or test. The architectural separation makes leakage structurally hard rather than dependent on correct filtering.

**What we accept by choosing this**: We can't have "this project is visible to this subset of the team" without creating another repository, which adds operational overhead. We're betting that at our size, the team and commercial split is the only axis of separation that matters.

**When to revisit**: If we onboard a client whose contract requires team-internal access lists per project, or if the execution team grows large enough that cross-project visibility within the team space starts to feel like over-sharing.

### Decision: Reject the full medallion architecture

**What we chose**: Two-layer architecture (raw artifacts plus distilled vaults), with curated content in markdown.

**What we rejected**: A full bronze/silver/gold medallion with object storage for raw, a normalized structured layer in Postgres, a vector store for semantic retrieval, and multiple gold audience-shaped views all materialized from the same silver.

**Why we chose this**: The medallion is right for large-scale systems with heavy query volume, complex analytics, and many heterogeneous consumers. At our scale, it's pre-built infrastructure for problems we don't have. We can add layers later if we need them — the raw artifacts in the commercial vault give us the foundation to regenerate any future layer.

**What we accept by choosing this**: We don't have semantic search yet. We don't have structured cross-project queries. If we want either, we have to add infrastructure. We bet that markdown plus grep plus the agent layer is enough for our team's scale.

**When to revisit**: When the vaults grow past ~10,000 files and grep gets slow, or when we have a use case for semantic search that the agent-layer approach can't satisfy.

### Decision: Markdown in git as the substrate, not Notion

**What we chose**: Markdown files in git repositories.

**What we rejected**: Notion as the storage substrate (as a "silver" layer or as primary storage), with native databases for projects/deals/people and the team consuming through Notion's UI.

**Why we chose this**: Notion has rate limits that make programmatic ingestion painful, is mutable in ways that conflict with bronze's immutability requirements, stores data on Notion's US infrastructure (a problem for EU client contracts), has weak bulk read and lineage tracking, and creates a vendor dependency we don't want. Markdown in git gives us versioning, diffs, review, and full data sovereignty.

**What we accept by choosing this**: Business users don't get a polished UI. Some management users may prefer Notion or a similar tool. We accept the tradeoff because the engineering team's productivity matters most and the alternative requires real infrastructure work to maintain Notion as a secondary view.

**When to revisit**: If management strongly prefers a Notion-style surface and we have evidence that markdown access is a barrier to their adoption, we add a one-way sync from the commercial vault to Notion. The vault remains canonical.

### Decision: Drive as backing store for files, not as bronze

**What we chose**: Drive is where actual file artifacts live (Docs, presentations, designs). The vaults index these with summaries and links but don't duplicate the file contents.

**What we rejected**: Drive as bronze storage with all raw artifacts (transcripts, emails, snapshots) stored as Drive files. Postgres metadata alongside.

**Why we chose this**: Drive is a file system, not a data store. Its API is rate-limited, its mutability conflicts with bronze's immutability requirements, its access via Google account creates lock-in risk, and its query patterns don't fit bulk re-processing. For our scale and use case, putting raw artifacts as files in git (in the commercial vault) gives us everything Drive would, with proper version control and no vendor lock-in.

**What we accept by choosing this**: Drive becomes a secondary system, indexed but not central. If Drive is unavailable, we lose access to the file artifacts (proposals, designs) but not to the project context.

**When to revisit**: If raw artifact volume grows past what git comfortably handles (large audio files, video, very high commit volume), we move raw artifacts to a proper object store (R2, MinIO, or Drive with proper API handling) while keeping metadata in git.

### Decision: Markdown distillation, not LLM-at-query-time

**What we chose**: Pre-compute distilled summaries at ingest time. Agents read the summaries.

**What we rejected**: Store raw transcripts and emails directly accessible to agents, with the agent doing summarization at query time.

**Why we chose this**: Pre-computed summaries are cheaper at query time (no LLM call to re-summarize on each question), more consistent (the same question gets the same answer until the underlying data changes), easier to access-control (you can curate the summary to enforce tier boundaries), and reviewable (the summary is a file we can read, diff, and revert).

**What we accept by choosing this**: We pay distillation cost upfront. We commit to a specific interpretation of the source content (the distiller's view) rather than letting the agent re-derive it for each question. We can't ask for a different "framing" of an old meeting without re-distilling.

**When to revisit**: If we find ourselves frequently wanting to ask questions that require different interpretations of the same source content, we can add a second distillation pass or expose raw content (in the commercial vault only) to agents with the right access.

### Decision: Reject "agent with full context, filters at output"

**What we chose**: Agents have access only to the data their user's identity permits. No agent has the full context with output filtering.

**What we rejected**: A "god agent" that has access to everything and is prompted to filter outputs based on the requesting user.

**Why we chose this**: Output filtering is the dominant failure mode for unified-context agents. Prompt injection, summary leaks, agent decision to "be helpful" with restricted data — all of these break filtering. The architectural principle is: don't put tier-3 data in the context window when serving a tier-1 query. Agents physically don't have access to data they shouldn't show.

**What we accept by choosing this**: We can't have a single "super agent" that can answer anyone's question with the full context available. Different roles get different agents (or the same agent with different tools). This is more infrastructure to maintain but it's the only pattern that survives audit.

**When to revisit**: Never, on this specific point. The risks of output-time filtering are well-established and don't shrink with better models.

### Decision: Per-source distillation prompts, not one general distiller

**What we chose**: A separate prompt per source-and-audience pair. `FathomTeamDistiller`, `FathomCommercialDistiller`, `GmailTeamDistiller`, etc.

**What we rejected**: A single general-purpose distiller that takes any artifact and an "audience" parameter, with the prompt instructing it on what to extract and what to exclude.

**Why we chose this**: Different sources have different content patterns and different leak risks. A Fathom transcript looks nothing like a Gmail thread; the exclusion rules and the extraction patterns are different. Per-source prompts can be tuned independently. One general prompt would be more brittle and harder to iterate.

**What we accept by choosing this**: More prompts to maintain. Some duplication across prompts for shared rules (the "don't include monetary amounts" instruction appears in every team distiller).

**Trade-off mitigation**: Common exclusion rules live in a shared template that each source-specific prompt includes. We don't fully duplicate; we compose.

### Decision: Pull pattern for Gmail (forwarding), not full ingestion

**What we chose**: Project-relevant emails are forwarded by team members to ingestion aliases. We don't auto-ingest mailboxes wholesale.

**What we rejected**: Per-user Gmail OAuth with auto-ingestion of every email, filtered by sender/recipient to extract project-relevant threads.

**Why we chose this**: Personal mailboxes contain too much that doesn't belong in shared project context. Auto-classifying which threads are project-relevant is fuzzy and error-prone. The forwarding pattern requires human judgment ("is this thread worth preserving?") which is exactly the right call to make.

**What we accept by choosing this**: Forwarding friction. People forget to forward. Some context is lost because it was never forwarded. We accept the loss; it's better than the noise of full ingestion plus the false-positive routing errors.

**When to revisit**: If forwarding friction becomes a major complaint, we move to Pattern 2 (label-based ingestion with per-user OAuth) which is lower-friction but more infrastructure.

### Decision: No WhatsApp automation in v1

**What we chose**: Manual export and ingestion for WhatsApp. No automated bridge or API.

**What we rejected**: WhatsApp Business API integration, Baileys self-hosted bridge, or a WhatsApp Web scraping approach.

**Why we chose this**: WhatsApp is a high-risk source. The Business API is paid and limited; Baileys is unofficial and fragile; scraping is against ToS and unreliable. The cost of building any of these for our v1 — when WhatsApp may or may not be the highest-value source — is too high.

**What we accept by choosing this**: WhatsApp context lags more than other sources because it depends on manual export cycles. Some context never makes it into the system.

**When to revisit**: If specific projects rely heavily on WhatsApp for substantive discussion and the manual workflow is painful, invest in proper ingestion for those projects. Otherwise leave it manual indefinitely.

### Decision: Human-in-the-loop for the first month of distillation

**What we chose**: Team-vault distillations go through PRs for human review during the first month of operation. After validation, auto-merge with the leakage scanner as the backstop.

**What we rejected**: Either fully manual review forever (too much friction) or fully automated from day one (too risky before the prompts are calibrated).

**Why we chose this**: Distillation prompts will have bugs in their first iterations. Catching those bugs requires reading distillation output and comparing to the source. PRs give us a workflow for that review. After a month, we have evidence about whether the prompts are reliable enough to remove the gate.

**What we accept by choosing this**: First-month friction. Slower iteration during the calibration period. The need for an owner who reviews PRs regularly.

**Trade-off mitigation**: Distillation PRs are batched; reviewing a week's worth takes less than an hour if the prompts are mostly working.

### Decision: No multi-agent orchestration upfront

**What we chose**: One agent per consumption surface (Claude Code for devs, possibly a chat agent for management). No orchestration framework, no agent-to-agent handoff infrastructure.

**What we rejected**: Building or adopting a multi-agent framework (LangGraph, AutoGen, CrewAI, etc.) as a starting point, with specialized agents that coordinate via shared state.

**Why we chose this**: Multi-agent orchestration is infrastructure looking for a use case. For our needs, single-agent patterns are sufficient and dramatically simpler. We add coordination only when we have a specific workflow that requires it.

**What we accept by choosing this**: We can't immediately implement complex multi-step agentic workflows. Some sophisticated patterns (research → draft → critique loops) require us to build them when the need arises.

**When to revisit**: When we have a specific, well-scoped workflow that genuinely needs multi-agent coordination and we've named the failure modes of trying to do it as a single agent.

### Decision: Donna chat as a third primary consumption surface

**What we chose**: Build a chat application — Django backend, Electron desktop client — as a first-class consumption surface alongside Obsidian and Claude Code. Donna lets the whole team ask questions across projects, paste ad-hoc context into a conversation, and trigger agents to produce drafts.

**What we rejected**: Restrict consumption to Obsidian and Claude Code, with a possible future "chat assistant for managers" deferred indefinitely. This was the earlier architectural posture and it had real merit: it kept the substrate clean and forced curation to be the primary work.

**Why we chose this**: Claude Code is a developer's tool. Obsidian is a power-user tool. Most of the team — project managers, account leads, co-founders — wants neither a CLI nor a markdown explorer. They want to type a question and get an answer. Donna is that surface. Without it, the vault's value is gated by tool literacy. With it, the same substrate is accessible to anyone who can type into a chat box. The deciding observation: the value of the vault is proportional to the breadth of people consuming it. A vault that only developers use is a developer productivity tool. A vault that the whole team uses is a company-wide context layer. The chat surface is what makes the second framing possible.

**What we accept by choosing this**: Real engineering scope. A chat server (Django, SSE, identity-scoped tools), a desktop client (Electron, native surfaces, auto-update, code signing), and the operational overhead of running both in production. We also accept that a chat UI is a forgiving surface — users can ask questions the vault can't answer, and Donna has to fail gracefully rather than hallucinate. This puts ongoing pressure on prompt engineering and tool design that wouldn't exist if the only consumption surface were Claude Code, where the user is technical enough to recognize bad output.

**When to revisit**: If Donna proves to be infrastructure looking for a use case — if the team continues to ask questions in Slack or in person rather than in chat — we treat it as an experiment that didn't earn its place and remove it. The vault stands without it.

### Decision: Electron desktop client, with local vault sync as the keystone feature

**What we chose**: Distribute Donna as an Electron desktop application. The Electron client wraps the same web UI that a browser would render, but adds three native capabilities the web cannot deliver: a background process that keeps `~/Cube-Context/` synced with the user's permitted vault(s) via `git pull`, an "open in Claude Code" launcher that spawns a terminal in that local clone, and system-keychain-backed token storage.

**What we rejected**: A browser-only web client. Also rejected: Tauri, which is technically lighter (10-20 MB binaries versus Electron's 100-200 MB) but introduces Rust to a Python and JavaScript team. Also rejected: native macOS and Windows clients built per platform.

**Why we chose this**: The local vault sync is the single feature that justifies the desktop client. Without it, Electron is a slower version of a browser tab. With it, the user has the *same files* on disk that Donna's agent is reading on the server. Obsidian opens those files. Claude Code can be launched in them. The desktop client becomes the bridge between Donna's chat surface and the developer-tier consumption surfaces, without making the user think about how to keep things in sync. The on-premises *feel* is also real, even if it's not a security posture — sales-adjacent and management users trust desktop apps with client data more than browser tabs, and for an internal tool that handles commercial conversations, the perception matters. Electron over Tauri: the team's expertise is in JavaScript, the ecosystem is deeper, auto-update is more mature, and at our scale the binary-size advantage of Tauri is invisible to end users.

**What we accept by choosing this**: The Electron tax — 100-200 MB binaries, higher memory footprint, and the operational responsibility of code signing (Apple Developer ID, Windows EV cert if we ship Windows) and auto-update infrastructure. The build pipeline gets more complex. Distribution requires its own discipline: a signed installer hosted on an internal page, with `electron-updater` pointing at an S3 feed.

**When to revisit**: If team adoption shows that nobody uses the local vault sync or the Claude Code launcher — that is, if Donna becomes a chat tool divorced from the developer workflow — we drop the Electron client and ship browser-only. The desktop client only earns its place if the cross-surface integration matters.

## Smaller decisions worth noting

### SQLite, not Postgres

Single file, no server, sufficient for our write volume, easier to back up. Migration to Postgres is straightforward if we ever need multi-writer concurrency or remote access.

### Python, not Go or TypeScript

Best ecosystem for LLM work, Pydantic for data models, Anthropic SDK is excellent. The performance ceiling is well above our needs. The team's familiarity matters more than minor performance gains.

### Django for the ingestion service and the Donna chat server

A single Python web framework runs both the ingestion webhook endpoints and the Donna chat server. The earlier sketch had FastAPI for ingestion and left the chat server open; we collapsed both onto Django.

Django brings real costs (heavier than FastAPI, less async-native, opinionated about its directory layout) and real benefits (mature ORM with first-class SQLite and Postgres support, the admin for hand-maintaining the project registry and inspecting state, DRF for the chat API, ASGI via Daphne or Uvicorn for SSE streaming). The deciding factor is operational consistency: one framework, one deployment, one set of conventions for the people who will operate the system. Splitting ingestion and chat across two frameworks would have created an unnecessary cognitive tax for a four-person team.

The ingestion service runs as Django management commands (for polling) and DRF webhook views (for source push events). The Donna chat server runs as a Django ASGI application for SSE streaming. Both share the same models, the same SQLite state database, and the same deployment unit.

If chat scale ever exceeds what a single Django process can serve, we split chat into its own deployment unit without changing the framework.

### SSE with a one-time-ticket exchange for chat authentication

Browser `EventSource` cannot send custom HTTP headers, which conflicts with our JWT-bearer auth pattern. We solve this with a short-lived ticket: the client posts its bearer JWT to `/api/sse/ticket`, the server returns a 30-second one-time ticket, and the client uses it as a query parameter on the SSE URL. The server validates and discards the ticket on open. The alternatives — putting JWTs directly in URL query strings, switching to cookie-based session auth, or replacing SSE with WebSockets to get header support — each had worse tradeoffs (logged secrets, cross-origin complications, or premature commitment to a bidirectional transport we don't need for chat).

### Cron over a scheduler library

System cron is one less thing to debug. APScheduler is a fine choice too but introduces a runtime dependency that needs to keep working. Cron is OS-level and just works.

### One container, not microservices

We're a four-person company. Microservices would be premature. One Docker container, multiple entry points, deployed to one host or one Cloud Run service.

### Manual project registry, not auto-discovered

We considered auto-discovering projects from HubSpot deal stage transitions. We rejected it because the registry is the keystone of routing and we want explicit human control over what counts as a project. Adding three lines to a YAML file is not a meaningful operational burden, and the discipline forces a moment of thought ("is this really a project we should track?").

### Hetzner over Cloud Run

Either works. Hetzner gives us EU sovereignty and predictable cost. Cloud Run is zero-ops and pay-per-request. The decision is operational preference; both fit the architecture.

## What we'd change with more time or scale

If we were building this at 30 people instead of 4:

- A proper identity layer with SSO, role mappings stored centrally, audit logging
- A small structured query layer over the vaults (probably Postgres with pgvector) for cross-project analytics
- A queue (Redis or NATS) for distillation to allow concurrent processing without overloading the Anthropic API
- A real observability stack (logs to Loki, metrics to Prometheus, alerts to PagerDuty)
- Per-team distillation prompts tuned for different verticals (HealthTech vs manufacturing have different exclusion needs)
- Automated registry maintenance with explicit approval flows

We're not at that scale. Adding any of this now is a bet against our actual current size in favor of a hypothetical future. We will add infrastructure when reality requires it.

## What we deliberately won't build, ever (probably)

A few things we've thought about and rejected with high confidence:

- A custom orchestration platform that competes with OpenClaw, Cowork, or Claude Code. We're not building agent infrastructure; we're building context infrastructure that those agents consume.
- A productized SaaS version of Cube-Context. Maybe someday, but it's a different business and would require a separate architecture optimized for multi-tenancy.
- Real-time ingestion. Distillation lag is acceptable; chasing real-time creates infrastructure complexity that isn't warranted.
- LLM-based access control. The "agent that filters outputs by who's asking" pattern has known failure modes and we won't introduce it under any framing.
