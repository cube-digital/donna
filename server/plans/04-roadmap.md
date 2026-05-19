# Roadmap

## Where we are

### Done

**Models** (committed on `main` as `3fe3856`):

- `users.User` — email-keyed, UUID PK, custom `UserManager`.
- `workspaces.Workspace`, `workspaces.WorkspaceMembership`.
- `chat.Channel` (with `kind` discriminator for DMs and `dm_must_be_private` CHECK), `chat.ChannelMembership`, `chat.AgentSession`, `chat.Message` (with polymorphic-author CHECK constraint), `chat.Document`.

**Workspace module** (uncommitted):

- `workspaces/services.py` — `WorkspaceService`, `WorkspaceMembershipService` extending `BaseService`. Ownership transfer is atomic; "last owner can't leave" enforced.
- `workspaces/api/v1/serializers.py` — read/write split for both resources; minimal embedded `_UserShortSerializer` placeholder.
- `workspaces/api/v1/views.py` — `WorkspaceViewSet`, `WorkspaceMembershipViewSet`, three permission classes inline (`IsWorkspaceMember`, `IsWorkspaceAdminOrOwner`, `IsWorkspaceOwner`).
- `workspaces/urls.py` — router registration.
- `workspaces/admin.py` — Django admin.
- `donna/urls.py` — `donna.workspaces.urls` mounted at `/api/v1/`.

**Tenant middleware** (user-provided in `workspaces/middlewares.py`) — header-based `X-Workspace-Id` resolution, sets `request.workspace` and `request.company`. See "Middleware fixes needed" below.

### Not yet runnable

The code compiles but the project doesn't boot because the foundation isn't wired. The list below is the unblock set, not a critique — it's the natural Phase 0.

---

## Phase 0 — Foundation (blocks everything below)

**Goal:** the project boots, migrations run, `/api/v1/workspaces` actually responds.

1. `**settings.py` from default stub to real config.**
  - `AUTH_USER_MODEL = "donna.users.User"`
  - `INSTALLED_APPS`: `django.contrib.*`, `rest_framework`, `donna.core`, `donna.users`, `donna.workspaces`, `donna.chat`, `donna.authentication`, `donna.authorization`, and the other apps as they're built.
  - DRF defaults:
    - `DEFAULT_RENDERER_CLASSES = ["donna.core.renderers.StandardJSONRenderer"]`
    - `EXCEPTION_HANDLER = "donna.core.exception_handler.custom_exception_handler"`
    - `DEFAULT_PAGINATION_CLASS = "donna.core.pagination.StandardLimitOffsetPagination"`
    - `DEFAULT_AUTHENTICATION_CLASSES` (pending the JWT vs session decision)
    - `DEFAULT_PERMISSION_CLASSES = ["rest_framework.permissions.IsAuthenticated"]`
  - `MIDDLEWARE` with the correct order:
    - Django security/sessions/auth middleware first
    - `donna.core.middleware.LoggingMiddleware` early (to attach request_id)
    - `django.contrib.auth.middleware.AuthenticationMiddleware`
    - `donna.workspaces.middlewares.UserContextMiddleware`
    - `donna.workspaces.middlewares.WorkspaceMiddleware`
  - structlog config: call `donna.core.logging.configure_logging()` at the bottom of settings.
  - ASGI: confirm `ASGI_APPLICATION = "donna.asgi.application"`; needed before realtime (Phase 2) but harmless to set now.
  - Switch `DEBUG`, `SECRET_KEY`, `ALLOWED_HOSTS` to env-driven.
  - Real `DATABASES` config (Postgres or keep SQLite for dev).
2. `**apps.py` files** — all currently say `name = '<app>'`; must be `name = 'donna.<app>'`. Otherwise Django can't import them under the `donna.*` namespace.
3. `**core/` stale imports** — references to `docupal`, `narrio` left over from copy-paste. Locations:
  - `core/viewsets.py:3` (`from docupal.core import generics, mixins`)
  - `core/middleware.py:14` (`from docupal.core.logging import ...`)
  - `core/db/models.py:58` (`KnowledgeLinkable.link_knowledge` imports `narrio.knowledge.models.KnowledgeLink`)
  - `core/apps.py` (references `docupal.core.logging` and `docupal.core.qdrant_helpers`)
  - `core/logging.py:104` (`event_dict.setdefault("service", "narrio-api")`)
  - Either rename to `donna.*` or delete the dead code (`KnowledgeLinkable` is unused; the `qdrant_helpers` warmup in `apps.py` is for embeddings we don't have).
4. **Initial migrations.**
  - `manage.py makemigrations users workspaces chat`
  - `manage.py migrate`
  - Order matters because of the `AUTH_USER_MODEL` swap — must be set in settings before `makemigrations users`.
5. **Auth mechanism — pick one.**
  - **JWT** (the original docs assumed this) — needs `djangorestframework-simplejwt` or similar; gives stateless tokens that work cleanly for SPA clients and the SSE ticket exchange we'll need in Phase 2.
  - **Django session** — built-in; simpler for v1 if clients are first-party only; SSE ticket exchange still needed but the session itself rides cookies.
  - The decision drives `DEFAULT_AUTHENTICATION_CLASSES` and the `/auth/*` endpoint set.
6. **Middleware fixes.** The user-provided `WorkspaceMiddleware` has three real bugs and three hygiene issues:
  - **Bug:** Docstring says `X-Tenant-Id`; code reads `HTTP_X_WORKSPACE_ID`. Update docstring.
  - **Bug:** Fallback to "user's first membership" is documented but not implemented. Currently if the header is missing and the path isn't in `IGNORED_PATHS`, `request.workspace` is never set → downstream code (e.g., permission classes) `AttributeError`. Either implement the fallback or return 400 explicitly.
  - **Bug:** No membership verification — the middleware loads the workspace by ID without checking the caller is a member. 404 vs 200 leaks workspace existence. Either check membership here (single source of truth) or accept that viewset permissions handle it and tighten the 404-on-miss leak separately.
  - **Hygiene:** `IGNORED_PATHS` prefix match (`/api/v1/workspaces` matches both the collection and individual resources). PATCH/DELETE on a specific workspace fall through to requiring the header, which is redundant with the URL. Either anchor the prefix or expand `IGNORED_PATHS` to cover all methods on `/api/v1/workspaces`.
  - **Hygiene:** Malformed UUIDs raise `ValidationError`, not `DoesNotExist`, and aren't caught. Need a try/except on both.
  - **Hygiene:** `process_response` clears the thread-local tenant context but `process_exception` doesn't always (it only fires for raised exceptions, not for handled errors in views). Verify the contextvar doesn't leak between requests.

**Phase 0 deliverable:** `manage.py runserver`, hit `/admin/` and log in, hit `/api/v1/workspaces` with a token and create a workspace. Single full end-to-end of the slimmest possible slice.

---

## Phase 1 — Chat module CRUD (2–3 sessions)

**Goal:** rows 11–20 of the API surface (channels + channel members), no realtime, no agent.

- `chat/services.py` — `ChannelService`, `ChannelMembershipService` extending `BaseService`. Channel creation auto-seeds creator's channel ADMIN. DM creation via `get_or_create_dm(workspace, users)` under transaction. Visibility-flip warnings/confirmations.
- `chat/api/v1/serializers.py` — read/write split for both resources. Channel read includes `member_count`, `my_role`, `is_dm`.
- `chat/api/v1/views.py` — viewsets with the same permission patterns. `ChannelViewSet.get_queryset` filters visibility correctly (public OR private-with-membership). Lookup by `id`; channel members by `user_id`.
- `chat/urls.py` — flat for `/channels/`, nested `NestedSimpleRouter` for `/channels/{cid}/members/`.
- `chat/admin.py` — register Channel, ChannelMembership.
- Mount `donna.chat.urls` under `/api/v1/` in the project urls.
- Messages — `POST /channels/{id}/messages`, `GET .../messages` (paginated reverse-chrono), `PATCH/DELETE /messages/{id}` (own only). Polling-only for now; realtime is Phase 2.
- Documents — `GET/POST /channels/{id}/documents`, `GET/PATCH/DELETE /documents/{id}`. Last-write-wins semantics.

**Phase 1 deliverable:** Postman can drive every chat operation. No agent, no realtime.

---

## Phase 2 — Realtime (2 sessions)

**Goal:** Server-Sent Events stream for channel events.

- ASGI server (Daphne or Uvicorn) and a worker process for any out-of-request work.
- `POST /api/v1/sse/ticket` — client posts its JWT, gets a 30-second one-time ticket.
- `GET /api/v1/sse?ticket=…&channels=…` — opens the stream; multiplexes per-channel events (`message.created`, `message.updated`, `message.deleted`, `member.added`, `member.removed`).
- Connection lifecycle: keepalive comments every 15–20s, reconnect with `Last-Event-ID` for replay.
- Replay backend decision (Redis vs in-memory) — Redis if we already have it for anything else, in-memory if not (lose replay across restarts, accept for v1).

**Phase 2 deliverable:** a client connects once, gets new messages pushed in real time, can reconnect with replay.

---

## Phase 3 — Agent integration (3 sessions, the heavy one)

**Goal:** Donna actually responds in channels.

- **Build `core/llm/`** (referenced in `core/CLAUDE.md` but doesn't exist):
  - `LLMFactory`, `LLMProvider` abstraction.
  - Pick LiteLLM (multi-provider) or direct Anthropic SDK with prompt caching. Decision affects extensibility vs simplicity.
- **Build `core/memory/`**:
  - `MemoryStore` protocol.
  - `InMemoryStore` (JSONField backed by `AgentSession.memory`).
  - Optional `Mem0Store` adapter later.
- **Build `core/conversation/`**:
  - Turn loop: receive a user message → assemble context (channel history window + active workspace knowledge if landed) → call LLM → persist streaming tokens → emit SSE events.
  - StateGraph abstraction (or simpler) for multi-step flows.
- **AgentSession runtime in `chat/agents/`** (the directory already exists as an empty skeleton):
  - Triggered by message creation in a channel (signal or explicit dispatch from service).
  - Trigger semantics decision (Open): `@mention` to summon, always-listening per-channel toggle, or slash commands.
  - Writes responses as `Message` rows with `author_agent` set.
- **Tool layer** — identity-aware tools the agent can call. For multi-user channels, tools are scoped to the *channel's* access tier, not the triggering user. A private channel's agent can read its own contents but not other private channels.

**Phase 3 deliverable:** mention the agent in a channel, get a streamed response with channel-scoped context.

---

## Phase 4 — Collaborative documents (1–2 sessions)

**Goal:** real document editing flow, decide on collaborative model.

- CRUD is trivial (already modeled).
- Decision point: last-write-wins on full-body PATCH (1 session) vs real CRDT/OT (its own project).
- v1 should ship LWW; mark CRDT as a separate effort.

---

## Phase 5 — Integrations / ingestion (multiple sessions, parallelizable)

**Goal:** integration framework + Fathom (Tier 1, integration #1) + the path to Slack/Gmail/Linear/Drive.

**Design:** [05-integration-architecture.md](05-integration-architecture.md) (architecture, tiering, framework, models) and [06-deployment-and-self-hosting.md](06-deployment-and-self-hosting.md) (workers, storage, BYO OAuth, license, Helm chart).

### 5a. Framework — `donna/core/integrations/` + `donna/integrations/`

**Framework primitives in `donna/core/integrations/`** (cross-cutting, no app-model deps):

- `provider.py` — `IntegrationProvider` Protocol (identity + OAuth coupling + capabilities + four factory methods)
- `client.py` — `BaseHTTPClient` (auth header injection, retry on transient errors). No rate-limit primitive in v1 — add when first provider hits a real limit.
- `webhook.py` — `BaseWebhookHandler` (verify signature, parse payload, resolve workspace via `OAuthToken` lookup)
- `oauth.py` — `BaseOAuthHandler` (build_authorize_url, exchange_code, parse_token_response, refresh, revoke, handle_callback). Default impl covers most providers.
- `adapter.py` — `BaseAdapter` (raw dict → `to_text` / `to_markdown` / `to_json` / `metadata` / `external_id` / `title` / `occurred_at`)
- `registry.py` — `@register` decorator + lookup
- `exceptions.py`

**No `BronzeStorage` framework primitive in v1.** Provider tasks use Django's `default_storage` directly. The facade returns later if (a) multiple providers duplicate storage boilerplate or (b) bronze-specific features (presigned URLs, lifecycle, replay) earn it.

**App in `donna/integrations/`** (Django app concerns):

- `models.py` — `DeliveryPackage` only (one model, one migration). `WebhookDelivery` and `IngestionJob` deferred — see [02-data-model.md](02-data-model.md#open). Idempotency lives on `DeliveryPackage`'s `UniqueConstraint(workspace, provider, provider_item_id)`.
- `services.py` — `RegistryService` only (list, connect, disconnect, handle OAuth callback). **`IngestionService` deferred** — webhook view + Celery tasks call framework + DB directly. This is the **one documented exception** to the "every ViewSet sets `service_class`" convention; document in [03-conventions-and-api.md](03-conventions-and-api.md) and inline in `IntegrationViewSet`.
- `apps.py` — **recursive opt-out auto-discovery** of `providers/`. Walks the tree for `provider.py` files (skips underscore-prefixed paths), imports each. **Also imports `tasks.py` in the same folder if present** — that's how per-provider Celery tasks register at startup.
- `tasks.py` — thin pointer comment only (provider tasks live alongside providers; this file exists so Celery's `autodiscover_tasks(['donna.integrations'])` finds the conventional location and doesn't warn).
- `api/v1/views.py` — `IntegrationViewSet` (list, retrieve, connect, disconnect actions; uses `RegistryService`).
- `api/v1/webhooks.py` — `ProviderWebhookView` (public webhook dispatcher).
- `api/v1/oauth.py` — `ProviderOAuthCallbackView` (public OAuth callback dispatcher; renamed for consistency with `ProviderWebhookView`).
- `management/commands/integrations_bootstrap.py` — seeds `OAuthProvider` rows from provider class defaults. **Groups provider classes by `oauth_provider_slug` and unions scopes** so multi-product vendors (Google = Gmail + Drive) collapse to one `OAuthProvider("google")` row. **Reads optional Cloud env vars** (`DONNA_OAUTH_<SLUG>_{CLIENT_ID,CLIENT_SECRET,REDIRECT_URI}`) — when present, fills the row with `is_enabled=True`; when absent (on-prem path), leaves the row as `is_enabled=False` for the admin to configure. Idempotent — preserves existing admin-configured credentials.

### 5b. `authentication` app updates

- Extend `OAuthProvider` with the deployment-config fields (see [02-data-model.md#9-oauthprovider](02-data-model.md#9-oauthprovider)).
- `OAuthProviderAdmin` in Django admin — read-only slug/display_name, editable credentials, `is_enabled` toggle.
- OAuth start/callback views unchanged in shape; now read `client_id`/`client_secret` from the `OAuthProvider` row instead of settings.

### 5c. Storage backend configuration (pluggable, env-var-driven)

- `settings.py` configures `STORAGES["default"]` driven by `DONNA_STORAGE_BACKEND` env var. Supported backends: `s3` (covers AWS S3 + any S3-compatible service via `DONNA_S3_ENDPOINT_URL` — MinIO, SeaweedFS, Garage, Ceph, R2, Backblaze, Wasabi, Hetzner), `filesystem`, `gcs`, `azure`. Provider tasks use `django.core.files.storage.default_storage` (which resolves to `STORAGES["default"]`).
- `django-storages` dependency added to project requirements.
- `storage_test` management command verifies the configured backend works end-to-end.
- Per-provider setup docs (under 5e, 5f) include the storage env-var matrix.
- `WorkspaceStorageConfig` (per-workspace override) deferred to v2+ — tracked in open decisions; revived when an enterprise customer asks for data-residency / per-tenant bucket isolation.
- Open question to revisit when integration #2 arrives: introduce a dedicated `STORAGES["integrations"]` named backend so ingestion data doesn't share a bucket/path with Django uploads (avatars, etc.). For Fathom-only v1, sharing `STORAGES["default"]` is acceptable.
- Reference: full design in [06-deployment-and-self-hosting.md#storage-pluggable-env-var-driven-code-agnostic](06-deployment-and-self-hosting.md).

### 5d. Fathom (Tier 1, integration #1)

- `providers/fathom/{provider,client,adapter,tasks}.py` — **4 files**. Webhook + OAuth use framework defaults (no `webhook.py` / `oauth.py` overrides needed).
- `FathomMeetingAdapter(BaseAdapter)` implements `external_id`, `title`, `occurred_at`, `to_json`, `metadata` (and the other adapter methods even if unused by the v1 task, for future consumers).
- `providers/fathom/tasks.py::ingest_fathom_meeting(workspace_id, meeting_id)` — Celery task: load `OAuthToken`, fetch meeting + transcript, run adapter, write raw JSON to `default_storage` at `{workspace_id}/fathom/meetings/{meeting_id}.json`, upsert `DeliveryPackage`.
- No gold landing in v1 — `DeliveryPackage` is the queryable output; raw payload sits in `default_storage`. Document creation (Tier 1 landing) comes when chat integration lands.
- Webhook-only for v1 (no backfill endpoint — see deferred decisions below).
- `docs/self-hosting/integrations/fathom.md` — BYO OAuth setup guide (covers Cloud env-var matrix and on-prem admin UI flow).

### 5e. Distiller + leakage scanner

Carries over from `/docs/04-ingestion-pipeline.md` posture (defense-in-depth: prompt + scan). Apply at the adapter level before landing gold.

### 5f. Integrations #2-#5 (Slack, Linear, Google {Mail, Drive})

Layout per the flat-vs-nested rule from [05-integration-architecture.md](05-integration-architecture.md#adding-integration-2):

- `providers/slack/` — single-product vendor, flat. `OAuthProvider("slack")`. Setup doc: `docs/self-hosting/integrations/slack.md`. Likely adds `oauth.py` (bot+user tokens) and `webhook.py` (Events API).
- `providers/linear/` — single-product vendor, flat. `OAuthProvider("linear")`. Setup doc: `docs/self-hosting/integrations/linear.md`.
- `providers/google/{client.py, scopes.py, mail/, drive/}/` — multi-product vendor, nested. **One** `OAuthProvider("google")` shared between Gmail and Drive. **One** setup doc covering both: `docs/self-hosting/integrations/google.md`.
- Each product folder has `provider.py + client.py + adapter.py`. Gmail and Drive subclass `BaseGoogleClient` from `providers/google/client.py`.

Framework matures from real friction (Slack is GraphQL + Events API + webhook signing; Linear is GraphQL + per-workspace tokens; Google is OAuth-shared + multi-product). By #5, the abstraction should be stable enough that #6+ is mostly mechanical.

---

## Open architectural decisions (cross-phase)

These are deferred but not forgotten. Each blocks at least one phase:


| Decision                                      | Blocks     | Default if not made                                                                         |
| --------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------- |
| Auth mechanism (JWT vs session)               | Phase 0    | JWT (matches `/docs/` and the SSE ticket exchange pattern)                                  |
| LLM provider abstraction                      | Phase 3    | Anthropic SDK with prompt caching                                                           |
| Memory store backend                          | Phase 3    | `JSONField` on `AgentSession` for v1                                                        |
| Agent trigger semantics                       | Phase 3    | `@mention` only                                                                             |
| SSE replay backend                            | Phase 2    | In-memory (no cross-restart replay)                                                         |
| DM dedup mechanism                            | Phase 1    | Service-level `get_or_create_dm`                                                            |
| Document editing model (LWW vs CRDT)          | Phase 4    | LWW for v1                                                                                  |
| Workflow engine (Celery / Django-Q / Inngest) | Phase 5    | Celery + Redis — see [06-deployment-and-self-hosting.md](06-deployment-and-self-hosting.md) |
| OSS license (MIT / Elastic v2 / BSL)          | Pre-public | Elastic v2 — see [06-deployment-and-self-hosting.md](06-deployment-and-self-hosting.md)     |


**Resolved (moved out of this table):**

- ~~Ingested content landing~~ — `DeliveryPackage` in `integrations` app (one model, 6 fields + JSONField, idempotent UniqueConstraint). See [05-integration-architecture.md](05-integration-architecture.md).
- ~~Storage backend portability~~ — `STORAGES["default"]` named backend driven by `DONNA_STORAGE_BACKEND` env var; supports `s3` (any S3-compatible), `filesystem`, `gcs`, `azure`. Provider tasks call `default_storage` directly. See [06-deployment-and-self-hosting.md](06-deployment-and-self-hosting.md). Phase 5c.
- ~~Storage key convention~~ — `{workspace_id}/{provider}/{kind}/{provider_item_id}.json`, backend-agnostic. For Fathom: `{workspace_id}/fathom/meetings/{meeting_id}.json`.
- ~~OAuth callback URL placement~~ — under integrations namespace: `/api/v1/integrations/{slug}/oauth/callback`.
- ~~Webhook callback URL placement~~ — under integrations namespace: `/api/v1/integrations/{slug}/webhook/callback`.
- ~~Cloud OAuth credentials provisioning~~ — env-var bootstrap (`DONNA_OAUTH_<SLUG>_CLIENT_ID`, etc.) → seeds `OAuthProvider` rows on first boot. Same code path as on-prem; only the data source differs. See [06-deployment-and-self-hosting.md](06-deployment-and-self-hosting.md).
- ~~Webhook idempotency~~ — moved to `DeliveryPackage`'s `UniqueConstraint(workspace, provider, provider_item_id)`. No `WebhookDelivery` row in v1; duplicate webhooks safely upsert.
- ~~Per-provider task location~~ — each provider's Celery tasks live in `providers/<vendor>/<product>/tasks.py`, imported by `apps.py:ready()` alongside `provider.py`. App-level `tasks.py` is a thin pointer.

**New deferred items added to v2+ backlog (not blocking Phase 5):**

- `WorkspaceStorageConfig` per-workspace storage override (data-residency).
- `WebhookDelivery` model — return when we need a discrete audit trail of webhook receipts independent of the resulting `DeliveryPackage`.
- `IngestionJob` model + `POST /backfill` endpoint + `GET /jobs` endpoints — return together when backfill / scheduled ingestion lands. v1 covers webhook-driven ingestion only.
- `BronzeStorage` framework primitive — return when (a) multiple providers duplicate `default_storage.save(...)` boilerplate or (b) bronze-specific features (presigned URLs, lifecycle policies, replay) earn it.
- `TokenBucket` rate-limit primitive — return when first provider hits a real rate limit.
- `IngestionService` — return if integrations grow logic worth extracting from the view + Celery tasks (currently the view is ~4 lines of glue per action).
- Dedicated `STORAGES["integrations"]` named backend — consider at integration #2 (separate ingestion data from Django uploads).
- Gold landing (`Document` in a per-workspace "Fathom" channel) — comes with chat agent integration.

## When to revisit this plan

- End of every phase — mark done items, refine the next phase, lock at least one open decision.
- When something surprising lands (a real client requirement, a perf wall, a security concern).
- When the gap between this plan and the code grows enough that one of them is wrong.

