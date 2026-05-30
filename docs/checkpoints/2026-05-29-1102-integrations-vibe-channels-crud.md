# 2026-05-29 11:02 — Integrations Vibe + Channel CRUD

## Summary & Overview

Long working session covering five mostly-independent strands: (1) FalkorDB compose service for Graphiti, (2) Fathom OAuth → programmatic webhook lifecycle with per-Connection HMAC secret, (3) frontend storage switch S3 ⇄ local filesystem, (4) sweeping UI vibe pass producing `web/VIBE.md` and applying its rules across the platform, plus a sidebar “Connections” section with brand icons, a `/integrations` catalog, a `/integrations/:slug` detail page, and a schema-driven JSON-Schema config form engine with Gmail-labels and Drive-folders pickers (the right-rail `IntegrationModal` was deleted), and (5) channel CRUD wired end-to-end — backend PATCH + DELETE permissions, frontend create dialog with Slack/Discord `#` UX, and a kebab actions menu on the channel header. Backend `django check` is clean, frontend `tsc --noEmit` is clean, dev preview is running on port 5173.

## Key Learnings

- **FalkorDB ships Redis protocol on 6379 plus a Browser UI on 3000** — same image (`falkordb/falkordb:latest`) serves both. `graphiti_core.driver.FalkorDriver` takes `host, port, username, password, database` and constructs an internal `FalkorDB(...)` client; keep the connection params shape-compatible with `**settings.GRAPH_DB`.
- **Fathom external API has two hosts** — OAuth lives on `https://fathom.video/external/v1/oauth2/*`, the REST API lives on `https://api.fathom.ai/external/v1/*`. They are NOT aliases — `api.fathom.video` does not resolve. Easy to miss because OAuth code paths work first.
- **Fathom webhook destination URLs must be HTTPS.** `http://localhost:8000` returns `400 {"error":"Invalid URL. Must be a valid HTTPS URL."}`. In dev you need a tunnel (ngrok / cloudflared); free ngrok injects an HTML interstitial that blocks vendor-initiated inbound webhooks.
- **Per-webhook secrets break the shared HMAC pattern.** Fathom returns a unique `secret` per registration, so `BaseWebhookHandler.verify()` must accept a `connection` kwarg and read from `Connection.state["webhook"]["secret"]`. The view-layer flow becomes `parse → resolve_workspace → load Connection → verify(connection=...) → dispatch` (parse before verify is normally a red flag — mitigated here because parse is pure JSON and dispatch only happens after verify).
- **OAuth refresh tokens rotate** — calling Fathom's `/oauth2/token` with `grant_type=refresh_token` returns a brand-new refresh token; if you don't persist it immediately the next refresh hits 400. Must `t.save(update_fields=["access_token", "refresh_token", "expires_at"])` in the same call.
- **Atomic OAuth callbacks are double-edged.** `RegistryService.handle_callback` is `@transaction.atomic`, so an exception in `provider.on_connect` rolls back BOTH the token row and the Connection row. Great for invariant maintenance, but during bring-up it means the only way to debug the side effect is to make `on_connect` soft-fail temporarily, otherwise you never get a persisted token to probe with.
- **Fathom has no `/meetings/{id}` endpoint.** Singular reads live on `/recordings/{recording_id}/transcript` and `/recordings/{recording_id}/summary`. Meeting metadata comes from list-endpoint items only — pass that dict through to the ingest task instead of re-fetching by id.
- **`default_storage` is backend-agnostic.** `delivery_packages.storage_key` is a plain string like `"<workspace>/<vendor>/.../<id>.json"`; the same key resolves against MinIO or local FS depending on `DONNA_STORAGE_BACKEND`. Data does NOT migrate on switch — re-ingest or `mc cp` manually.
- **Electron and the web app share one bundle**, period. `desktop/main.ts` either does `win.loadURL("http://localhost:5173")` (dev) or `win.loadFile("../../web/dist/index.html")` (prod). All the Slack/Linear/Discord/Notion/Postman/VS Code crowd does this. Hardening lives in the Electron shell (`contextIsolation`, preload, code signing) — not in forking the UI.
- **`UserAuditMixin` field is `modified_by`, not `updated_by`.** Pre-existing channel create code passed `updated_by=request.user` which silently 500'd. Always `grep` the mixin definition before assuming field names.
- **Vibe enforcement boils down to five recurring drifts**: custom-pixel `rounded-[Npx]` values, `text-[13.5px]` overshoots, ad-hoc pill heights (`h-[26px]`), tracking inconsistency (`0.06em` vs `0.04em`), and oklch hover vs `bg-bg-2`. Lock with `rg` greps; `web/VIBE.md` documents the rules.
- **JSON Schema `allOf` conditionals model Gmail/Drive's mode-gated fields cleanly.** Engine walks each clause: if `if.properties` matches current value, surface `then.required` keys; else hide them AND strip from the PATCH payload so stale data doesn't leak.

## Solutions & Fixes

- **Fathom OAuth callback 500 — `[Errno -2] Name or service not known`** → API host wrong. `FathomClient.base_url` changed from `https://api.fathom.video/external/v1` to `https://api.fathom.ai/external/v1`.
- **`fathom_create_webhook_failed status=400 body='{"error":"Invalid URL. Must be a valid HTTPS URL."}'`** → `DONNA_PUBLIC_BASE_URL` defaulted to `http://localhost:8000`. Wired ngrok URL in `server/env/.env.docker`; documented requirement in `server/donna/settings.py`.
- **`OAuthToken matching query does not exist` in `ingest_fathom_meeting`** → Task did `OAuthToken.objects.get(provider__slug=..., workspace_id=workspace_id)` but Fathom is user-scoped (`workspace_id IS NULL`). Refactored to look up via `Connection.objects.select_related("token").get(workspace_id=..., provider_slug="fathom")`.
- **404 on every `GET /meetings/{id}`** → endpoint doesn't exist. Rewrote `FathomClient` to expose `list_meetings`, `iter_meetings`, `get_transcript(/recordings/{id}/transcript)`, `get_summary(/recordings/{id}/summary)`. Task now accepts `meeting: dict` from list-item / webhook payload; only fetches transcript+summary.
- **Vite proxy ECONNREFUSED on `/api/auth/signin`** → backend runs on host port `8190` (per `docker-compose.yml`), `vite.config.ts` proxy defaulted to `:8000`. Wrote `web/.env` with `VITE_API_PROXY_TARGET=http://localhost:8190`.
- **Vite pre-transform failures — 4 missing `lib/*` files** → `web/src/lib/` didn't exist. Wrote `auth-storage.ts`, `hueForAgent.ts`, `ws.ts` (singleton WebSocket with auto-reconnect; `action`/`event` envelope matches `ChatConsumer`), `sse.ts` (EventSource singleton; query-param auth because EventSource can't send headers).
- **`Expected corresponding JSX closing tag for <Link>`** → Sidebar conversion left a `</button>` after switching the outer element to `<Link>`. Replaced.
- **TS error: `MessageWsPayload` index-signature `unknown` rejected in `fromEvent`** → narrowed payload type to discriminated optional fields (`id?`, `body?`, etc.) and added `!` asserts in the create/update-only `fromEvent` consumer.
- **`Channel() got unexpected keyword arguments: 'updated_by'`** → mixin field is `modified_by`. Fixed both `ChannelListCreateView.create` (pre-existing bug) and the new `ChannelDetailView.partial_update`.
- **`Unexpected token '<', "<!DOCTYPE "... is not valid JSON`** in CreateChannelDialog → backend was returning a 500 HTML page (same `updated_by` bug). Fixed via the above.

## Decisions Made

- **FalkorDB use case: Graphiti knowledge graph.** Backed `graphiti-core[falkordb]` already in `pyproject.toml`. Browser UI exposed on port 3001 (host). No password in dev (matches Postgres/Redis posture). Single shared compose volume `falkor_data`.
- **Fathom webhook destination = detail-page URL via `DONNA_PUBLIC_BASE_URL`.** New setting, separate from `WEB_REDIRECT_HOST` because the frontend host and backend host differ. `WEB_REDIRECT_HOST` targets the SPA; `DONNA_PUBLIC_BASE_URL` targets the backend for vendor callbacks.
- **Per-Connection HMAC secret stored on `Connection.state["webhook"]["secret"]`** in plain JSON for v1. `EncryptedTextField` migration deferred. Documented in `server/plans/fathom-webhook-lifecycle.md`.
- **Connector-specific webhook handler subclass over base modification.** `FathomWebhookHandler.verify(connection=...)` knows to look up its secret on `Connection.state`; base handler keeps its `ClientCredentials.webhook_secret` fallback for Gmail/Drive/etc.
- **`on_connect` failures re-raise to trigger `@transaction.atomic` rollback.** Reverted from the temporary soft-fail used during bring-up.
- **Storage backend = local filesystem in dev**, bind-mounted at `server/var/storage/`. MinIO config kept commented in `.env.docker` for one-line revert. GCS / Azure branches in `settings.py` retained but flagged in plans for removal.
- **Web codebase shared between desktop (Electron) and browser.** No fork. Production hardening lives in Electron shell — preload script + sandbox + code signing — not in UI divergence.
- **Hot reload for desktop main process via `electronmon` + `tsc --watch`** in `npm run start:dev`. Renderer HMR comes free via Vite.
- **Vibe = PostHog × Linear × Slack — dense, monochrome chrome, brand-only color, hairline borders.** Codified in `web/VIBE.md` with exact tokens, sizes, radii, hover rules, type scale, status indicators. All future component PRs must conform.
- **`/integrations` catalog filters via top tab strip** (All / Connected / Available) + client-side search. Slack pattern. Sidebar facets deferred until ≥30 connectors.
- **Form rendering = hybrid schema-driven + per-connector pickers.** Generic engine walks JSON Schema (enum→Select, bool→Toggle, integer→Number, array<string>→MultiSelect, string→Input). `(slug, field)` registry slots in Gmail labels + Drive folders custom widgets.
- **Form library = handwritten primitives in `components/Ui/`.** No external dep (react-hook-form, radix). Total ~250 LOC. Tailored to VIBE.md.
- **Connect / disconnect / configure live on the detail page only.** `IntegrationModal.tsx` deleted; right-rail `ContextSection` rows became `<Link>` to detail.
- **Channel create dialog = Slack/Discord vibe.** Single `#`-prefixed name input, auto-normalized to lowercase + dashes as user types. Slug + topic dropped (editable later via kebab). Public/Private toggle.
- **Channel update / delete restricted to channel admin role.** Backend `_require_admin` gate in `partial_update` + `destroy`.

## Pending Tasks

- [ ] Set `DONNA_PUBLIC_BASE_URL` to a real (not free-tier-interstitial) tunnel before reconnecting Fathom for end-to-end webhook delivery. Cloudflared recommended.
- [ ] Confirm the `X-Fathom-Signature` header name guess against the first real webhook delivery. Currently a TODO in `FathomWebhookHandler`.
- [ ] Investigate why Fathom `/recordings/{id}/summary` returns `{}` (4 bytes) — likely plan-tier or scope gated. Adapter currently drops summary anyway.
- [ ] AppShell right-rail (320px) is rendered on every route, cramping the `/integrations` and `/integrations/:slug` pages. Either gate it via `useLocation` on integration routes, or collapse the grid template.
- [ ] Investigate weird `/integrations` card text in screenshot — looked like `meeting_trans` etc. rendered above the icon row. Could be backend `display_name` swap or pure narrow-column truncation. Use `preview_inspect` / `preview_snapshot` to verify.
- [ ] Trim GCS + Azure storage branches from `server/donna/settings.py` (and matching env vars / pyproject extras) — confirmed dropped.
- [ ] Promote channel rename + topic from `window.prompt` to proper inline dialogs for consistency with the Create flow.
- [ ] Add channel member-management endpoints (add/remove user, change role). Currently no API surface.
- [ ] Add `gsd-docs-update` / similar to keep `server/plans/02-data-model.md` and `08-connection-pattern.md` in sync with `state["webhook"]` shape addition.

## Errors & Workarounds

- **`Failed to resolve import "../lib/auth-storage" from "src/state/auth.ts"`** — Vite pre-transform. Cause: `web/src/lib/` directory entirely missing. Fix: wrote the four missing files (`auth-storage`, `ws`, `sse`, `hueForAgent`). Proper fix already applied.
- **`[Errno -2] Name or service not known` on `https://api.fathom.video/external/v1/webhooks`** — `httpcore.ConnectError` raised through `httpx.ConnectError`. Wrong host. Fix: `FathomClient.base_url = "https://api.fathom.ai/external/v1"`.
- **`Client error '400 Bad Request' for url 'https://api.fathom.ai/external/v1/webhooks'`** — Logged `body='{"error":"Invalid URL. Must be a valid HTTPS URL."}'` from new error-capturing block. Fix: set `DONNA_PUBLIC_BASE_URL` to HTTPS tunnel.
- **`Client error '404 Not Found' for url 'https://api.fathom.ai/external/v1/meetings/146737694'`** — singular endpoint doesn't exist. Fix: refactored client + task signature to use `/recordings/{id}/...`.
- **`OAuthToken matching query does not exist.`** — task lookup keyed by `workspace_id` but Fathom token rows have `workspace_id IS NULL`. Fix: lookup via `Connection`.
- **`Channel() got unexpected keyword arguments: 'updated_by'`** — pre-existing typo. Fix: `modified_by` matches `UserAuditMixin`.
- **`Unexpected token '<', "<!DOCTYPE "... is not valid JSON`** — frontend symptom of the above backend 500. Cleared when backend fix landed.
- **`[hmr] Failed to reload /src/components/Shell/Sidebar.tsx. This could be due to syntax errors`** — transient after a partial Edit. Resolved by completing the next Edit and letting watchfiles re-trigger.
- **`AggregateError ... internalConnectMultiple ... ECONNREFUSED`** in Vite proxy log on `/api/auth/signin` — backend was on `:8190`, proxy on `:8000`. Fix: `web/.env` with `VITE_API_PROXY_TARGET=http://localhost:8190`.
- **`donna.integrations.models.ClientCredentials.DoesNotExist`** during a dev probe — running provider methods on a fresh DB without a seeded `ClientCredentials` row. Workaround: probe via the existing connected token row instead of constructing a provider from scratch.
- **ngrok free tier injects an HTML interstitial on first request** — blocks inbound webhook deliveries from Fathom. Workaround: documented, flagged to switch to cloudflared.

## Files Modified

### Server

- `server/docker-compose.yml` — added `graph` (FalkorDB) service with healthcheck + `falkor_data` volume; added `falkor_data` to top-level volumes; added `./var/storage:/var/donna/storage` bind-mount to `server` and `worker`.
- `server/env/.env.docker` — added `GRAPH_*` block; added `DONNA_PUBLIC_BASE_URL`; switched to `DONNA_STORAGE_BACKEND=filesystem` + `DONNA_FILESYSTEM_ROOT`; commented MinIO/S3 block.
- `server/donna/settings.py` — `GRAPH_DB` dict; `DONNA_PUBLIC_BASE_URL` env var.
- `server/donna/core/integrations/provider.py` — added optional `on_connect` / `on_disconnect` Protocol methods.
- `server/donna/core/integrations/webhook.py` — `BaseWebhookHandler.verify(...)` accepts `connection: Connection | None` kwarg.
- `server/donna/integrations/services.py` — `handle_callback` calls `on_connect` inside `@transaction.atomic` (raise rolls back); `disconnect` calls `on_disconnect` before revoke (failures logged + swallowed).
- `server/donna/integrations/api/v1/webhooks.py` — reorder to parse → resolve_workspace → load Connection → verify(connection=...) → dispatch.
- `server/donna/integrations/api/v1/views.py` — `retrieve` enriches IntegrationStatusSerializer payload with `token_scope`, `config_schema`, `default_config`.
- `server/donna/integrations/api/v1/serializers.py` — IntegrationStatusSerializer gains optional `token_scope`, `config_schema`, `default_config` fields.
- `server/donna/integrations/connectors/fathom/client.py` — base_url → `api.fathom.ai`; added `list_meetings`, `iter_meetings`, `get_summary`, `create_webhook`, `delete_webhook`; rewrote `get_transcript` to `/recordings/{id}/transcript`.
- `server/donna/integrations/connectors/fathom/provider.py` — `FathomWebhookHandler` subclass (per-Connection secret); `on_connect` registers webhook + persists `Connection.state["webhook"]`; `on_disconnect` deletes webhook (404-tolerant); `_webhook_destination_url`.
- `server/donna/integrations/connectors/fathom/tasks.py` — task accepts optional `meeting: dict`; uses Connection token lookup; fetches transcript + summary.
- `server/donna/chat/api/v1/views.py` — `ChannelDetailView` → `RetrieveUpdateDestroyAPIView` with admin-gated `partial_update` + `destroy`; `modified_by` field name fix on both create and update.
- `server/donna/chat/api/v1/serializers.py` — `ChannelUpdateSerializer` (all fields optional).
- `server/donna/chat/services.py` — `emit_channel_updated`, `emit_channel_deleted`.
- `server/donna/chat/consumers.py` — `chat_channel_updated`, `chat_channel_deleted` handlers.
- `server/plans/fathom-webhook-lifecycle.md` — new planning doc.

### Web (UI primitives + integrations)

- `web/.env` — `VITE_API_PROXY_TARGET=http://localhost:8190`.
- `web/VIBE.md` — design baseline doc.
- `web/tailwind.config.ts`, `web/src/styles/tokens.css` — minor token additions to support new components.
- `web/src/lib/auth-storage.ts`, `hueForAgent.ts`, `ws.ts`, `sse.ts` — created.
- `web/src/types/index.ts` — `ConfigSchema`; `IntegrationProvider` gains optional `config_schema` + `default_config`.
- `web/src/api/integrations.ts` — `getPicker(slug, resource, params)`; `toProvider` enriched with `token_scope`, `config_schema`, `default_config`.
- `web/src/state/integrations.ts` — `reload()`, `bySlug()`.
- `web/src/components/Ui/BrandIc.tsx` — Gmail / Drive / Fathom SVG glyphs + `ConnectorIcon` dispatcher + `InitialsIc` fallback.
- `web/src/components/Ui/Input.tsx`, `Select.tsx`, `Toggle.tsx`, `MultiSelect.tsx`, `Field.tsx`, `Button.tsx` — new form primitives.
- `web/src/components/Integrations/IntegrationForm.tsx` — schema-driven engine.
- `web/src/components/Integrations/fields/TextField.tsx`, `SelectField.tsx`, `NumberField.tsx`, `ToggleField.tsx`, `MultiSelectField.tsx`, `PickerField.tsx`.
- `web/src/components/Integrations/pickers/registry.ts`, `GmailLabelsPicker.tsx`, `DriveFoldersPicker.tsx`.
- `web/src/components/Integrations/useOAuthConnect.ts` — lifted OAuth popup hook.
- `web/src/views/Integrations.tsx` — catalog (tabs + search + grid).
- `web/src/views/IntegrationDetail.tsx` — detail page (header + form + status).
- `web/src/components/RightRail/RightRail.tsx` — `ContextSection` rows now `<Link>` to detail; brand icons; modal state removed.
- `web/src/components/RightRail/IntegrationModal.tsx` — **deleted**.
- `web/src/App.tsx` — added `/integrations` and `/integrations/:slug` routes.

### Web (vibe pass)

- `web/src/components/Ui/Av.tsx` — `rounded-[5/7/10px]` → `rounded-sm/md/md`.
- `web/src/components/Shell/TopBar.tsx`, `WsRail.tsx`, `Sidebar.tsx`, `ArchiveDock.tsx` — custom pixel radii → Tailwind presets.
- `web/src/components/Channel/Composer.tsx`, `Message.tsx`, `ChannelHeader.tsx`, `AgentRunCard.tsx` — same plus `text-[13.5px]` → `text-[13px]`, `h-[26px]` → `h-6`, agent chip `rounded-sm`.
- `web/src/views/Auth.tsx`, `WorkspacePicker.tsx`, `Personal.tsx`, `ComingSoon.tsx` — vibe drift cleaned (sizes, radii).

### Web (channels)

- `web/src/api/chat.ts` — `createChannel`, `updateChannel`, `deleteChannel` + typed inputs.
- `web/src/state/channels.ts` — mutators + WS event handlers (`upsertFromEvent`, `removeFromEvent`); sortByName indexing.
- `web/src/components/Channel/CreateChannelDialog.tsx` — Slack/Discord vibe: single `#`-prefixed name + public/private toggle.
- `web/src/components/Channel/ChannelHeader.tsx` — `ChannelActionsMenu` (rename / set topic / toggle visibility / delete).
- `web/src/components/Shell/AppShell.tsx` — WS bootstrap subscribes to `channel.created/updated/deleted` → store fanout.
- `web/src/components/Shell/Sidebar.tsx` — `+` next to Channels header opens `CreateChannelDialog`; replaced ConnectionsGroup modal with route navigation; `ConnectionRow` is now a `<Link>` with active-route highlight.

### Desktop

- `desktop/package.json` — added `electronmon` + `tsc-watch`; new `main:watch`, `electron:watch`, `start:dev` orchestrates `web` (vite) + `main` (tsc) + `electron` (electronmon).
- `desktop/dist/main.js` (regenerated by tsc).

## Blockers & External Dependencies

- **Cannot end-to-end test Fathom webhook delivery** until a non-interstitial public tunnel is provisioned. Unblocks when: cloudflared tunnel URL set as `DONNA_PUBLIC_BASE_URL`.
- **`X-Fathom-Signature` header name is a guess.** Unblocks when: first real Fathom webhook arrives in logs and the header name is confirmed (or corrected).
- **Fathom `summary` endpoint returns empty.** Unblocks when: scope / plan tier requirements clarified with Fathom docs or support.
- **`/integrations` cards look cramped + show wrong text.** Unblocks when: AppShell right-rail is gated off integration routes; needs a small layout patch.
- **No channel-member endpoints** for add/remove user, change role. Backend gap. Unblocks when: members API added (plans/02-data-model.md).
