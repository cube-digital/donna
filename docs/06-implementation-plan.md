# Implementation plan

## Posture

This plan is deliberately anti-perfectionist. The goal is to ship the smallest useful slice quickly, learn from real use, and expand on evidence. Every week below has a deliverable that produces signal, even if it's a slice of the eventual system.

Three principles guide the sequencing:

**Vertical slices over horizontal layers.** Each week's work should deliver something useful end-to-end, even if narrow. We do not build "all the storage" in week 1 and "all the ingestion" in week 2. We build one source from receipt to consumption in week 1, then add the second source in week 2.

**Validate before scaling.** Don't add the second project before the first one works. Don't add the third source before the second is reliable. The temptation to onboard everything at once is strong; resist it. Two weeks of one-project use will reveal more about what to build next than a month of speculative design.

**Manual where automated would be premature.** Human review of distillations in the first month. Manual registry maintenance. Manual triage of unrouted artifacts. These are not laziness; they are deliberate scope reduction that buys us time to learn what to automate.

## Week 0: Decisions and setup

Before any code, settle the questions that affect everything:

- Confirm the two-vault structure and access lists (who exactly is on each)
- Decide where the ingestion service will run (Hetzner VPS recommended for sovereignty; Cloud Run if we want zero-ops)
- Decide on the project tagging convention for calendar invites (`[acme]` is the proposed format)
- Identify the one project to use as the test bed (active enough to generate signal, not so critical that prototype gaps hurt)
- Decide who owns the registry day-to-day (Andreea is the proposed owner)

Concrete artifacts produced this week:

- Two empty private git repositories: `cube-context-team` and `cube-context-commercial`
- Access lists configured on both
- A VPS provisioned with Docker installed (or a Cloud Run project set up)
- A registry YAML stub with the chosen test project filled in
- This documentation set committed to the team vault

## Week 1: Fathom end-to-end on one project

Goal: a Fathom transcript for the test project arrives via webhook, gets distilled into team and commercial summaries, and both land in the appropriate vault.

Build:

- Project skeleton for the ingestion service (Python, Django + DRF, SQLite state via the Django ORM)
- Registry loader and the test project entry
- Router for Fathom (title and attendee matching against the registry)
- Fathom email webhook receiver (using SendGrid Inbound Parse or similar to convert Fathom's email-based output to HTTP POSTs)
- Team distiller and commercial distiller for Fathom, with initial prompts
- Writers for both vaults (using GitPython)
- Leakage scanner (basic regex pass)
- CLI command to manually trigger distillation on a saved transcript

Validate:

- Run the pipeline on 5-10 past meetings from the test project, by feeding their transcripts through the CLI manually
- Read the team distillations: are they useful? Are they leaking anything?
- Iterate on the team distiller prompt based on what you see
- Read the commercial distillations: are they capturing the substance?
- Spot-check the leakage scanner: is it catching what it should?

This week is mostly prompt engineering, not code. The Python plumbing is straightforward; the distiller prompts are where the real work is.

By end of week 1: one project has meeting notes auto-distilled into both vaults. Developers can browse it in Obsidian. The pipeline runs reliably on new Fathom transcripts for that project.

## Week 2: First-class developer experience

Goal: a developer working on the test project uses Claude Code in the team vault and the experience is noticeably better than working without it.

Build:

- `CLAUDE.md` at the team vault root documenting the structure and conventions
- `_brief.md` for the test project (hand-written, this is high-value content)
- `_status.md` for the test project (hand-written for v1, automated later)
- A `decisions.md` file with notable decisions extracted from past meetings (can be done by running distillation across the historical transcripts)
- Set up Obsidian on at least one developer's machine pointed at the team vault clone
- Configure Claude Code to be aware of the vault structure (mostly via the `CLAUDE.md`)

Validate:

- A developer (probably Rares first, then one team member) spends a workday using Claude Code in the test project's folder
- Document what worked and what didn't: which questions did Claude Code answer well, which did it stumble on, what was missing from the vault
- Adjust the conventions, the brief, the distiller, based on real use

By end of week 2: at least two people are using the vault productively. We have evidence for what makes a vault "good" — what content matters, what structure works, what's noise.

## Week 3: Second source (Discord) and second project

Goal: add Discord ingestion and onboard a second project to validate that the system handles multi-project, multi-source operation cleanly.

Build:

- Discord bot using `discord.py`, listening on the registered channels
- Routing logic mapping channel IDs to projects
- Daily batch distillation for Discord (one summary per channel per day)
- Add the second project to the registry, including its Discord channel
- Hand-write the second project's `_brief.md`

Validate:

- Discord summaries are useful, not noise (calibrate the distiller's prompt to drop social chatter)
- Both projects' contexts stay separate (no cross-contamination)
- Two projects in the team vault don't make navigation worse; the structure scales

By end of week 3: two projects, two sources, with reliable end-to-end flow.

## Week 4: HubSpot for commercial space

Goal: management can see commercial state in the commercial vault, including HubSpot deal information.

Build:

- HubSpot poller (daily, or webhook-driven for deal stage changes)
- Snapshot writer that produces `_deal.md` per project in the commercial vault
- Append `deal-history.md` with day-over-day deltas
- Verify nothing from HubSpot leaks to the team vault under any condition

Validate:

- Manager opens the commercial vault and sees an up-to-date view of each project's deal state
- Verify the team vault has no HubSpot-derived content
- The commercial side is now genuinely useful for management's "what's happening" question

By end of week 4: commercial vault has both meeting content (from Fathom) and deal context (from HubSpot). Management can use it to stay informed.

## Week 5: Gmail forwarding pattern

Goal: project-relevant emails flow into the right vault when team members forward them to the project alias.

Build:

- Per-project email aliases (`projects+acme@cube-digital.io` and `projects-comm+acme@cube-digital.io`)
- IMAP poller for these aliases
- Email parser that extracts thread content, attachments, headers
- Email-specific distiller for both team and commercial views
- Team training/documentation on the forwarding convention

Validate:

- Forward a few real project emails (with attachments, with quoted history, with HTML formatting) and verify they ingest cleanly
- Verify the team distiller strips commercial content from emails (deal-related threads should produce team-safe summaries focused on technical content if any)
- Operational test: ask one team member to forward emails during a normal workweek and report friction

By end of week 5: three automated sources (Fathom, Discord, HubSpot) and one semi-automated (Gmail forwarding).

## Week 6: Drive indexing and operational polish

Goal: Drive documents are discoverable from the vaults; the operational layer is robust enough to run unattended.

Build:

- Drive folder scanner using the Drive API, registered with the appropriate scopes
- Per-project indexing that writes `projects/<slug>/docs/index.md` in the appropriate vault
- For Google Docs: pull a short summary and include it in the index entry
- Operational dashboard or CLI showing: artifacts processed last 24h, unrouted count, distillation errors, leakage scanner hits
- Set up monitoring/alerting for service-down conditions (a simple healthcheck endpoint plus a cron that pings it and alerts on failure)
- Backup procedure documented and tested (SQLite, vault remotes, secrets)

Validate:

- Drive index pages are useful: clicking a link opens the right doc, summaries describe the doc's substance
- The system runs for a week without manual intervention
- A simulated failure (kill the service) is detected and recovers

By end of week 6: the system is genuinely operational. All major sources except WhatsApp are integrated. Both vaults are useful, with multiple projects.

## Week 7-8: Expansion, calibration, and graduation

Goal: bring in the rest of the team, validate the human-review gates can be relaxed, and stabilize.

Build:

- Onboard the remaining team members to the team vault
- Onboard remaining active projects (each project = registry entry + initial brief + retroactive distillation of recent meetings)
- After one month of human-reviewed PRs, evaluate whether distiller output is reliable enough to auto-merge. Adjust the leakage scanner accordingly.
- Document the operational playbook (registry maintenance, source onboarding, leakage triage, GDPR procedures)
- Hold a 30-minute team session on vault conventions and the Gmail forwarding pattern

Validate:

- Team members report whether the vault makes them more productive (informally, in conversation)
- Compare time-to-context for new project work before and after
- Identify the highest-friction parts of the operational flow and queue them for improvement

By end of week 8: the system is in steady-state operation, used by the whole team, covering all active projects.

## Phase 2: Donna chat and desktop client

The eight-week foundation builds the vaults, the ingestion pipeline, and the Claude Code experience. Phase 2 adds Donna — the Django chat server and the Electron desktop client — as the team-wide consumption surface. Phase 2 can start as early as week 4 (once the team vault has Fathom content and at least one project is operational) but is sequenced after the foundation because chat without curated content is a demo, not a tool. Phase 2 is likely four to six weeks once started.

The build, in order:

**Donna server skeleton.** A Django app within the same project as the ingestion service. JWT auth, a `Conversation` and `Message` model in SQLite, and the SSE endpoint with the ticket exchange. Initial scope: a user authenticates, opens a conversation, and the conversation streams a single LLM response token-by-token. No vault tools yet — just LLM-only chat as a transport sanity check. This is the smallest possible end-to-end slice that validates the framework choice, the SSE plumbing, and the auth flow.

**Identity-scoped vault tools.** The agent gets its first real tools: `list_projects(tier)`, `get_project_brief(slug, tier)`, `search_meetings(slug, query, tier)`, `get_decisions(slug, tier)`. Each tool is gated by the requesting user's tier, set when the conversation initializes. A developer's Donna can call only the team-vault flavor; a co-founder's Donna can call both. The tool implementations are thin wrappers over the same markdown-reading code the ingestion service uses to verify writes.

**Electron client v1.** A thin Electron wrapper around the Donna web UI that adds: a tray/menubar icon with vault sync status, system-keychain-backed token storage (`keytar`), native notifications for ingestion events that arrive over the SSE stream, and a background process that runs `git pull` on the user's local clone of the team vault on a fixed schedule. Auto-update via `electron-updater` and an S3-hosted feed. Distribution: signed installers (Apple Developer ID, Windows EV cert if Windows is supported) hosted on an internal page.

**Claude Code launcher.** A button in the Electron client that opens a terminal in `~/Cube-Context/` with `claude` running. This is the on-premises feature that justifies the desktop client over a browser tab. For users with commercial access, a second button opens the commercial vault's local clone.

**Promote-to-vault staging.** When a user has pasted ad-hoc context into a conversation and wants it preserved (a forwarded email, a quote from a client call), a "promote to vault" action produces a staged proposal in `_staging/`. The proposal is reviewed and either merged into the project's folder or rejected. This is the same staging path used by every other agent write — there is no Donna-specific write path.

**Validation.** A pilot user — probably one co-founder plus one developer — uses Donna for a week as their primary surface for cross-project questions. Document what worked, what didn't, what was missing from the vault that the chat surfaced as a gap. The biggest risks at this stage are tool-design mistakes (a tool that returns too much, too little, or the wrong shape) and agent-prompt issues; both surface quickly in real use. The vault-quality feedback loop from Donna usage is one of the most valuable signals Phase 2 produces.

By the end of Phase 2, the team has a chat surface installed on every laptop that reads from the same vaults the developer workflow reads from, and stays within the access-tier boundaries the architecture enforces structurally.

Phase 2 explicitly does *not* build:

- Multi-user shared conversations (one user, one conversation, for now)
- Conversation memory across sessions (each conversation is fresh)
- Auto-ingestion of pasted content into the vault without staging
- A polished mobile or tablet client
- Voice or video in chat

These are deferred to a hypothetical Phase 3 if the basic shape earns its place in the team's workflow.

## Beyond week 8: what comes next

The next priorities depend on what we learn in weeks 1-8. Likely candidates, roughly in order:

**Action layer for high-value writes.** The first specific write path to automate is "draft a Linear task from a meeting action item." This is high-frequency, high-value, and well-bounded. Build the staging-and-approval pattern around it.

**Status digest agent.** A scheduled agent that produces a weekly status summary across all active projects and emails it to management. Reads from the vaults, produces a single document, no writes to external systems.

**WhatsApp ingestion if it matters.** If WhatsApp traffic on specific projects is high-value and the manual workaround is painful, invest in proper ingestion (Baileys or WhatsApp Business API). If not, leave it manual indefinitely.

**Semantic search.** If grep and Obsidian search become inadequate (probably around 1000+ files across the vaults), add a vector store. Qdrant or pgvector are the leading candidates.

**Cowork integration for management.** If management wants a specific surface (we noted this depends on validation; they may be happy with the markdown vault), build the integration as a one-way sync from the commercial vault to Drive Docs.

**Multi-tenant productization.** Only if there's clear external demand and we're confident in the architecture. Not before month 6 of internal use at the earliest.

## Risk register and mitigations

A few specific risks worth tracking:

**Distiller leakage.** Mitigated by the leakage scanner, the human review gate for the first month, the architectural split (raws never in team vault), and ongoing prompt iteration. If a leak does occur, document it in the operational log and update the distiller and scanner together.

**Registry drift.** The registry is hand-maintained and will drift if no one owns it. Andreea is the proposed owner. Weekly review of the `unrouted/` folder catches drift symptoms (artifacts that should have routed but didn't).

**Ingestion service downtime.** Webhook-source artifacts may be lost during downtime; most sources retry but not all. Mitigations: minimize downtime by keeping the service simple, monitor with a healthcheck, document a quick-restart procedure. For prolonged outages, sources like Fathom can be replayed manually from email.

**Team adoption.** If the team doesn't use the vault, we've built infrastructure that produces no value. Mitigations: start with Rares and one volunteer, build the experience to a quality bar before broader rollout, listen for friction points and fix them, evangelize specific wins ("Claude Code wrote this whole thing because the brief was clear").

**Scope creep.** The temptation to add WhatsApp on day one, build a custom chat agent, expose a Cowork-style dashboard, etc. Mitigations: this plan, the principle of validating before scaling, and the discipline of saying "not yet" to every nice-to-have until the core slice is solid.

## How to know we're succeeding

After 8 weeks, success looks like:

- Every active project has a maintained team-vault folder with a current brief, recent meeting summaries, and a decision log
- At least three team members are using Claude Code regularly against the vault and report it as useful
- Andreea or another co-founder can answer "what's happening with X" by reading the commercial vault, without asking the team
- The pipeline has run for at least two weeks without manual intervention
- No leakage incidents, or if there have been any, they were caught quickly and produced prompt-engineering improvements

If any of these aren't true by week 8, we slow down and fix them before adding scope. The architecture is right; the operational discipline is what produces value.
