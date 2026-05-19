# Architecture

## The system in one paragraph

Donna is a multi-tenant, Slack-shaped chat application with a Claude Cowork–style agent embedded in every channel. A **Workspace** is the tenant root; users (identified globally by email) join workspaces by membership. Inside a workspace, channels host messages, agent conversations, and collaborative documents. Sensitive content is structurally separated by **private channels with restricted membership** — no application-level filtering, no per-record tier tags. External integrations (Fathom, Gmail, Discord, Drive, HubSpot) are configured per workspace via OAuth and feed knowledge that any channel in that workspace can reference. The whole system runs as one Django project serving REST endpoints, SSE streams, and the agent runtime.

## Workspaces are the tenant boundary

A workspace is owned by whoever creates it and exists in isolation from every other workspace. Users (`User`) are global identities keyed by email; the same email can be a member of many workspaces (this is the Slack model — Cube-Digital is one workspace among many, not a special case).

- **Creating a workspace** is open to any authenticated user. The creator becomes `OWNER` automatically.
- **Inviting members** is the only mechanism to grow a workspace; there is no global directory.
- **Workspace-scoped resources** (channels, messages, agent sessions, documents, ingested content, OAuth tokens granted at workspace level) cannot leak across tenants. Every query is filtered by the active workspace at the data layer.

## Header-based multi-tenancy (not URL-nested)

The active workspace is communicated via an **`X-Workspace-Id` header** on every request, not via a URL prefix like `/workspaces/{id}/channels/...`. A `WorkspaceMiddleware` resolves the header, loads the workspace, and attaches it as `request.workspace` (with `request.company` aliased for compatibility with `core/`'s tenant-aware service base class).

| | URL-nested (rejected) | Header-tenanted (chosen) |
|---|---|---|
| URL shape | `/workspaces/{ws}/channels/{id}` | `/channels/{id}` (+ header) |
| Tenant source | URL path parameter | HTTP header |
| Client SDK ergonomics | Repeated path params per call | Set header once per session |
| Visibility of scope | Visible in URL | Hidden in header |
| Common in | Older REST APIs | Stripe, Linear, GitHub Apps |

**Trade-offs we accepted:** the workspace ID isn't visible in URLs (less self-describing in logs), and we depend on a single middleware to enforce tenant scope correctly. We mitigate the second with object-level permission checks at the viewset layer.

**Endpoints exempt from the header requirement:** `POST /api/v1/workspaces` (creating a tenant), `GET /api/v1/workspaces` (listing the caller's tenants), and the auth/admin/health paths. These live in `IGNORED_PATHS` on the middleware.

## Channels and sensitivity

Channels are rooms within a workspace. Two visibility modes:

- **Public** — every workspace member can join and see.
- **Private** — invite-only; non-members can't see the channel exists.

Private channels are how sensitivity is enforced. The original `/docs/` design had two separate git vaults (team and commercial) for the same conceptual reason; in the chat model the principle ("access via architecture, not policy") moves down one level — from repo to channel.

**Direct messages are channels with `kind=DIRECT`.** Group DMs are just DIRECT channels with more members. This avoids duplicating the message/membership/agent infrastructure into a parallel model. DM identity is the participant set, enforced by a service-layer `get_or_create` rather than a derived DB column for now.

## The agent: one session per channel

Every channel has an `AgentSession` — a persistent piece of state owning the agent's memory, configuration, and message authorship within that channel. The relationship is **N:1 with Channel**, not 1:1, so future personas (different agents specialized for different tasks) can coexist in the same channel without restructuring.

- **History** is the channel's `Message` log filtered by `author_agent` — not a separate field on `AgentSession`.
- **Memory** is a JSON field on `AgentSession` for v1; can later point to an external store (Mem0 or similar).
- **Config** holds per-channel overrides: model, tool allowlist, system prompt fragments.
- **Tools the agent has access to** are intersected with the requesting channel's tier — a private channel's agent can read its own contents; a public channel's agent cannot read private channel data.

The agent is always single-agent-per-conversation. We don't ship multi-agent orchestration; that's earned when a specific workflow demands it.

## OAuth integrations

External providers (Fathom, Gmail, Discord, Drive, HubSpot, etc.) are configured via two models:

- **`OAuthProvider`** — global, holds provider config (client_id, scopes, endpoints).
- **`OAuthToken`** — per provider × (user XOR workspace). A user can enable a provider for themselves only, OR enable it on behalf of the entire workspace (token shared, usable by all members). A `granter` field records who authorized.

This is distinct from app login — `OAuth*` models exist to authenticate Donna against external services, not to log users into Donna.

Ingested content from these providers lives at workspace scope and is referenceable from any channel inside that workspace. The exact model for storing distilled artifacts (transcripts, threads, snapshots) is **deliberately open** — a `KnowledgeItem` model was proposed and then dropped; landing strategy is TBD before ingestion is built.

## What we deliberately don't build

- **Per-record access tiering** — sensitivity = channel membership, full stop.
- **A god agent with full context and output filtering** — agents only have tools they're permitted to use, never "all tools with downstream filtering."
- **Multi-agent orchestration as a starting point** — single-agent per channel until a real workflow demands more.
- **Real-time ingestion** — content lags by minutes to hours; we trade latency for reliability.
- **Threading, reactions, attachments in v1** — explicitly deferred; the message model can be extended later without breakage.

## Open

- **Auth mechanism for app login** (JWT vs Django session) — affects every endpoint; not yet decided.
- **Ingested content landing model** — where do distilled provider artifacts live? Possibly Documents in a designated channel, possibly workspace-scoped `KnowledgeItem` (rejected once, may need revival), possibly out-of-Django storage with an index.
- **DM dedup approach** — service-level `get_or_create_dm()` for v1; member-set hash column may follow if it bites.
- **Agent trigger semantics** — @mention, slash command, or always-on per-channel toggle.
- **SSE replay backend** — Redis (per the original docs) or in-memory for v1.
- **LLM provider abstraction** — LiteLLM (the CLAUDE.md in `core/` promises it) vs direct Anthropic SDK with prompt caching.
