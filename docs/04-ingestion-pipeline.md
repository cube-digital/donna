# Ingestion pipeline

## What this layer does

The ingestion pipeline is the operational core of Cube-Context. Its job is to receive artifacts from external sources, decide which project each artifact belongs to, distill it into appropriate forms for the team and commercial spaces, and commit the results to the right vault.

This is where most of the system's value is created and where most of the operational complexity lives. The rest of the system (vaults, agents, consumption surfaces) is comparatively simple. The pipeline is where the work gets done.

## The pipeline at a glance

The pipeline has six logical stages. Every artifact, regardless of source, flows through these stages in order.

**Receive.** A webhook fires or a scheduled poller wakes up, pulls one or more artifacts from a source, and converts each into a normalized internal representation called an `IncomingArtifact`. The normalization strips source-specific quirks so downstream code doesn't need to know whether something came from Fathom or Gmail.

**Route.** The router takes an `IncomingArtifact` and matches it to a project in the registry. Different sources use different matching strategies (title keywords, attendee emails, channel IDs, folder IDs), but all produce a `RoutedArtifact` with a project slug, a target space, a confidence score, and a reasoning string.

**Persist raw.** The raw artifact is committed to the commercial vault under `projects/<slug>/raw/<source>/`. This happens before any distillation so we never lose the original even if distillation fails.

**Distill.** The team distiller produces a team-safe markdown summary. The commercial distiller produces a fuller summary that retains commercial content. Both use Claude through the Anthropic API with carefully-crafted prompts.

**Validate.** A leakage scanner inspects the team distillation for content that should never appear in the team vault (currency symbols, specific keywords, monetary patterns). Hits cause the team commit to be held in a pull request rather than auto-merged.

**Commit and index.** Both distillations are committed to their respective vaults. The state database is updated to mark the artifact as processed. Any periodic indexing jobs (project status pages, decision logs) are notified that this project has new content.

## The project registry

The registry is the keystone of the pipeline. Without it, automated routing is impossible.

The registry lives in two files. The public part is committed to the team vault at `_registry.yaml` and contains information visible to everyone in the team space — project names, aliases, domains, contact emails, Discord channel IDs, Drive folder IDs. The private part is committed to the commercial vault at `_registry-commercial.yaml` and contains commercial extensions — HubSpot company and deal IDs, internal project codes, anything else that should not be visible to the team space.

The registry loader reads both files at service startup and merges them into a single in-memory model. The pipeline only ever queries the merged registry, so source-side routing logic doesn't need to know which fields came from where.

A typical registry entry looks like this:

```yaml
projects:
  - slug: acme-corp
    name: "Acme Corp"
    aliases: ["acme", "ACME", "Acme Corporation"]
    domains: ["acme.com", "acme-corp.com"]
    contacts:
      - email: maria.popescu@acme.com
        name: "Maria Popescu"
        role: "CTO"
        whatsapp_phone: "+40712345678"
      - email: john.doe@acme.com
        name: "John Doe"
        role: "Product Manager"
    discord_channel_ids: ["1234567890123456789"]
    drive_folder_ids:
      tech: "1abcDEF..."
      commercial: "1xyzGHI..."  # only in commercial registry
    hubspot_company_id: 12345    # only in commercial registry
    hubspot_deal_ids: [67890]    # only in commercial registry
    fathom_keywords: ["acme", "acme corp"]
    status: active
    started: 2026-02-15
```

Maintaining the registry is the primary operational task. When a new project starts, an entry is added. When a project ends, the status changes to `archived`. When a client adds a new stakeholder, their email is added to the contacts list. This is done by the operational owner (typically Andreea) and the PRs are reviewed by a co-founder before merging.

## Source-by-source routing

Each source has its own routing logic because the available signals differ. The principle is the same — match to a project, default to "unrouted" if no match is confident enough — but the specifics vary.

### Fathom

Fathom is the highest-value source and has the cleanest routing signals. Fathom can be configured to email a summary or transcript when a meeting ends. We point this email at an ingestion address (`fathom@cube-digital.io`).

Routing happens in two passes:

1. **Title keyword match.** If the meeting title contains a registered alias (`[acme]`, `Acme weekly sync`, etc.), the project is matched directly. This is the high-confidence path.
2. **Attendee email match.** If no title match, the attendee list is checked against the contacts and domains in the registry. A match by domain gives moderate confidence; a match by specific email gives higher confidence.

If neither matches, the transcript goes to `unrouted/fathom/` for manual review. The operational owner triages this folder weekly.

The discipline here is calendar invite hygiene. We ask the team to put `[acme]` (or the relevant alias) in calendar invite titles. This is a thirty-second habit that makes Fathom routing 99% reliable. Without it, we fall back to attendee matching, which works but is fuzzier and produces more unrouted items.

After routing, the Fathom flow is:

1. Raw transcript committed to `cube-context-commercial/projects/<slug>/raw/fathom/<date>.txt`
2. Commercial distiller produces `projects/<slug>/meetings-comm/<date>.md` in the commercial vault
3. Team distiller produces a candidate `projects/<slug>/meetings/<date>.md` for the team vault
4. Leakage scanner checks the team output
5. Commit or PR per the scanner result

### Gmail

Gmail is fundamentally a mixed-content source. The same mailbox contains personal correspondence, internal team email, vendor communication, and project-specific client threads. We do not auto-ingest entire mailboxes; we ingest project-tagged threads explicitly.

Two routing patterns work. We start with the first and move to the second if needed.

**Pattern 1: forwarding to project aliases.** We set up two ingestion addresses per project: `projects+acme@cube-digital.io` and `projects-comm+acme@cube-digital.io`. When a team member receives a project-relevant email, they forward it to the appropriate alias. The ingestion service polls these aliases via IMAP, parses each forwarded message, and routes it directly to the named project.

This pattern requires the forwarder to make a binary decision: is this team-shareable or commercial? For most threads the answer is obvious. For mixed threads, the forwarder either splits the thread (forward the team-relevant messages to the team alias, the commercial parts to the commercial alias) or forwards to the commercial alias by default, where a distiller will produce a team-safe summary.

**Pattern 2: label-based ingestion.** Each user sets up Gmail labels `vault/acme-team` and `vault/acme-commercial`. When they read a thread, they apply the appropriate label. A Gmail watcher (using the Gmail API with the user's OAuth consent) detects newly-labeled threads and ingests them. This requires per-user OAuth setup but eliminates the forwarding friction.

We use Pattern 1 for v1 because it requires no API integration and works for any team member who can forward an email. We move to Pattern 2 if the forwarding friction becomes a real cost.

The Gmail flow is otherwise similar to Fathom: raw to commercial, two distillations, leakage check, commit.

### HubSpot

HubSpot is purely commercial. It does not write to the team vault under any circumstances.

The ingestion service polls HubSpot daily (with webhooks for stage changes if available) and snapshots key fields for each tracked deal:

- Deal stage, value, close date, owner
- Associated company and contacts
- Recent activity log
- Notes added since last snapshot

Each snapshot is written as JSON to `cube-context-commercial/projects/<slug>/raw/hubspot/<date>-snapshot.json`. A small distiller produces a human-readable `projects/<slug>/_deal.md` that overwrites on each snapshot, and appends a delta to `projects/<slug>/deal-history.md` so the change history is preserved.

The team vault never receives HubSpot data. If a developer needs to know whether a project is active, they read the project's `status` field in the registry, which is manually maintained and contains no commercial signal.

### WhatsApp

WhatsApp is the operationally hardest source because there is no clean API for ingestion of personal WhatsApp accounts. The WhatsApp Business API is paid and limited to business-initiated conversations; scraping WhatsApp Web is fragile and against the terms of service.

For v1, we do not automate WhatsApp ingestion. Two manual paths are supported:

**Periodic export.** Every two weeks, the operational owner exports the WhatsApp chat for each active project (using WhatsApp's built-in export feature) and drops the export into `cube-context-commercial/projects/<slug>/raw/whatsapp/<date>.txt`. A distiller runs over it and produces a team-safe summary in `cube-context-team/projects/<slug>/chats/<date>-whatsapp.md`. Commercial-relevant content goes to the commercial vault.

**Quote on demand.** When a team member references "Maria said in WhatsApp...", they paste the relevant snippet into a project note manually. This is the lowest-friction path for occasional reference but doesn't scale to high-traffic chats.

If WhatsApp becomes a high-value source for any specific project, we invest in proper ingestion using a self-hosted bridge (e.g., Baileys) or the WhatsApp Business API. We do not build that infrastructure speculatively.

### Discord

Discord is structured by channel. The registry maps Discord channel IDs to project slugs. A Discord bot in our server listens for messages in mapped channels.

Routing is deterministic: messages from a registered channel are routed to that channel's project. By default, Discord channels are internal team discussion and route to the team space. A channel suffix convention identifies commercial channels: `#acme-tech` routes to the team space, `#acme-comm` routes to the commercial space.

The bot batches messages by day rather than committing each message individually. Each day at midnight, the previous day's messages from each channel are aggregated, summarized by a distiller (extracting decisions, action items, and substantive discussion while dropping social noise), and committed to `projects/<slug>/chats/discord-<date>.md`.

Discord is the lowest-friction source after Fathom because routing is exact and the volume per channel is manageable.

### Drive

Drive is not ingested in the sense of copying file contents into the vaults. Drive files are indexed: the system reads file metadata (title, type, last-modified, link) and produces an index page in the appropriate vault.

The convention is:

- `Drive/Projects/<Project>/Tech/` is indexed in the team vault
- `Drive/Projects/<Project>/Commercial/` is indexed in the commercial vault
- Files added to either folder appear in the index within 24 hours

For Google Docs specifically, the indexer can additionally pull a short summary of the document and include it in the index entry. This gives the vault index meaningful previews without duplicating the full document content.

The team vault index lives at `projects/<slug>/docs/index.md`. It looks like:

```markdown
# Acme Corp - Documents

## Architecture
- [System architecture v2](https://docs.google.com/document/d/...) — last updated 2026-05-08
  Two-page summary of the planned architecture for the Acme integration.
- [API contract](https://docs.google.com/document/d/...) — last updated 2026-05-03

## Meeting prep
- [Kickoff prep](https://docs.google.com/document/d/...) — last updated 2026-02-15
```

The files themselves stay in Drive. The vault just helps you find them.

## The distillers

Distillers are the LLM-powered transformers that turn raw artifacts into curated markdown. There is one distiller class per source-and-audience combination: `FathomTeamDistiller`, `FathomCommercialDistiller`, `GmailTeamDistiller`, and so on.

Each distiller is essentially a system prompt plus a small wrapper that calls the Anthropic API. The prompt is stored as a markdown file in the source tree (`distillers/prompts/fathom_team.md`) and loaded at runtime. This keeps prompts versioned in git alongside the code.

### The team distiller for Fathom (the load-bearing prompt)

The Fathom team distiller is the most important prompt in the system. Its job is to extract technical, decision-relevant content from a meeting transcript while reliably excluding commercial content. The prompt has three sections:

The first section establishes the role and the output format. It tells the model it is summarizing for a technical execution team, in a specific markdown structure with frontmatter, headings, and lists.

The second section is the **critical exclusions**. This is the heart of the prompt. It lists categories of content that must never appear in the output:

- Specific monetary amounts, prices, rates, or budget figures
- Discussion of deal stage, contract terms, or commercial negotiation
- Margin, profitability, or revenue commentary
- Internal commercial strategy or competitive positioning
- Discussion of other clients or unrelated commercial matters
- Personal or political commentary about the client's staff
- Mentions of the client's commercial relationships with their own competitors

The exclusions are framed as content the model should silently omit, not redact with markers. A "[redacted]" or "[commercial content removed]" placeholder would itself leak information by signaling that something was there. The prompt explicitly instructs the model to write a coherent summary as if the excluded content had never been said.

The third section is the **inclusions**: what the model should extract. Technical decisions, scope discussions, architecture choices, action items with owners, open questions, client requests with technical implications. This is the substance of the summary.

There is also a fallback rule: if the meeting was entirely commercial with no technical content to summarize, the output is a minimal stub with `content_type: commercial-only` in frontmatter, indicating no team-relevant content exists. This is preferable to forcing the model to invent technical content.

### The commercial distiller for Fathom

The commercial distiller is much simpler. Its prompt asks for a complete summary covering all aspects of the meeting — technical, commercial, relational, strategic. There is no filtering. The output goes only to the commercial vault.

### Distillers for other sources

The pattern for other sources is the same: a system prompt with exclusions and inclusions specific to the source's content. Discord summaries have additional exclusions for social chatter. Gmail summaries focus on the substantive content of a thread rather than the conversational mechanics. HubSpot snapshots produce structured human-readable summaries with no filtering needed (since HubSpot data is always commercial).

Each distiller's prompt is reviewable, version-controlled, and refined over time. When we update a prompt, we bump the `distiller_version` in the frontmatter of generated content. We can re-run distillation over historical raw artifacts when a prompt improves significantly.

## The leakage scanner

The leakage scanner is the last automated check before content lands in the team vault. It is a deliberately simple, fast, regex-based scan.

The scanner looks for:

- Currency symbols: €, $, £, ¥, and the words "EUR", "USD", "GBP"
- Monetary patterns: numbers followed by "k" or "m" or in the format of money (e.g., `1,500` or `1.5M`)
- Specific keywords: "margin", "markup", "rate card", "deal value", "pipeline", "contract value", "ARR", "MRR"
- Competitor names from a list in the configuration
- Discount and pricing language: "discount", "rebate", "% off"

Hits are not automatic rejections. They are flags that route the team-vault commit through a pull request instead of an auto-merge. The PR description includes the scanner's findings, the relevant excerpts, and a link to the raw transcript in the commercial vault. A human reviews and either merges (if the flag was a false positive — "the discount applies to the academic license" is technical context, not a leak) or rejects and updates the prompt.

The scanner is not a security boundary. It is a calibration aid. Its job is to catch what the prompt missed during the first month, so we can iterate the prompt until the scanner is rarely firing. After the first month, scanner hits are infrequent enough that human review is fast and a PR is the right interaction model.

## The ingestion service: technology stack

The ingestion service is a Django application sharing a single Django project with the Donna chat server. Key dependencies:

- **Django** with **Django REST Framework** for the webhook receiver views (`/webhooks/fathom`, `/webhooks/discord`, etc.) and the Donna chat API
- **Daphne** or **Uvicorn** as the ASGI server — required for SSE streaming on the chat side; the webhook views work fine under WSGI, but ASGI covers both surfaces in one process
- **System cron** or **django-q** for polling jobs (Fathom email fallback, Gmail IMAP, daily HubSpot snapshot, Drive index)
- **Django ORM** with **SQLite** for state, with the option to migrate to Postgres without schema changes
- **GitPython** for committing to the vaults
- **anthropic** SDK for the Anthropic API with prompt caching enabled (distiller prompts are long and repeated, caching cuts cost significantly)
- **structlog** or **Loguru** for logging
- **discord.py** for the Discord bot
- **imapclient** for Gmail polling

The combined Django project has multiple entry points: a Daphne process serving HTTP and SSE, a separate worker process for scheduled polling and the Discord bot (run as a Django management command), and a CLI for ad-hoc operations such as manual distillation triggers or registry reloads. It's deployed in a Docker container on a Hetzner VPS or Cloud Run. The container mounts the two vaults as volumes and pushes commits via SSH using a deploy key. The Django admin is exposed on an internal-only port for hand-maintaining the project registry and inspecting state. Choosing Django over FastAPI here is operational consistency: one framework, one deployment unit, one set of conventions for ingestion *and* the Donna chat server. The full reasoning lives in the decisions document.

For full structural details (project layout, models, key code paths), see the technical implementation in the `implementation` section of the operational playbook or the codebase README.

## What happens when ingestion fails

Several failure modes exist and each has a defined recovery:

**Webhook fails to receive.** The webhook endpoint is behind a reverse proxy that returns 503 if the service is down. Most sources (Fathom, HubSpot) retry. Discord events are replayed by the bot's session resume. If a webhook is dropped permanently, the raw artifact may be missed; this is rare and we accept the risk for now.

**Routing finds no match.** The artifact lands in `unrouted/<source>/` in the commercial vault. The operational owner reviews this folder weekly. Common causes: a new project hasn't been added to the registry yet, or a calendar tag was missing. Fix the cause, then re-route the artifact manually using the CLI.

**Distillation fails.** If the Anthropic API call errors, the service retries with backoff. If retries exhaust, the artifact's raw is preserved in the commercial vault, the failure is logged, and an alert fires. The operational owner re-runs the distillation manually after addressing the cause (API outage, prompt too long, etc.).

**Leakage scanner flags.** The team commit goes to a PR instead of being merged automatically. The PR is reviewed and either merged or rejected. If the same pattern flags repeatedly with false positives, the scanner's rules or the distiller's prompt is adjusted.

**Vault push fails.** The local commit succeeds but the push to GitHub fails (network issue, auth failure). The service retries; if it still fails, the commits sit in the local working copy and the next successful push includes them. State is consistent because the local vault is the truth.

**SQLite corruption.** SQLite is robust, but in the unlikely case of corruption we restore from nightly backup and reprocess any artifacts received since the backup. The dedup logic prevents duplicates; reprocessing is safe.

## Operational notes

A few things worth knowing for anyone operating the pipeline:

The pipeline is **single-tenant**. It is built for Cube-Digital, with our project registry, our access list, our prompts. Productizing it for other agencies is possible but not trivial — at minimum, multi-tenancy in the registry, per-tenant prompts, and isolated vaults would be needed.

The pipeline is **opinionated about discipline**. Calendar invite naming, Gmail forwarding, Discord channel naming — these are conventions the team must follow for routing to work. The operational playbook covers the conventions; onboarding new team members includes a walkthrough.

The pipeline is **observable but not over-instrumented**. Logs go to Loguru with structured fields; the state DB has the audit trail; commits are the visible history. We do not have Prometheus metrics, distributed tracing, or any heavyweight observability stack. If the pipeline misbehaves, the SQLite query plus the git log usually answers what happened.

The pipeline is **conservatively designed for our scale**. We could ingest ten times more without architectural changes. Beyond that, we would queue distillation jobs (currently synchronous), add an indexer for fast cross-vault search, and possibly shard the registry. None of this is needed today.
