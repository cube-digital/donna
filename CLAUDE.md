# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

This is a monorepo with three top-level projects:

| Path | What it is | Stack |
|---|---|---|
| `server/` | The Donna backend — multi-tenant chat app with embedded AI agent + connector framework. **This is where most work happens.** | Django 5.2+, DRF, Celery, Postgres, Redis, uv-managed Python 3.13+ |
| `desktop/` | Donna desktop chat client | Electron + TypeScript |
| `docs/` | Original Cube-Context product vision (pre-pivot). **Superseded by `server/plans/` for implementation decisions** — see `server/plans/README.md` |

## Authoritative planning docs (read these first)

`server/plans/` is the source of truth for architectural decisions and the current build plan. Read in this order before making non-trivial changes:

1. `01-architecture.md` — multi-tenancy (header-based via `X-Workspace-Id`), channel/agent model, OAuth
2. `02-data-model.md` — every model with rejected alternatives + open questions
3. `03-conventions-and-api.md` — **mandatory app layout**, service/view/serializer patterns, API conventions
4. `04-roadmap.md` — phase-by-phase build sequence with status
5. `05-integration-architecture.md` — connector framework (Tier 1 deep custom / Tier 2 agent-action / Tier 3 sync), n8n deployment model
6. `06-deployment-and-self-hosting.md` — Cloud vs on-premise, storage backends, BYO OAuth, license
7. `07-integration-platform-landscape.md` — reference / learning material (n8n, Airbyte, Nango, Composio comparisons)
8. `08-connection-pattern.md` + `08a/08b` — per-tenant integration config (`Connection` model, JSON config + state, JSON Schema validation) with Gmail + Drive specifics
9. `09-auth-and-notifications.md` — login (email/password + Google), password reset, email verification; in-app notifications (DB + SSE)
10. `10-realtime-layer.md` — SSE per-(user, workspace) for notifications + Django Channels WebSockets for chat / DM / presence / agent token streaming

`server/plans/diagrams/fathom.md` has Mermaid class + sequence diagrams of the reference connector.

## Common commands (run from `server/`)

```bash
# Install / sync deps (uv-managed)
uv sync

# Migrations
DJANGO_SETTINGS_MODULE=donna.settings .venv/bin/python -m django makemigrations
DJANGO_SETTINGS_MODULE=donna.settings .venv/bin/python -m django migrate

# Dev server (SQLite by default; override with DATABASE_URL)
DJANGO_SETTINGS_MODULE=donna.settings .venv/bin/python -m django runserver

# Django check / shell
DJANGO_SETTINGS_MODULE=donna.settings .venv/bin/python -m django check
DJANGO_SETTINGS_MODULE=donna.settings .venv/bin/python -m django shell

# Seed OAuthProvider rows from connector class defaults
DJANGO_SETTINGS_MODULE=donna.settings .venv/bin/python -m django integrations_bootstrap

# Celery worker (needs Redis at CELERY_BROKER_URL)
celery -A donna worker --loglevel=info
```

### Full local stack (Postgres + Redis + web + worker + beat)

```bash
cd server
docker compose up --build
docker compose run --rm web bootstrap          # seed OAuthProvider rows
docker compose run --rm web shell              # Django shell
docker compose logs -f worker                  # tail worker
```

`docker-compose.yml` wires Postgres 16, Redis 7, the web container (gunicorn), the Celery worker, and Celery beat. Entrypoint dispatches by role (`web | worker | beat | migrate | bootstrap | shell`).

### Desktop (Electron)

```bash
cd desktop && npm run start                    # build TS + launch Electron
```

## High-level architecture

### Multi-tenancy is header-based, not URL-nested

Active workspace is communicated via `X-Workspace-Id` header. `donna.workspaces.middlewares.WorkspaceMiddleware` resolves it, sets `request.workspace` (+ `request.company` alias for `BaseService`). URLs do **not** prefix workspace IDs.

Public endpoints (webhook + OAuth callback) bypass the header via `IGNORED_PATHS` (prefix) and `IGNORED_SUFFIXES` (suffix: `/webhook/callback`, `/oauth/callback`).

### Standard app layout (mandatory)

Every Django app follows the structure documented in `server/plans/03-conventions-and-api.md`:

```
<app>/
├── models.py
├── services.py            # extends donna.core.services.BaseService
├── api/v1/{views,serializers,filters}.py
├── urls.py
└── tests/
```

- **Services own state mutations.** Views shape requests/responses; services own transactions, side effects, multi-step orchestration.
- **ViewSets set `service_class`.** The `ServiceMethodMixin` in `donna/core/mixins.py` auto-discovers `create_<model>` / `update_<model>` / `delete_<model>` methods.
- **PATCH only, no PUT.** `UpdateModelMixin` exposes `partial_update` only.
- **DRF responses are wrapped** by `donna.core.renderers.StandardJSONRenderer` as `{data, meta, message, code}`.

**Documented exception:** the `integrations` app uses `RegistryService` for the OAuth lifecycle only — webhook view + Celery tasks call framework + DB directly without a service. See `server/plans/03-conventions-and-api.md` "Documented exception".

### `donna/core/` is shared infrastructure

`donna.core.*` holds framework code used by every app: `BaseService`, `ModelViewSet`, `TimestampsMixin`/`UserAuditMixin`, `EncryptedTextField`, `StandardJSONRenderer`, `LoggingMiddleware`, structlog wiring. **Do not import from apps into core.** See `server/donna/core/CLAUDE.md` for the inventory and rules.

### Integration framework — two layers, no app-model deps in framework

```
donna/core/integrations/                # framework primitives, NO app-model deps
├── provider.py        # IntegrationProvider Protocol
├── client.py          # BaseHTTPClient (httpx, auth header, retry, pagination)
├── webhook.py         # BaseWebhookHandler (HMAC-SHA256 default)
├── oauth.py           # BaseOAuthHandler (OAuth 2.0 authorization-code flow)
├── adapter.py         # BaseAdapter (raw → to_text/to_markdown/to_json/metadata)
├── registry.py        # @register decorator + lookup
└── exceptions.py

donna/integrations/                     # Django app — models, services, views, connectors
├── models.py          # DeliveryPackage (single normalized row per ingested item)
├── services.py        # RegistryService (OAuth lifecycle for views)
├── api/v1/{views,webhooks,oauth}.py    # IntegrationViewSet + Provider*View
├── apps.py            # ready() recursively imports connectors/*/provider.py + tasks.py
└── connectors/        # plain-Python connector modules — NOT Django apps
    ├── fathom/        # single-product vendor → FLAT (provider, client, adapter, tasks)
    ├── google/        # multi-product vendor → NESTED
    │   ├── mail/      #   shares OAuthProvider("google")
    │   └── drive/
    └── ...
```

**Connector folder rule:** flat by default; nest under a vendor folder only when a second product from the same vendor lands (shared OAuth). Promotion from flat → nested is a folder rename + import update. Underscore-prefixed paths (`_shared/`) skipped by discovery.

**`OAuthProvider` is per-vendor, not per-connector.** Multiple connectors set `oauth_provider_slug` to the same vendor slug (e.g., Gmail + Drive → `"google"`); `integrations_bootstrap` unions their scopes onto one row.

**Cloud vs on-prem use the same code:** `OAuthProvider` row is filled either by `DONNA_OAUTH_<SLUG>_{CLIENT_ID,CLIENT_SECRET,REDIRECT_URI}` env vars (Cloud) or via Django admin (on-prem). Runtime always reads from the DB.

### Storage is env-var-driven

`STORAGES["default"]` is configured from `DONNA_STORAGE_BACKEND` (`filesystem | s3 | gcs | azure`). For `s3`, set `DONNA_S3_ENDPOINT_URL` to point at any S3-compatible service (AWS S3 / MinIO / SeaweedFS / R2 / Backblaze / etc.). Provider Celery tasks call `default_storage` directly — no `BronzeStorage` facade in v1.

### Logging

`donna.core.logging.configure_logging()` is called at the bottom of `settings.py`. Use `get_logger(__name__)`; request_id is attached by `LoggingMiddleware` and propagates via contextvars. Set `LOG_FORMAT=console` for dev, `json` for prod.

## Working in plans

When you change architectural shape (new model, new endpoint, new convention), update the relevant `server/plans/*.md` file in the same commit. The plans are not historical artifacts — they're the live design contract. The "Open" section at the bottom of most plan docs lists deferred decisions; resolved ones move into the body.
