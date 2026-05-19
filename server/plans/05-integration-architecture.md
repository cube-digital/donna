# Integration architecture

The path from Fathom (integration #1) to 100+ third-party APIs (Linear, Slack, Asana, ClickUp, Telegram, Gmail, Drive, HubSpot, Discord, …). Integrations are core product for Donna — the agent's value depends on what it can read from and act in.

## Scope shift

The earlier plan (Phase 5 in [04-roadmap.md](04-roadmap.md)) treated ingestion as a single feature. It isn't. At the projected scale (~100 providers) the integration layer is **a sub-system, not a feature**, and decisions about its shape determine team velocity for years.

This document supersedes Phase 5 as written and replaces the open "ingested content landing model" question from [02-data-model.md](02-data-model.md) with a concrete model (`DeliveryPackage`).

## The thesis

> **Build deep for the providers users live in. Use AI-action platforms for the long tail. Stage the migration — don't pre-commit to platforms before feeling the pain they solve.**

Three tiers, picked by *what role the integration plays in the product*, not by source category.

| Tier | Role | Implementation | Count |
|---|---|---|---|
| **1. Deep custom** | Products users live in; deep semantic understanding required | Custom Python client + bespoke transform + Tier 1 landing (Document/Message/Memory) | 5–10 |
| **2. Agent action layer** | Tools the agent calls (post message, create issue, send email) | Composio or Arcade (MCP-native) — 500+ tools via one platform | ~100 |
| **3. Long-tail data sync** | Read-only data ingestion from tools the agent only acts in | Nango syncs (or skipped entirely if Tier 2 covers it) | optional |

The 90/10 split: ~10 providers carry 90% of the product value (deep custom). The remaining 90 are agent reach (Tier 2 platform).

## Why this — the evidence

The build-it-yourself-for-100 path is not what successful integration-heavy products actually do. The data is consistent across the 2026 landscape:

- **Maintenance dominates cost.** Initial development is 30–40% of TCO; 60–70% is recurring maintenance, schema drift, deprecations, retries. One multi-case study put dev at 21% of 5-year costs.
- **Per-script multiplication is brutal.** 30 integrations × 5 object types each = 150 distinct scripts to maintain. Providers deprecate endpoints, change pagination, alter rate limits — every change is a rewrite/test/deploy cycle, multiplied by 150.
- **Custom integrations cost $50k–$150k/year per integration** at maturity. DIY for 3 providers = $20k–$32k Year 1. Unified-API equivalent for the same = $1.6k–$5.6k Year 1. The gap widens with maintenance.
- **MCP is the emerging standard** for AI-agent tool calling. Industry framing: *"the REST API moment for AI-enabled SaaS."* Composio (500+ tools, 18k GitHub stars), Arcade (MCP runtime), Paragon ActionKit are converging on it.
- **What successful integration-heavy products do:** Notion, Linear, Zapier, Retool, Workato — none hand-build 100 connectors. They build 5–15 deep ones (their moat) and use platforms for the rest, or expose APIs and let an ecosystem fill the long tail.

## Why custom for *now*

Despite the evidence above, **the right v1 move is custom-build for Fathom and the next 4–5 providers**. The reasoning is staged, not contrarian:

1. **You're learning the shape of the abstraction.** A framework designed before you've built 3 integrations is a framework designed wrong. The `IntegrationProvider` protocol below has to *emerge from* the real friction of Fathom + Slack + Gmail before it's worth committing to.
2. **The Tier 1 transforms are your moat.** Fathom transcript → channel `Document`, Slack thread → agent memory, Linear issue → channel notification. These are bespoke and product-defining. No platform does them for you.
3. **Premature platform adoption is more expensive than premature build.** Switching from custom to Composio at integration #5 is cheap (you have a clean abstraction); switching from Composio to custom because the abstraction didn't fit is expensive.
4. **The framework is reusable.** Building Fathom inside the structure below means Slack/Gmail/Linear are ~2-day projects each, not ~2-week projects. The maintenance burden hits at integration #15, not #3.

The decision to introduce a platform (Composio for Tier 2 action; Nango for Tier 3 sync) is **deferred to after integration #5**, when the abstraction is mature and the friction is concrete.

---

## App structure

One Django app (`donna.integrations`); providers as plain Python modules inside `providers/`. OAuth lives in `donna.authentication` (unchanged from [02-data-model.md](02-data-model.md)).

```
donna/
├── authentication/                      # OAuth* models (unchanged)
│   ├── models.py                        # OAuthProvider, OAuthToken
│   ├── services.py                      # OAuth flow + token refresh
│   └── api/v1/views.py                  # /oauth/{provider}/{start,callback}
│
├── core/                                # cross-cutting framework primitives
│   ├── (existing: services.py, viewsets.py, db/, mixins.py, renderers.py, ...)
│   └── integrations/                    # integration framework — provider-agnostic
│       ├── __init__.py
│       ├── provider.py                  # IntegrationProvider Protocol
│       ├── client.py                    # BaseHTTPClient: auth, retry
│       ├── webhook.py                   # BaseWebhookHandler: verify, parse, resolve ws
│       ├── oauth.py                     # BaseOAuthHandler: authorize, exchange, refresh, revoke
│       ├── adapter.py                   # BaseAdapter: raw → to_text/to_markdown/to_json/metadata
│       ├── registry.py                  # @register decorator + lookup
│       └── exceptions.py
│                                        # NOTE: no BronzeStorage, no TokenBucket in v1
│                                        # (provider tasks use default_storage directly;
│                                        #  rate limiting added when first limit bites)
│
└── integrations/                        # the APP (models, providers, API, tasks)
    ├── apps.py                          # recursive discovery — imports provider.py AND tasks.py per provider
    ├── admin.py
    ├── models.py                        # DeliveryPackage only
    │                                    # (WebhookDelivery + IngestionJob deferred — see 02-data-model.md)
    ├── services.py                      # RegistryService only (IngestionService deferred —
    │                                    #   webhook view + Celery tasks call framework + DB directly)
    ├── urls.py
    ├── tasks.py                         # thin aggregator / pointer only; tasks live per-provider
    ├── migrations/                      # one migration for DeliveryPackage
    │
    ├── api/v1/
    │   ├── serializers.py
    │   ├── views.py                     # IntegrationViewSet (list/retrieve/connect/disconnect)
    │   ├── webhooks.py                  # ProviderWebhookView — one dispatcher for all providers
    │   └── oauth.py                     # ProviderOAuthCallbackView — one dispatcher for all providers
    │
    ├── providers/                       # plain Python — NOT Django apps
    │   │
    │   ├── fathom/                      # SINGLE-PRODUCT VENDOR → flat
    │   │   ├── provider.py              # FathomProvider — slug="fathom"
    │   │   ├── client.py                # FathomClient(BaseHTTPClient)
    │   │   ├── adapter.py               # FathomMeetingAdapter(BaseAdapter)
    │   │   └── tasks.py                 # @shared_task ingest_fathom_meeting(ws_id, meeting_id)
    │   │                                # (no webhook.py / oauth.py — Fathom uses framework defaults)
    │   │
    │   ├── slack/                       # single-product → flat
    │   │   ├── provider.py
    │   │   ├── client.py
    │   │   ├── adapter.py
    │   │   ├── tasks.py
    │   │   ├── webhook.py               # Slack Events API needs custom handler
    │   │   └── oauth.py                 # Slack bot+user tokens override
    │   │
    │   └── google/                      # MULTI-PRODUCT VENDOR → nested (future)
    │       ├── __init__.py
    │       ├── client.py                # BaseGoogleClient — shared at vendor level
    │       ├── scopes.py
    │       ├── oauth.py                 # shared OAuth quirks
    │       ├── mail/
    │       │   ├── provider.py          # GmailProvider — slug="gmail", oauth_provider_slug="google"
    │       │   ├── client.py            # GmailClient(BaseGoogleClient)
    │       │   ├── adapter.py
    │       │   └── tasks.py
    │       └── drive/
    │           ├── provider.py
    │           ├── client.py
    │           ├── adapter.py
    │           └── tasks.py
    │
    └── tests/
        ├── factories.py
        ├── test_models.py
        ├── test_services.py
        ├── test_registry.py
        └── providers/
            ├── fathom/{test_client,test_adapter,test_tasks}.py
            └── google/{mail,drive}/{test_client,test_adapter,test_tasks}.py
```

**Load-bearing decisions:**

- **Framework in `core/integrations/`, app in `integrations/`.** The framework is cross-cutting primitives — same kind of thing as `core/db/models.py` (`TimestampsMixin`) or `core/services.py` (`BaseService`). It lives in `core/` where Donna already keeps framework code. The `integrations/` app holds *Django app concerns* — models, migrations, services, admin, API, providers, tasks. Clean separation: framework knows nothing about app models; app uses framework primitives.
- **Framework code has no app-model dependencies.** `core/integrations/*` defines Protocols, base classes, and helpers. Concrete behavior (creating `DeliveryPackage` rows, dispatching to providers, writing to storage) lives in `integrations/services.py` and per-provider `tasks.py` files, which use the framework. This is the same separation `core/services.py:BaseService` has from concrete services in app `services.py` files.
- **One Django app, providers as modules (flat-or-nested per vendor).** Each new product is a folder under `integrations/providers/`, not a Django app. **Flat by default; nest under a vendor folder when the same upstream vendor ships 2+ products that share OAuth.** Examples: `providers/fathom/` (single product, flat); `providers/google/mail/` + `providers/google/drive/` (multi-product, nested under shared vendor); `providers/atlassian/jira/` + `providers/atlassian/confluence/` (future, same pattern). Vendor folders carry shared code at root (`client.py`, `scopes.py`) that products subclass/import.
- **Provider slugs are flat and short, independent of folder path.** `GmailProvider.slug = "gmail"`, not `"google.mail"`. The folder layout is for code organization; the slug is the system-wide identifier used in URLs, the disabled list, registry lookups. n8n does the same — folder is `Google/Gmail/`, node name is `Gmail`.
- **`OAuthProvider`/`OAuthToken` stays in `authentication/`.** Auth lifecycle (tokens, refresh, revocation) is distinct from "do something with the token." Clean separation. `OAuthProvider` also carries the deployment-config layer — see [Deployment model](#deployment-model) below.
- **Shared OAuth per vendor.** Multiple providers under the same vendor folder point at one `OAuthProvider` row via `oauth_provider_slug` (e.g., both `GmailProvider` and `GoogleDriveProvider` set `oauth_provider_slug = "google"`). One OAuth dance unlocks all products from that vendor. The data model already supports this — no schema changes needed.
- **Opt-out discovery (n8n model), recursive.** `integrations/apps.py:ready()` walks `integrations/providers/` recursively for `provider.py` files and imports each module. Underscore-prefixed paths are skipped. The `@register` decorator (from `core.integrations.registry`) checks `DONNA_DISABLED_INTEGRATIONS` against the class's `slug` and registers if allowed. No manual wiring per provider, no settings edit when adding one.

---

## Core models

### `DeliveryPackage` — the one v1 model

Single normalized row per ingested item. Populated by the provider's adapter (`adapter.title()`, `adapter.occurred_at()`, `adapter.metadata()`, …). The raw payload is written separately to `default_storage` and referenced via `storage_key`.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `workspace` | FK Workspace, CASCADE | Tenant scope |
| `provider` | CharField(64) | `"fathom"`, `"gmail"`, `"linear"` |
| `provider_item_id` | CharField(255) | Provider's stable ID (Fathom meeting ID, Gmail message ID, …) |
| `provider_item_type` | CharField(64) | `"meeting"`, `"email"`, `"issue"` |
| `title` | CharField(500) | From `adapter.title()` |
| `occurred_at` | DateTimeField | From `adapter.occurred_at()` |
| `storage_key` | CharField(500) | Key under `default_storage`, e.g. `{ws_id}/fathom/meetings/{id}.json` |
| `metadata` | JSONField, default=dict | From `adapter.metadata()` |
| | | TimestampsMixin |

**Constraints:**
- `UniqueConstraint("workspace", "provider", "provider_item_id")` — idempotency. Re-delivery upserts the row; the storage write is also idempotent because the key is keyed by `provider_item_id`. **No `WebhookDelivery` row needed** — duplicate webhooks safely overwrite the same key + upsert the same row.
- Index `("workspace", "provider", "occurred_at")` — provider-scoped time queries.
- Index `("workspace", "occurred_at")` — cross-provider time queries.

### Deferred to v2+

- `WebhookDelivery` — return when we need a discrete audit trail of webhook receipts independent of resulting packages.
- `IngestionJob` — return when backfill / scheduled ingestion lands (paired with `POST /backfill` + `GET /jobs` endpoints).
- `BronzeStorage` framework primitive — return when (a) multiple providers duplicate `default_storage.save(...)` boilerplate or (b) bronze-specific features (presigned URLs, lifecycle policies, replay across providers) earn their keep.
- `TokenBucket` — return when first rate limit bites in production.

---

## The `IntegrationProvider` protocol

In `donna/core/integrations/provider.py`:

```python
class IntegrationProvider(Protocol):
    # Identity
    slug: ClassVar[str]                              # "fathom"
    display_name: ClassVar[str]                      # "Fathom"
    category: ClassVar[str]                          # "meeting_transcripts"

    # OAuth coupling
    oauth_provider_slug: ClassVar[str]               # find OAuthProvider row
    token_scope: ClassVar[Literal["user", "workspace"]]

    # Static OAuth defaults (consumed by integrations_bootstrap to seed OAuthProvider)
    default_authorize_url: ClassVar[str]
    default_token_url: ClassVar[str]
    default_scopes: ClassVar[list[str]]

    # Capabilities
    supports_webhooks: ClassVar[bool]

    # Factory methods
    def client(self, token: OAuthToken) -> BaseHTTPClient: ...
    def webhook_handler(self) -> BaseWebhookHandler: ...
    def oauth_handler(self, oauth_provider: OAuthProvider) -> BaseOAuthHandler: ...
    def adapter_for(self, raw: dict) -> BaseAdapter: ...

    # Capabilities
    supports_webhooks: ClassVar[bool]
    supports_backfill: ClassVar[bool]

```

Every provider implements **four factory methods** (`client`, `webhook_handler`, `oauth_handler`, `adapter_for`) and declares **class-level static config** (slug, OAuth coupling, defaults, capabilities). For most providers, `webhook_handler` and `oauth_handler` return the framework defaults — only `client` and `adapter_for` need provider-specific implementations.

Fathom example: only Provider + Client + Adapter + Tasks files needed (4 files). Slack: those plus `webhook.py` (Events API quirks) and `oauth.py` (bot + user tokens).

---

## API surface

All `/api/v1/`. Header-tenanted except webhook + OAuth callback (added to `IGNORED_PATHS`).

| # | Method | Path | Purpose | Tenant via | Auth |
|---|---|---|---|---|---|
| 1 | `GET` | `/integrations` | List available providers + status | Header | User |
| 2 | `GET` | `/integrations/{slug}` | Detail: connected? scopes? | Header | User |
| 3 | `POST` | `/integrations/{slug}/connect` | Returns OAuth `{authorize_url}` | Header | User |
| 4 | `POST` | `/integrations/{slug}/disconnect` | Revoke + delete `OAuthToken` | Header | User |
| 5 | `POST` | `/integrations/{slug}/webhook/callback` | Provider webhook receiver | — | Signature |
| 6 | `GET` | `/integrations/{slug}/oauth/callback` | OAuth redirect target | — | State param |

Endpoints 5 + 6 are non-tenanted (provider doesn't send `X-Workspace-Id`; OAuth callback comes from browser redirect). Added to `WorkspaceMiddleware.IGNORED_PATHS` via URL-suffix matching.

**Deferred (will return when needed)**: `POST /backfill`, `GET /jobs`, `GET /jobs/{id}`. v1 covers webhook ingestion only.

Webhook receiver is one ViewSet that dispatches to `provider.webhook_handler()` — adding Gmail webhooks doesn't add a URL pattern. OAuth callback is one view that dispatches to `provider.oauth_handler()` — same pattern.

See [diagrams/fathom.md](diagrams/fathom.md) for the call-chain diagrams.

---

## Task pipeline

Two halves:
- **Receive** — synchronous code in `ProviderWebhookView`. Verifies, parses, dispatches a Celery task. Returns 200 fast.
- **Process** — Celery task colocated with the provider in `providers/<vendor>/<product>/tasks.py`. Fetches, adapts, persists.

### Receive (sync, in the view)

```
ProviderWebhookView.post(slug, request)                    [sync, returns 200 fast]
    ↓
    1. provider_cls = Registry.get(slug)
    2. provider = provider_cls()
    3. handler = provider.webhook_handler()
    4. handler.verify(request.body, request.headers[signature_header])     [401 if invalid]
    5. parsed = handler.parse(request.body)
    6. workspace = handler.resolve_workspace(parsed)
         (looks up OAuthToken by Fathom-side identifier in payload)
    7. dispatch the provider's Celery task with (workspace.id, item_id)
         e.g. ingest_fathom_meeting.delay(workspace.id, parsed["meeting_id"])
    → return 200 OK
```

### Process (Celery task, per-provider)

Each provider owns its task in `providers/<vendor>/<product>/tasks.py`. Fathom example:

```python
# providers/fathom/tasks.py
from celery import shared_task
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
import json

from donna.authentication.models import OAuthToken
from donna.core.integrations.registry import Registry
from donna.integrations.models import DeliveryPackage

@shared_task(name="integrations.fathom.ingest_meeting")
def ingest_fathom_meeting(workspace_id, meeting_id):
    provider = Registry.get("fathom")()
    token = OAuthToken.objects.get(provider__slug="fathom", workspace_id=workspace_id)
    client = provider.client(token)

    raw = {
        "meeting":    client.get_meeting(meeting_id),
        "transcript": client.get_transcript(meeting_id),
    }
    adapter = provider.adapter_for(raw)

    storage_key = f"{workspace_id}/fathom/meetings/{meeting_id}.json"
    default_storage.save(
        storage_key,
        ContentFile(json.dumps(adapter.to_json()).encode()),
    )

    DeliveryPackage.objects.update_or_create(
        workspace_id=workspace_id,
        provider="fathom",
        provider_item_id=meeting_id,
        defaults={
            "provider_item_type": "meeting",
            "title":              adapter.title(),
            "occurred_at":        adapter.occurred_at(),
            "storage_key":        storage_key,
            "metadata":           adapter.metadata(),
        },
    )
```

### Task registration

Tasks register with Celery the moment their module is imported (`@shared_task` is import-time). The integrations app's `apps.py:ready()` imports each provider's `provider.py` *and* its `tasks.py` (when present) — so adding a provider with a `tasks.py` requires zero wiring elsewhere.

```python
# donna/integrations/apps.py — ready()
for provider_py in providers_root.rglob("provider.py"):
    rel = provider_py.relative_to(providers_root)
    if any(part.startswith("_") for part in rel.parts):
        continue
    base = f"donna.integrations.providers.{str(rel.with_suffix('')).replace('/', '.')}"
    importlib.import_module(base)                                       # provider.py
    try:
        importlib.import_module(base.replace(".provider", ".tasks"))    # tasks.py (optional)
    except ImportError:
        pass    # provider has no Celery tasks (e.g., pure pull-mode integration)
```

The app-level `donna/integrations/tasks.py` stays as a one-line pointer: provider tasks live alongside their provider; this file exists so Celery's `autodiscover_tasks(['donna.integrations'])` finds *something* in the conventional location and doesn't warn.

**Comparison with other tools** (see [07-integration-platform-landscape.md](07-integration-platform-landscape.md)): the colocation pattern matches Trigger.dev (`@task` decorator on per-folder functions), Nango (sync per provider folder), Activepieces (triggers in piece package). Our specific wrinkle — recursive auto-import via `apps.py:ready()` — sits cleanly under Celery's import-time registration model.

---

## Deployment model

We adopt the **n8n model**: ship all providers as code in the Docker image, opt-out via env var, configure per-deployment via admin UI, BYO OAuth app for on-premise. Same image runs Donna Cloud and customer on-prem installs — only the `OAuthProvider` row data differs.

### Three-layer model

| Layer | Who decides | What it controls | When set |
|---|---|---|---|
| **1. Shipped** | Donna maintainers | Which providers' code is in the Docker image | At release |
| **2. Configured** | Sysadmin (Cloud team for Donna Cloud, customer for on-prem) | Which providers are available + OAuth app credentials | At deploy / via admin UI |
| **3. Connected** | Workspace admin or user | Which providers I have linked | At use |

A provider only appears to users when **all three layers say yes**: code loaded, `OAuthProvider.is_enabled=True` with valid credentials, and the caller has (or creates) an `OAuthToken`.

### Layer 1 — Shipped (code)

All providers under `providers/` are loaded by default. Sysadmin can disable specific ones:

```python
# donna/settings.py
DISABLED_INTEGRATIONS = env.list(
    "DONNA_DISABLED_INTEGRATIONS", default=[]
)
```

`apps.py:ready()` walks the providers tree recursively, finds every `provider.py`, and imports it. The `@register` decorator filters on `DISABLED_INTEGRATIONS`:

```python
# donna/integrations/apps.py
def ready(self):
    from pathlib import Path
    from . import providers
    import importlib

    providers_root = Path(providers.__file__).parent

    for provider_py in providers_root.rglob("provider.py"):
        rel = provider_py.relative_to(providers_root)
        # Skip underscore-prefixed paths (e.g., _shared/, _draft/) and __pycache__
        if any(part.startswith("_") for part in rel.parts):
            continue
        module_path = "donna.integrations.providers." + str(rel.with_suffix("")).replace("/", ".")
        importlib.import_module(module_path)


# donna/core/integrations/registry.py
def register(cls):
    from django.conf import settings
    if cls.slug in settings.DISABLED_INTEGRATIONS:
        return cls          # class still exists for tests, just not in the runtime registry
    _REGISTRY[cls.slug] = cls
    return cls
```

This handles both flat (`providers/fathom/provider.py` → slug `"fathom"`) and nested (`providers/google/mail/provider.py` → slug `"gmail"`) layouts. The slug is whatever the provider class declares — never derived from the path.

### Layer 2 — Configured (`OAuthProvider` row)

Per-deployment configuration lives in the `OAuthProvider` model — see [02-data-model.md#9-oauthprovider](02-data-model.md#9-oauthprovider) for the full schema. Key fields the deployer controls: `is_enabled`, `client_id`, `client_secret`, `redirect_uri`.

Each provider class declares safe defaults that the bootstrap command consumes:

```python
@register
class FathomProvider:
    slug = "fathom"
    display_name = "Fathom"
    category = "meeting_transcripts"

    # Static defaults — seeded into OAuthProvider on bootstrap
    default_authorize_url = "https://fathom.video/oauth/authorize"
    default_token_url = "https://fathom.video/oauth/token"
    default_scopes = ["transcripts:read"]

    supports_webhooks = True
    supports_backfill = True
    token_scope = "user"
```

A management command bootstraps `OAuthProvider` rows:

```bash
python manage.py integrations_bootstrap
```

The command **groups provider classes by `oauth_provider_slug`** and creates one `OAuthProvider` row per group, unioning scopes. This is how shared-OAuth vendors (Google = Gmail + Drive + Calendar) collapse to a single `OAuthProvider("google")` row with combined scopes:

```python
class Command(BaseCommand):
    def handle(self, *args, **opts):
        from donna.core.integrations.registry import all_loaded
        from donna.authentication.models import OAuthProvider

        by_oauth = {}
        for cls in all_loaded():
            by_oauth.setdefault(cls.oauth_provider_slug, []).append(cls)

        for oauth_slug, classes in by_oauth.items():
            scopes = sorted({s for c in classes for s in c.default_scopes})
            vendor_name = _common_prefix([c.display_name for c in classes]) \
                          or oauth_slug.title()

            OAuthProvider.objects.update_or_create(
                slug=oauth_slug,
                defaults={
                    "display_name": vendor_name,
                    "authorize_url": classes[0].default_authorize_url,
                    "token_url": classes[0].default_token_url,
                    "default_scopes": scopes,
                    # is_enabled, client_id, client_secret left untouched if row exists
                },
            )
```

Idempotent — safe to run on every deploy. If the admin has already configured credentials on an existing row, bootstrap preserves them.

**Cloud env-var bootstrap.** For Donna Cloud, credentials live in the secrets manager (AWS Secrets Manager / Vault) and are injected as env vars at container start. Bootstrap reads them through and fills the `OAuthProvider` row automatically — so Cloud customers see "Connect" buttons immediately, with no admin step. On-prem customers don't set these env vars; bootstrap creates the row with `is_enabled=False` and the customer fills it via Django admin. **Same code path either way.**

```python
# Per-provider, bootstrap probes for env vars and applies them if present:
client_id     = env(f"DONNA_OAUTH_{oauth_slug.upper()}_CLIENT_ID",     default=None)
client_secret = env(f"DONNA_OAUTH_{oauth_slug.upper()}_CLIENT_SECRET", default=None)
redirect_uri  = env(f"DONNA_OAUTH_{oauth_slug.upper()}_REDIRECT_URI",  default=None)

extra = {}
if client_id and client_secret and redirect_uri:
    extra = {
        "client_id":     client_id,
        "client_secret": client_secret,
        "redirect_uri":  redirect_uri,
        "is_enabled":    True,
    }

OAuthProvider.objects.update_or_create(
    slug=oauth_slug,
    defaults={
        "display_name":   vendor_name,
        "authorize_url":  classes[0].default_authorize_url,
        "token_url":      classes[0].default_token_url,
        "default_scopes": scopes,
        **extra,
    },
)
```

Cloud: bootstrap sets `is_enabled=True` automatically. On-prem: row stays `is_enabled=False` until admin enters credentials. The DB is always the source of truth at request time — the runtime code never reads OAuth secrets from env vars.

**Result for the Google vendor**:
- Two provider classes: `GmailProvider`, `GoogleDriveProvider`, both with `oauth_provider_slug="google"`
- One `OAuthProvider(slug="google", display_name="Google", default_scopes=["drive.file", "drive.readonly", "gmail.readonly", "gmail.send"])` row
- Sysadmin configures one OAuth app in Google Console with both Gmail + Drive scopes
- User connects "Gmail" OR "Drive" → OAuth dance asks for all Google scopes; the resulting `OAuthToken` powers both integrations

**UX implication**: per-service "Connect" buttons remain (Gmail and Drive are independent products in the UI), but clicking either triggers the same Google OAuth flow. If a Google token already exists for the user, the second "Connect" succeeds immediately without re-auth.

### Layer 3 — Connected (`OAuthToken`)

Unchanged from [02-data-model.md#10-oauthtoken](02-data-model.md#10-oauthtoken). Users/workspaces grant access; tokens stored encrypted.

### Registry filtering

```python
# donna/core/integrations/registry.py

def all_loaded() -> list[IntegrationProvider]:
    """Code-loaded providers (modulo DISABLED_INTEGRATIONS)."""
    return list(_REGISTRY.values())

def configured_for_workspace(workspace) -> list[IntegrationProvider]:
    """Loaded AND has OAuthProvider row with is_enabled=True."""
    enabled_slugs = OAuthProvider.objects.filter(
        is_enabled=True
    ).values_list("slug", flat=True)
    return [p for p in _REGISTRY.values() if p.slug in enabled_slugs]
```

API endpoints filter by `configured_for_workspace()`; webhook + connect endpoints refuse with 503 if the provider isn't configured.

### Donna Cloud vs On-Premise

| | Donna Cloud | On-Premise |
|---|---|---|
| Docker image | Same | Same |
| Discovery | All providers loaded | All loaded (sysadmin may disable some) |
| `OAuthProvider` rows | Managed by Donna team (hidden from customers) | Managed by customer sysadmin via admin UI |
| OAuth apps | Donna-owned, redirect = `donna.cloud/...` | Customer-owned, redirect = `donna.acme.internal/...` |
| `OAuthToken` rows | Per workspace × user, same | Same |
| Sysadmin onboarding | None | "Set up your OAuth apps with each provider" guide per provider |

**No code branches on deployment mode.** The full self-hosting story (workers, storage, license, Helm chart, BYO OAuth setup flow) lives in [06-deployment-and-self-hosting.md](06-deployment-and-self-hosting.md).

---

## Adding integration #2

**Flat-or-nested decision first.** Pick the layout based on the vendor:

| Vendor ships... | Layout | Example |
|---|---|---|
| One product | Flat | `providers/slack/`, `providers/notion/`, `providers/linear/` |
| Multiple products sharing OAuth | Nested under vendor folder | `providers/google/{mail,drive,calendar}/`, `providers/microsoft/{outlook,teams,onedrive}/`, `providers/atlassian/{jira,confluence}/` |

Promote a flat provider to nested when the *second* product from the same vendor lands. Don't pre-nest "in case." Refactoring flat → nested is a folder rename + import update; not painful.

### For a single-product vendor (e.g., Linear)

1. Create `providers/linear/` with `provider.py`, `client.py`, `webhook.py`, `transform.py`, `schemas.py`.
2. Write a setup guide: `docs/self-hosting/integrations/linear.md` for the on-prem BYO OAuth flow.
3. Deploy; bootstrap auto-creates the `OAuthProvider("linear")` row with `is_enabled=False`. Admin configures it.

### For a multi-product vendor (e.g., adding Gmail when no Google integrations exist yet)

1. Create `providers/google/` with shared code: `client.py` (`BaseGoogleClient`), `scopes.py`, `oauth.py`.
2. Create `providers/google/mail/` with `provider.py`, `client.py` (`GmailClient(BaseGoogleClient)`), `webhook.py`, `transform.py`, `schemas.py`.
3. `GmailProvider.oauth_provider_slug = "google"`.
4. Write **vendor-level** setup guide: `docs/self-hosting/integrations/google.md` (one doc covers Gmail + future Drive + Calendar; sysadmin sets up one OAuth app in Google Console).
5. Deploy; bootstrap auto-creates the `OAuthProvider("google")` row with `is_enabled=False`.

### Adding Drive after Gmail already exists

1. Create `providers/google/drive/` with the five files.
2. `GoogleDriveProvider.oauth_provider_slug = "google"` — points at the same row.
3. Re-run `integrations_bootstrap`. It unions Drive's scopes into the existing `OAuthProvider("google")` row's `default_scopes`.
4. Sysadmin re-runs OAuth app setup in Google Console to add the new scopes; updates `OAuthProvider("google")` if scope list changed.
5. Existing user tokens may need re-auth to pick up new scopes (handled by the framework's incremental-scope check on next connect).

**New URL? No. New model? No. New task? No. No settings edit needed.** The framework, the silver table, the API, the admin, the audit, the rate limit, the OAuth lifecycle — all already there.

---

## Staged migration

| Phase | Trigger | Action |
|---|---|---|
| **Now (Fathom)** | Build #1 | Custom Python. No platform. Learn the shape. |
| **#2 — Slack** | Build #2 | Custom. Slack is Tier 1 — users live in it; agent needs deep semantic understanding. |
| **#3-5 — Gmail / Linear / Drive** | Build #3-5 | Custom. The `IntegrationProvider` abstraction matures from real experience. Refactor as needed. |
| **#5-7 inflection** | Agent needs to *act* in 500+ tools | Introduce **Composio or Arcade** as the Tier 2 action layer. Agent gets MCP-native tool calling without 500 custom clients. |
| **~#10** | Celery starts cracking | Migrate workflow engine to **Inngest** (managed, observability, retries). Or **Temporal** if a platform team exists. |
| **~#15** | Read-only long-tail demand | Introduce **Nango** for Tier 3 data sync. Optional — Tier 2 platforms may cover this. |
| **~#30** | Cross-provider product features | Silver layer becomes critical infrastructure. Invest in normalized entities, search indices. |

The path is *staged*, not *all-at-once*. Each platform adoption is triggered by concrete pain, not a roadmap entry.

---

## Rejected alternatives

- **Hand-build all 100+ integrations.** Romantic engineering. 60-70% of cost is maintenance; 100 providers means 100 × maintenance burden. Not done by Notion, Linear, Zapier, or any other integration-heavy product. Becomes a 5-person team doing nothing but connector upkeep.
- **Adopt Composio / Nango from day one.** Frameworks designed before friction is concrete are frameworks designed wrong. You also don't get to learn what the deep Tier 1 transforms need before locking in a platform's abstractions.
- **One Django app per provider.** Each provider would have its own `models.py`, `migrations/`, `apps.py`, URL namespace — none of which it needs. The "100 apps" overhead is real (settings bloat, migration sequencing, test discovery). One app with provider modules is cleaner.
- **Runtime plugin loading (Airbyte's per-connector Docker image model).** Tempting because customers could install custom connectors without forking. Rejected for v1: sandbox security, dependency hell, signed-package distribution, version compatibility, plugin discovery — all gigantic problems that pay off at hundreds of customer-supplied connectors. Ship-all-as-code now; revisit if real customer demand arrives.
- **Opt-in via `INSTALLED_INTEGRATIONS` settings list.** Considered briefly. Rejected in favor of n8n's opt-out model: less per-provider config, easier for customers, matches the industry norm.
- **Customer-written Python plugins on the server.** Massive arbitrary-code-execution risk. If a customer needs a custom connector, they fork Donna or open a PR.
- **Provider-owned models for ingested content.** Considered `FathomTranscript`, `GmailEmail`, etc. as separate tables. Rejected: cross-provider features (search, agent context, timelines) need a normalized table. `DeliveryPackage` with `metadata` JSONField gives provider-specific data + cross-provider queries.
- **Land everything as `Document` in a channel (skip silver).** Considered making the gold layer the only layer. Rejected: agent context assembly, cross-provider search, and re-processing all need a structured silver layer. Bronze→silver→gold is the right shape, even if gold is just a `Document` for v1.
- **Self-host Airbyte for the data pull.** Heavy for one source; the Fathom connector isn't pre-built, so we'd write it in their CDK anyway. Pays off at 5+ data sources, not 1.
- **Synchronous webhook processing.** Webhook handler returns 200 *fast*. Fathom (and most providers) retry on timeout. All real work is on the queue.

---

## Open questions

- **Workflow engine for v1 — Celery or Django-Q?** Both fit. Celery is the historical default; Django-Q is simpler operationally (Postgres-backed, no Redis). Inngest comes when ops becomes the bottleneck (~integration #10). Decision deferred to [06-deployment-and-self-hosting.md](06-deployment-and-self-hosting.md).
- **Bronze key/path convention** — *resolved*: `{workspace_id}/{provider}/{yyyy}/{mm}/{dd}/{provider_item_id}.json`. Workspace-prefixed for compliance + lifecycle policies. Backend-agnostic — see [06-deployment-and-self-hosting.md#storage-pluggable-env-var-driven-code-agnostic](06-deployment-and-self-hosting.md#storage-pluggable-env-var-driven-code-agnostic).
- **Gold landing strategy for transcripts.** Provisional: `Document` in a per-workspace "Fathom" channel. Obsidian-via-git was considered (revives the dropped two-vault model); deferred until a customer requests it. Document the override hook in `BaseTransform.to_gold()` so it's a swap, not a rewrite.
- **Rate limit budget storage.** Token buckets per provider × per workspace. Probably Redis-backed; Postgres for v1 is fine but contention may bite at scale.
- **Schema validation.** Pydantic per provider in `schemas.py` — runtime check that the API hasn't changed shape under us. Catches schema drift before it lands as garbage in bronze.
- **Backfill UX.** Deferred from v1 — see [04-roadmap.md](04-roadmap.md). When it returns, lean async: return `IngestionJob` ID, client polls `/jobs/{id}`.
- **Connection scope override per provider.** Some providers are naturally user-scoped (Gmail), some workspace-scoped (Slack workspace token), some both. `IntegrationProvider.token_scope` is `"user" | "workspace"` — multi-mode providers may need `"user_or_workspace"`.
- **Admin UI for `OAuthProvider`.** Django admin is enough for v1. A dedicated `/admin/integrations` SPA is post-v1 polish — triggered when >5 Tier 1 providers exist and the admin surface starts feeling cramped.
