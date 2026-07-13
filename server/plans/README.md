# Implementation plan

This directory documents the **target architecture and build sequence** for the Donna server. It supersedes the broader product-vision docs at the repo root (`/docs/`) wherever the scope has evolved.

## What changed from `/docs/`

The original docs described an internal Cube-Digital tool with a two-vault git-based architecture for one tenant. We've since pivoted:

- **Multi-tenant** product from day one — anyone can create a workspace; users belong to many.
- **Slack-shaped ✕ Claude Cowork** consumption surface — channels, messages, collaborative documents, agent in every channel.
- **Vaults dissolved** as a product primitive. Sensitivity becomes "private channels" (membership-gated), which is the same structural principle applied at a finer grain.
- **Single Django project** (`donna/`) for everything: chat, agent, ingestion, OAuth, admin. No separate microservices.

The `/docs/` files remain useful as background on the original problem and trust model, but the implementation here is the source of truth.

## Reading order

1. [01-architecture.md](01-architecture.md) — target system at a glance; multi-tenancy, agent model, channel model, OAuth.
2. [02-data-model.md](02-data-model.md) — every model, its scope, its relationships, and the rejected alternatives.
3. [03-conventions-and-api.md](03-conventions-and-api.md) — standard app layout, service/view/serializer patterns, the 20-endpoint API surface for workspaces + channels.
4. [04-roadmap.md](04-roadmap.md) — what's done, what's blocking, the phase-by-phase build sequence.
5. [05-integration-architecture.md](05-integration-architecture.md) — tiered approach (deep custom / agent-action / long-tail sync), the `donna/integrations/` framework, silver-layer model, staged migration from custom-build to platforms, n8n deployment model.
6. [06-deployment-and-self-hosting.md](06-deployment-and-self-hosting.md) — Donna Cloud vs on-premise, plain workers (Celery + Redis), S3-compatible storage, BYO OAuth flow per provider, OSS license decision, Helm chart aspiration.
7. [08-connection-pattern.md](08-connection-pattern.md) — single polymorphic `Connection` model (one row per workspace/user/provider), JSON `config` + JSON `state`, per-connector `config_schema` (JSON Schema), industry-validated against Airbyte / Nango / Singer / n8n / Hookdeck.
8. [08a-gmail-integration.md](08a-gmail-integration.md) — Gmail subscription config: `everything` / `time_window` / `subscriptions` modes; labels + queries + domains (OR-combined); label picker; per-stream state shape.
9. [08b-google-drive-integration.md](08b-google-drive-integration.md) — Drive integration: hybrid Google Picker + custom folder browser; progressive OAuth scope (`drive.file` → `drive.readonly` upgrade); v1 file-type coverage; Shared Drives included.
10. [09-auth-and-notifications.md](09-auth-and-notifications.md) — User authentication (email/password + Google login + password reset + email verification) and in-app notifications (DB feed + SSE). Cherry-picked from narrio's production code.
11. [10-realtime-layer.md](10-realtime-layer.md) — Realtime architecture: SSE per-(user, workspace) for notifications + Django Channels WebSockets for chat / DMs / presence / agent token streaming. One Redis pubsub backbone, two transports.
12. [11-nango-integration.md](11-nango-integration.md) — Nango as the long-tail fleet for low-priority connectors; relationship to the Tier 1 (custom) integration framework.
13. [12-deployment-pipelines.md](12-deployment-pipelines.md) — Cloud GitOps + self-host tagged releases (GHCR + Helm); settings split; Dockerfile + entrypoint hardening; CI/CD workflows. Coordinates w/ [13](13-agent-runtime-maturity.md) Phase 3.4 on the `worker-io` / `worker-cpu` compose split.
14. [13-agent-runtime-maturity.md](13-agent-runtime-maturity.md) — Drafting, memory, multi-agent, automation. Eight-phase build sequence taking the chat agent from generic to channel-resident ambient teammates. Renamed 2026-06-25 from the original "Claude Code pattern adoption" framing — every pattern is adopted *because* it serves Donna's Cowork shape, not because Donna is becoming Claude Code.
15. [14-frontend-integration.md](14-frontend-integration.md) — Eight frontend feature deliverables; tracks the web client against the backend phases shipped by 09, 10, 13.
16. [15-remaining-roadmap.md](15-remaining-roadmap.md) — Consolidated index of what's left across plans 11, 12, 13, 14 + cortex. Fourteen phases tier-ordered S/A/B/C with cross-references back to each originating plan. Refreshed 2026-06-28 from the post-v1 audit.

## Reference / deep dives

These aren't plans — they're learning material gathered during the design sessions. Read them to understand the background reasoning, the landscape, and the design vocabulary the plan docs use.

- [07-integration-platform-landscape.md](07-integration-platform-landscape.md) — how n8n, Airbyte, Nango, Composio, Activepieces structure their integrations; framework-vs-procedural patterns; build-vs-buy economics with concrete numbers; MCP and the AI-native integration shift; self-hosting infrastructure patterns; OSS license landscape; webhook reliability; a decision framework for new products.
- [whats-app-integration.md](whats-app-integration.md) — **documented-only**, not yet implemented. Baileys sidecar architecture for personal WhatsApp accounts; QR-code pairing; per-chat subscriptions; cross-user dedup via `WhatsAppMessageSeen`; ban-risk mitigations; future Business Cloud API path.

## Status snapshot (kept in 04)

- **Models** for users, workspaces, and chat are committed on `main` (3fe3856).
- **Workspace module** (services, serializers, viewsets, permissions, admin, urls) is implemented and wired into `/api/v1/`.
- **Settings, middleware, migrations, and auth** are not yet runnable — see [04-roadmap.md](04-roadmap.md#phase-0--foundation) for the unblock list.

## How to maintain this set

- **Decisions land in the roadmap.** When a design decision is made — whether through discussion, research, or implementation — it gets captured in [04-roadmap.md](04-roadmap.md) as a concrete work item under the relevant phase, AND in the design doc that owns the topic (01-architecture, 02-data-model, 03-conventions-and-api, 05-integration-architecture, 06-deployment-and-self-hosting). Two locations: the *what* in the design doc, the *when/who/how* in the roadmap.
- Update the relevant doc when a design decision lands. Don't write side notes in code or in commit messages and leave the plan stale.
- Keep open questions visible — every doc has an "Open" section. When something is resolved, move it to the body and record the decision; reflect that resolution in 04's "Resolved" list.
- The roadmap (04) drifts fastest; review at the end of each phase.
