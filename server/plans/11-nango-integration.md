# Plan — Nango Integration (long-tail fleet)

> Source of architecture decisions: 2026-06-24 chat with Rares.
> Source of current Donna shape: `server/donna/core/integrations/`,
> `server/donna/integrations/` (verified 2026-06-24).
> Companion docs: [`05-integration-architecture.md`](05-integration-architecture.md),
> [`07-integration-platform-landscape.md`](07-integration-platform-landscape.md),
> [`08-connection-pattern.md`](08-connection-pattern.md).

---

## Context

### Why this work

Donna ships three hand-rolled connectors (Fathom, Gmail, Drive). Each is
~500 LOC of provider + client + adapter + tasks plus its own OAuth-app
setup. Adding the next 20 (Notion, Linear, Slack, HubSpot, Salesforce,
Jira, Asana, Calendar, Outlook, Confluence, ...) is multi-month work even
with the framework primitives already factored.

[Nango](https://nango.dev) ships 400+ pre-built integrations with managed
OAuth + sync engine + unified webhook proxy. Bolting it onto Donna covers
the long tail for ~0 marginal connector code while keeping the existing
deep-custom Tier 1 connectors untouched.

### Goal

Two coexisting backends behind one contract:

- **Donna backend** (current): provider class implements full OAuth +
  webhook + client + adapter; tokens stored on Donna side; webhooks
  signed by vendor; Celery owns ingestion.
- **Nango backend** (new): Nango owns OAuth + sync; Donna owns adapter
  + bronze + cortex hop. Nango fires sync webhook into Donna; Donna
  canonicalizes records and walks the existing pipeline.

The seam runs between *transport* (Nango) and *processing* (Donna).
`BaseAdapter` + `DeliveryPackage` + bronze writer + cortex hop never
change. Cortex never knows Nango exists.

### Non-goals

- **Do NOT migrate Fathom/Gmail/Drive to Nango.** They're shipped, working,
  and use binary-attachment walking + OCR sidecar patterns that don't fit
  Nango's record-oriented sync model. Cost > benefit.
- **Do NOT replace OAuthToken storage for Donna-backend connectors.**
  Existing rows + encryption + refresh logic stay as-is.
- **Do NOT add a NangoConnectorBase class with vendor-specific subclasses.**
  Each Nango connector is just a `provider.py` declaring `oauth_backend="nango"`
  + an `adapter.py`. No client.py, no tasks.py.

### Plan shape

Seven phases. Phase 0 is refactor-only (no Nango code lands). Phase 1
bolts Nango on as one of two backends. Phase 1.5 makes the Donna admin the
sole UX for OAuth-app config (admin form → signal → push to platform).
Phase 2 handles self-host stack. Phase 3 ships the first real Nango
connector. Phase 4 documents the Tier 1 decision. Phase 5 expands the
fleet. Phase 6 documents the swap-out path so any platform can replace
Nango without touching connectors.

| Phase | Scope | Effort |
|---|---|---|
| 0 | Backend abstraction refactor — extract `OAuthBackend` Protocol, wrap current as `DonnaOAuthBackend`; same for webhooks. No Nango. | ~2d |
| 1 | Nango wiring — `NangoOAuthBackend`, `NangoWebhookBackend`, `NangoFetchBackend`, Nango SDK wrapper, sync-webhook → bronze → DP → cortex. | ~3d |
| 1.5 | Admin sync — `ClientCredentials.backend` field + post_save signal pushes OAuth-app creds to platform. Donna admin becomes the only UI users see. | ~0.5d |
| 2 | Self-host stack — Nango as compose service; shared Postgres logical DB; env vars; doctor command. | ~1d |
| 3 | First Nango connector (Notion or Linear) end-to-end — provider + adapter + tests. | ~1.5d |
| 4 | Document Tier 1 non-migration decision in [`05-integration-architecture.md`](05-integration-architecture.md). | ~0.5d |
| 5 | Fleet expansion — 5-10 long-tail connectors via Nango. | ~3-5d |
| 6 | Swap-out path doc — checklist + reference for replacing Nango with another platform (Composio / Paragon / Merge / homegrown). | ~0.5d |

Total ≈ 12-15d.

---

## Architecture

### Backend split

```
┌────────────────────────────────────────────────────────────────┐
│                       IntegrationProvider                       │
│   slug, display_name, category, canonical_types,                │
│   oauth_backend, fetch_backend, adapter_for(raw)                │
└─────────────────────┬───────────────────────────────────────────┘
                      │
       ┌──────────────┴──────────────┐
       │                              │
┌──────▼──────┐               ┌──────▼──────┐
│ Donna BE    │               │ Nango BE    │
│             │               │             │
│ OAuth ──────│ vendor token  │ OAuth ──────│ Nango Connect UI
│   stored on │   endpoint    │   delegated │   → Nango holds
│   Donna     │               │             │   tokens
│             │               │             │
│ Webhook ────│ vendor signs  │ Webhook ────│ Nango signs
│   HMAC by   │   per-vendor  │   HMAC by   │   sync notification
│   vendor    │   secret      │   Nango     │   payload
│             │               │             │
│ Fetch ──────│ Celery task   │ Fetch ──────│ Nango sync engine
│   pulls via │   via         │   runs;     │   pushes records
│   BaseHTTPC │   client.py   │   Donna     │   inline in
│             │               │   receives  │   webhook
└──────┬──────┘               └──────┬──────┘
       │                              │
       └──────────────┬──────────────┘
                      ▼
        ┌─────────────────────────────┐
        │  Shared processing pipeline │   ← unchanged
        │                              │
        │  adapter.canonicalize(raw)   │
        │       ↓                       │
        │  bronze.write(payload)       │
        │       ↓                       │
        │  DeliveryPackage.create(...) │
        │       ↓                       │
        │  cortex_hop.delay(dp.id)     │
        └─────────────────────────────┘
```

### Three Protocols (Phase 0 extracts these)

```python
# core/integrations/backends/oauth_backend.py
class OAuthBackend(Protocol):
    """Owns the OAuth dance + token lifecycle."""
    def build_authorize_url(self, *, state_payload, redirect_uri=None) -> str: ...
    def handle_callback(self, *, code, state, request) -> Connection: ...
    def revoke(self, connection) -> None: ...
    def get_access_token(self, connection) -> str: ...
    def refresh(self, connection) -> None: ...

# core/integrations/backends/fetch_backend.py
class FetchBackend(Protocol):
    """Owns the data-pull mechanism (Celery task vs Nango sync)."""
    def kickoff_initial_sync(self, connection) -> None: ...
    def trigger_sync(self, connection, *, full=False) -> None: ...
    def handle_sync_webhook(self, payload) -> int: ...  # returns count processed

# core/integrations/backends/webhook_backend.py
class WebhookBackend(Protocol):
    """Verifies + parses incoming HTTP webhook payloads."""
    signature_header: str
    def verify(self, payload, signature, *, connection=None) -> bool: ...
    def parse(self, payload) -> dict: ...
```

### Connector authoring shape after Phase 0

**Design rule:** connector class ClassVars carry NO platform-specific field
names (no `nango_*`, no `composio_*`). Backend selection is by string name;
per-backend opaque config lives in `backend_config: dict[str, Any]`. The
active backend reads its own keys; framework code never inspects the dict.
Swap platform = change backend class + change dict keys; connector contract
stays stable.

Donna-native (Fathom — unchanged behaviour):
```python
@register
class FathomProvider:
    slug = "fathom"
    oauth_backend_name = "donna"
    fetch_backend_name = "donna_celery"
    webhook_backend_name = "donna_hmac"
    backend_config = {}              # not used; Donna reads ClientCredentials
    # ... rest unchanged
```

Platform-backed via Nango (Notion — new):
```python
@register
class NotionProvider:
    slug = "notion"
    oauth_backend_name = "nango"
    fetch_backend_name = "nango_sync"
    webhook_backend_name = "nango_proxy"
    backend_config = {
        # Nango reads these keys; other backends ignore them.
        "provider_config_key": "notion",
        "catalog_key":         "notion",
        "sync_models":         ("Page", "Database"),
        "sync_frequency":      "every 1 hour",
        "oauth_scopes":        [],
    }
    # NO client.py, NO tasks.py
    def adapter_for(self, raw) -> BaseAdapter: return NotionAdapter()
    def resolve_workspace(self, parsed) -> Workspace:
        # Generic lookup — state["external_connection_id"] + state["backend"]
        from donna.integrations.models import Connection
        return Connection.objects.get(
            state__backend="nango",
            state__external_connection_id=parsed["connectionId"],
        ).workspace
```

Same connector class, swap to Composio (hypothetical — illustrating the contract):
```python
@register
class NotionProvider:
    slug = "notion"
    oauth_backend_name = "composio"
    fetch_backend_name = "composio_actions"
    webhook_backend_name = "composio_webhook"
    backend_config = {
        # Composio reads these; Nango never sees them.
        "app_name": "notion",
        "action_ids": ["NOTION_FETCH_PAGES"],
    }
    # adapter_for + resolve_workspace UNCHANGED — they read normalized data.
```

---

## Phase 0 — Backend abstraction refactor (~2d)

**Goal:** extract backend Protocols, wrap current implementations as
`Donna*Backend`. Existing connectors switch to declaring backend names.
Zero behaviour change.

### 0.1 New module: `core/integrations/backends/`

```
server/donna/core/integrations/backends/
├── __init__.py            # registry of backends
├── oauth_backend.py       # OAuthBackend Protocol + DonnaOAuthBackend wrapping BaseOAuthHandler
├── fetch_backend.py       # FetchBackend Protocol + DonnaCeleryFetchBackend wrapping current task dispatch
├── webhook_backend.py     # WebhookBackend Protocol + DonnaHmacWebhookBackend wrapping BaseWebhookHandler
└── registry.py            # backend name → backend class lookup
```

**New file:** `backends/__init__.py`

```python
"""Backend abstraction layer.

Each connector picks one OAuthBackend + one FetchBackend + one
WebhookBackend. Names map to classes via the backend registry. Adding
a new backend = drop a file here + register; never touch connector code.
"""
from .oauth_backend import OAuthBackend, DonnaOAuthBackend
from .fetch_backend import FetchBackend, DonnaCeleryFetchBackend
from .webhook_backend import WebhookBackend, DonnaHmacWebhookBackend
from .registry import (
    OAUTH_BACKENDS,
    FETCH_BACKENDS,
    WEBHOOK_BACKENDS,
    register_oauth_backend,
    register_fetch_backend,
    register_webhook_backend,
)

__all__ = [
    "OAuthBackend", "DonnaOAuthBackend",
    "FetchBackend", "DonnaCeleryFetchBackend",
    "WebhookBackend", "DonnaHmacWebhookBackend",
    "OAUTH_BACKENDS", "FETCH_BACKENDS", "WEBHOOK_BACKENDS",
    "register_oauth_backend", "register_fetch_backend", "register_webhook_backend",
]
```

**New file:** `backends/registry.py`

```python
"""Backend name → class registry. Lookup at dispatch time."""
from __future__ import annotations
from typing import Type

OAUTH_BACKENDS: dict[str, Type] = {}
FETCH_BACKENDS: dict[str, Type] = {}
WEBHOOK_BACKENDS: dict[str, Type] = {}


def register_oauth_backend(name: str):
    def wrap(cls):
        OAUTH_BACKENDS[name] = cls
        return cls
    return wrap


def register_fetch_backend(name: str):
    def wrap(cls):
        FETCH_BACKENDS[name] = cls
        return cls
    return wrap


def register_webhook_backend(name: str):
    def wrap(cls):
        WEBHOOK_BACKENDS[name] = cls
        return cls
    return wrap
```

**New file:** `backends/oauth_backend.py`

```python
"""OAuth backend abstraction. Wraps existing BaseOAuthHandler."""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from .registry import register_oauth_backend

if TYPE_CHECKING:
    from donna.integrations.models import ClientCredentials, Connection
    from donna.workspaces.models import Workspace
    from donna.users.models import User


@runtime_checkable
class OAuthBackend(Protocol):
    """Contract every OAuth backend implements."""

    def build_authorize_url(
        self,
        *,
        workspace: "Workspace",
        user: "User",
        connector_slug: str,
        redirect_to: str = "",
    ) -> str: ...

    def handle_callback(
        self,
        *,
        vendor_slug: str,
        code: str,
        state: str,
        request_query: dict,
    ) -> "Connection": ...

    def revoke(self, connection: "Connection") -> None: ...

    def get_access_token(self, connection: "Connection") -> str:
        """Return a valid access token for outbound calls. Refresh if needed."""
        ...

    def refresh(self, connection: "Connection") -> None: ...


@register_oauth_backend("donna")
class DonnaOAuthBackend:
    """
    Wraps the current BaseOAuthHandler + RegistryService.handle_callback
    logic so existing connectors keep working unchanged.

    Stateless — all state lives on ClientCredentials + OAuthToken rows
    in Donna's DB.
    """

    def build_authorize_url(self, *, workspace, user, connector_slug, redirect_to=""):
        # Delegates to existing RegistryService.initiate_connect logic.
        # See server/donna/integrations/services.py:RegistryService.initiate_connect.
        from donna.core.integrations import NotConfigured, get as get_provider
        from donna.integrations.models import ClientCredentials

        cls = get_provider(connector_slug)
        provider = cls()
        oauth_config = ClientCredentials.objects.resolve(
            cls.oauth_provider_slug, workspace=workspace,
        )
        if oauth_config is None:
            raise NotConfigured(
                f"No enabled ClientCredentials({cls.oauth_provider_slug!r}) "
                f"row for workspace={workspace.id} or deployment-wide."
            )
        handler = provider.oauth_handler(oauth_config)
        state_payload = {
            "user_id":              str(user.id),
            "workspace_id":         str(workspace.id),
            "slug":                 connector_slug,
            "redirect_to":          redirect_to or "",
            "client_credentials_id": str(oauth_config.id),
            "backend":              "donna",
        }
        return handler.build_authorize_url(state_payload=state_payload)

    def handle_callback(self, *, vendor_slug, code, state, request_query):
        # Delegates to existing RegistryService.handle_callback. Returns the
        # Connection (after token + connection upsert).
        from donna.integrations.services import RegistryService

        service = RegistryService(current_user=None, company=None)
        token = service.handle_callback(slug=vendor_slug, code=code, state=state)
        # handle_callback creates Connection internally; pull it back out.
        connection = token.connections.first()  # type: ignore[attr-defined]
        return connection

    def revoke(self, connection):
        # Existing RegistryService.disconnect path.
        from donna.core.integrations import get as get_provider
        from donna.integrations.models import ClientCredentials

        cls = get_provider(connection.provider_slug)
        oauth_config = ClientCredentials.objects.resolve(
            cls.oauth_provider_slug, workspace=connection.workspace,
        )
        if oauth_config is None or connection.token_id is None:
            return
        provider = cls()
        try:
            provider.oauth_handler(oauth_config).revoke(connection.token)
        except Exception:
            pass

    def get_access_token(self, connection):
        if connection.token is None:
            raise ValueError(f"connection {connection.id} has no token")
        # Refresh-on-demand left to existing handler logic; for v0 just return.
        return connection.token.access_token

    def refresh(self, connection):
        from donna.core.integrations import get as get_provider
        from donna.integrations.models import ClientCredentials

        cls = get_provider(connection.provider_slug)
        oauth_config = ClientCredentials.objects.resolve(
            cls.oauth_provider_slug, workspace=connection.workspace,
        )
        handler = cls().oauth_handler(oauth_config)
        parsed = handler.refresh(connection.token)
        connection.token.access_token = parsed["access_token"]
        if parsed.get("refresh_token"):
            connection.token.refresh_token = parsed["refresh_token"]
        connection.token.expires_at = parsed.get("expires_at")
        connection.token.save(update_fields=["access_token", "refresh_token", "expires_at"])
```

**New file:** `backends/fetch_backend.py`

```python
"""Fetch backend abstraction.

Current Donna pattern: webhook view → resolve_workspace → dispatch_webhook
→ Celery task → BaseHTTPClient → bronze + DP + cortex hop. Encapsulated
as DonnaCeleryFetchBackend so the dispatch path is interchangeable with
Nango's sync-receiver path.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from .registry import register_fetch_backend

if TYPE_CHECKING:
    from donna.integrations.models import Connection


@runtime_checkable
class FetchBackend(Protocol):
    def kickoff_initial_sync(self, connection: "Connection") -> None: ...
    def trigger_sync(self, connection: "Connection", *, full: bool = False) -> None: ...
    def handle_sync_webhook(self, payload: dict) -> int: ...


@register_fetch_backend("donna_celery")
class DonnaCeleryFetchBackend:
    """No-op for kickoff/trigger — Donna connectors rely on inbound vendor
    webhooks. handle_sync_webhook unused (the dispatch path is on the
    connector's `dispatch_webhook` method, kept for compatibility)."""

    def kickoff_initial_sync(self, connection):
        # Some connectors (Drive, Mail) implement initial backfill on connect.
        # Delegate to provider.on_connect hook (already invoked by
        # RegistryService.handle_callback). No-op here.
        return

    def trigger_sync(self, connection, *, full=False):
        # Manual re-sync — connector-specific Celery task. Look up by
        # convention or expose via provider.trigger_sync hook.
        return

    def handle_sync_webhook(self, payload):
        # Donna backend uses ProviderWebhookView path; not this method.
        return 0
```

**New file:** `backends/webhook_backend.py`

```python
"""Webhook backend abstraction. Wraps existing BaseWebhookHandler."""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from .registry import register_webhook_backend

if TYPE_CHECKING:
    from donna.integrations.models import Connection


@runtime_checkable
class WebhookBackend(Protocol):
    signature_header: str

    def verify(
        self,
        payload: bytes,
        signature: str | None,
        *,
        connection: "Connection | None" = None,
    ) -> bool: ...

    def parse(self, payload: bytes) -> dict: ...


@register_webhook_backend("donna_hmac")
class DonnaHmacWebhookBackend:
    """Wraps BaseWebhookHandler — current behaviour, per-vendor HMAC secret."""

    signature_header = "X-Signature"  # overridden per-connector via handler

    def __init__(self, handler):
        # handler is a BaseWebhookHandler instance from connector.webhook_handler()
        self._handler = handler
        self.signature_header = handler.signature_header

    def verify(self, payload, signature, *, connection=None):
        return self._handler.verify(payload, signature, connection=connection)

    def parse(self, payload):
        return self._handler.parse(payload)
```

### 0.2 Extend `IntegrationProvider` Protocol

**Edit:** `core/integrations/provider.py` — add backend-name fields + opaque
`backend_config` dict. NO platform-specific field names (no `nango_*`,
no `composio_*`) in the Protocol — those leak the abstraction.

```python
# core/integrations/provider.py
@runtime_checkable
class IntegrationProvider(Protocol):
    # ── Identity ──────────────────────────────────────────
    slug: ClassVar[str]
    display_name: ClassVar[str]
    category: ClassVar[str]

    # ── NEW: backend selection (by name; lookups in INTEGRATION_BACKENDS) ─
    # Defaults preserve current behaviour for Donna-native connectors.
    oauth_backend_name:   ClassVar[str] = "donna"
    fetch_backend_name:   ClassVar[str] = "donna_celery"
    webhook_backend_name: ClassVar[str] = "donna_hmac"

    # ── NEW: per-backend opaque config (string-keyed) ─────
    # The active backend reads its own keys; framework code never inspects
    # this. Swapping the platform = swap backend classes + change the key
    # set in this dict. Connector contract stays stable.
    #
    # Example for "nango" backend:
    #   backend_config = {
    #       "provider_config_key": "notion",
    #       "catalog_key":         "notion",
    #       "sync_models":         ("Page",),
    #       "sync_frequency":      "every 1 hour",
    #       "oauth_scopes":        [],
    #   }
    #
    # Example for "composio" backend:
    #   backend_config = {
    #       "app_name":  "notion",
    #       "action_ids": ["NOTION_FETCH_PAGES"],
    #   }
    backend_config: ClassVar[dict[str, Any]] = {}

    # ── Existing OAuth coupling (Donna backend only) ──────
    oauth_provider_slug: ClassVar[str]
    token_scope: ClassVar[TokenScope]
    default_authorize_url: ClassVar[str]
    default_token_url: ClassVar[str]
    default_scopes: ClassVar[list[str]]

    # ── Capabilities / lifecycle / hooks ──────────────────
    # (unchanged)
    ...
```

### 0.2.1 Backend registry via `settings.INTEGRATION_BACKENDS`

Backends resolve through Django's `import_string` (django.utils.module_loading)
so installing a third-party platform = `pip install + add path in settings`,
zero core edits.

**Edit:** `settings.py`

```python
# Backends resolved at runtime; ordering of installed apps determines which
# `@register_*_backend` decorators run, but settings provides the override.
INTEGRATION_BACKENDS = {
    "oauth": {
        "donna": "donna.core.integrations.backends.oauth_backend.DonnaOAuthBackend",
        # Add or replace below to swap the platform.
        "nango": "donna.core.integrations.backends.nango_oauth.NangoOAuthBackend",
        # "composio": "myapp.integrations.composio.oauth.ComposioOAuthBackend",
    },
    "fetch": {
        "donna_celery": "donna.core.integrations.backends.fetch_backend.DonnaCeleryFetchBackend",
        "nango_sync":   "donna.core.integrations.backends.nango_fetch.NangoFetchBackend",
    },
    "webhook": {
        "donna_hmac":  "donna.core.integrations.backends.webhook_backend.DonnaHmacWebhookBackend",
        "nango_proxy": "donna.core.integrations.backends.nango_webhook.NangoWebhookBackend",
    },
}
```

**Edit:** `core/integrations/backends/registry.py` — resolve lazily.

```python
"""Backend name → class lookup via Django's import_string.

Lazy + cached. Allows third-party packages to ship a backend, install via
pip, register the path in settings.INTEGRATION_BACKENDS — no core edits.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Type

from django.conf import settings
from django.utils.module_loading import import_string


@lru_cache(maxsize=None)
def get_backend(category: str, name: str) -> Type:
    """category ∈ {'oauth', 'fetch', 'webhook'}. name = backend slug."""
    try:
        path = settings.INTEGRATION_BACKENDS[category][name]
    except KeyError as exc:
        raise LookupError(
            f"no {category} backend named {name!r}; "
            f"add to settings.INTEGRATION_BACKENDS[{category!r}]"
        ) from exc
    return import_string(path)


# Convenience facades — same API as before.
class _Resolver:
    def __init__(self, category):
        self.category = category

    def __getitem__(self, name):
        return get_backend(self.category, name)

    def get(self, name, default=None):
        try:
            return get_backend(self.category, name)
        except LookupError:
            return default


OAUTH_BACKENDS   = _Resolver("oauth")
FETCH_BACKENDS   = _Resolver("fetch")
WEBHOOK_BACKENDS = _Resolver("webhook")
```

The `@register_*_backend` decorator pattern stays useful for backends that
ship inside Donna (auto-registers on import); third-party backends go via
settings. Both populate the same lookup.

### 0.3 Migrate existing connectors

**Edit:** `connectors/fathom/provider.py`, `connectors/google/mail/provider.py`,
`connectors/google/drive/provider.py` — add explicit backend declarations.
Since defaults are `"donna" / "donna_celery" / "donna_hmac"`, this is a
no-op for existing connectors. Documented for clarity:

```python
# connectors/fathom/provider.py
@register
class FathomProvider:
    slug = "fathom"
    display_name = "Fathom"
    category = "meetings"

    # Explicit — even though these are defaults.
    oauth_backend_name = "donna"
    fetch_backend_name = "donna_celery"
    webhook_backend_name = "donna_hmac"

    oauth_provider_slug = "fathom"
    # ... rest unchanged
```

### 0.4 Refactor `RegistryService` to dispatch via OAuthBackend

**Edit:** `integrations/services.py` — `RegistryService.initiate_connect`,
`disconnect`, `handle_callback` thin out to backend dispatch.

Before (current `initiate_connect`):
```python
def initiate_connect(self, workspace, user, slug, redirect_to=None):
    cls = get_provider(slug)
    provider = cls()
    oauth_config = ClientCredentials.objects.resolve(...)
    handler = provider.oauth_handler(oauth_config)
    state_payload = {...}
    return handler.build_authorize_url(state_payload=state_payload)
```

After:
```python
def initiate_connect(self, workspace, user, slug, redirect_to=None):
    from donna.core.integrations.backends import OAUTH_BACKENDS

    cls = get_provider(slug)
    backend = OAUTH_BACKENDS[cls.oauth_backend_name]()
    return backend.build_authorize_url(
        workspace=workspace,
        user=user,
        connector_slug=slug,
        redirect_to=redirect_to or "",
    )
```

Same shape for `disconnect` and `handle_callback`:

```python
@transaction.atomic
def disconnect(self, workspace, user, slug):
    from donna.core.integrations.backends import OAUTH_BACKENDS
    from .models import Connection

    cls = get_provider(slug)
    backend = OAUTH_BACKENDS[cls.oauth_backend_name]()

    conn = (
        Connection.objects
        .filter(workspace=workspace, user=user, provider_slug=slug)
        .first()
        or Connection.objects
        .filter(workspace=workspace, provider_slug=slug)
        .first()
    )
    if conn is None:
        return False

    backend.revoke(conn)
    conn.delete()
    return True


@transaction.atomic
def handle_callback(self, slug, code, state, request_query=None):
    from donna.core.integrations.backends import OAUTH_BACKENDS

    # Decode state to find the connector + backend.
    from donna.core.integrations.oauth import BaseOAuthHandler
    state_payload = BaseOAuthHandler.verify_state(state)
    connector_slug = state_payload["slug"]
    cls = get_provider(connector_slug)

    backend = OAUTH_BACKENDS[cls.oauth_backend_name]()
    return backend.handle_callback(
        vendor_slug=slug,
        code=code,
        state=state,
        request_query=request_query or {},
    )
```

Notice the return type of `handle_callback` shifts from `OAuthToken` to
`Connection`. The `ProviderOAuthCallbackView` needs the corresponding
update:

**Edit:** `integrations/api/v1/oauth.py:ProviderOAuthCallbackView.get`:

```python
# was: token = service.handle_callback(slug=slug, code=code, state=state)
# now:
connection = service.handle_callback(
    slug=slug, code=code, state=state,
    request_query=dict(request.query_params),
)
logger.info(
    "oauth_callback_success",
    extra={"slug": slug, "connection_id": str(connection.id) if connection else None},
)
```

### 0.5 Refactor `ProviderWebhookView` to dispatch via WebhookBackend

**Edit:** `integrations/api/v1/webhooks.py:ProviderWebhookView.post`:

Before:
```python
provider = provider_cls()
handler = provider.webhook_handler()
signature = request.headers.get(handler.signature_header)
parsed = handler.parse(payload)
# ... resolve workspace ...
handler.verify(payload, signature, connection=connection)
dispatcher = getattr(provider, "dispatch_webhook", None)
dispatcher(parsed=parsed, workspace=workspace)
```

After:
```python
from donna.core.integrations.backends import WEBHOOK_BACKENDS

provider = provider_cls()
backend_name = provider_cls.webhook_backend_name
backend_cls = WEBHOOK_BACKENDS[backend_name]

# Donna backend wraps the connector's BaseWebhookHandler; Nango backend
# is constructed without per-connector state.
if backend_name == "donna_hmac":
    backend = backend_cls(provider.webhook_handler())
else:
    backend = backend_cls()

signature = request.headers.get(backend.signature_header)
parsed = backend.parse(payload)
# ... resolve workspace, verify, dispatch (unchanged) ...
```

### 0.6 Model changes — none yet

Phase 0 doesn't touch models. Backend names live on the connector class.
Existing `ClientCredentials` + `OAuthToken` + `Connection` rows keep
working as-is.

### 0.7 Tests

- `core/integrations/tests/test_backends.py` — registry registration,
  `OAUTH_BACKENDS["donna"]` is `DonnaOAuthBackend`, etc.
- `integrations/tests/test_services_backend_dispatch.py` — `initiate_connect`
  picks the right backend by `cls.oauth_backend_name`; existing Fathom
  flow still passes end-to-end.
- Run existing connector tests — they must pass unchanged.

```bash
docker exec donna-server bash -lc \
  "cd /opt/donna && DATABASE_HOST=donna-database \
   uv run python -m django test donna.integrations donna.core.integrations -v 2"
```

---

## Phase 1 — Nango wiring (~3d)

**Goal:** all three Nango backend implementations + sync-webhook receiver
+ Nango SDK wrapper.

### 1.1 Nango SDK client wrapper

**New file:** `core/integrations/backends/_nango_client.py`

```python
"""Single facade over Nango's REST API.

Uses httpx directly rather than the official SDK to keep dependency
surface small and to support both Cloud + self-host with the same code.
Cloud: NANGO_BASE_URL=https://api.nango.dev, NANGO_SECRET_KEY=...
Self-host: NANGO_BASE_URL=http://nango-server:3003.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from django.conf import settings


logger = logging.getLogger(__name__)


class NangoClient:
    """Thin REST wrapper. Read-only for now (Nango Connect UI handles writes)."""

    def __init__(
        self,
        base_url: str | None = None,
        secret_key: str | None = None,
        timeout: float = 30.0,
    ):
        self.base_url = (base_url or settings.NANGO_BASE_URL).rstrip("/")
        self.secret_key = secret_key or settings.NANGO_SECRET_KEY
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
        }

    # ── Connect session ─────────────────────────────────────────────────────
    def create_connect_session(
        self,
        *,
        end_user_id: str,
        end_user_email: str | None = None,
        allowed_integrations: list[str] | None = None,
        organization_id: str | None = None,
    ) -> dict[str, Any]:
        """Returns {token, expires_at}. Token feeds the Nango Connect UI."""
        body: dict[str, Any] = {"end_user": {"id": end_user_id}}
        if end_user_email:
            body["end_user"]["email"] = end_user_email
        if organization_id:
            body["organization"] = {"id": organization_id}
        if allowed_integrations:
            body["allowed_integrations"] = allowed_integrations
        resp = httpx.post(
            f"{self.base_url}/connect/sessions",
            headers=self._headers(),
            json=body,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["data"]

    # ── Connection lookup ───────────────────────────────────────────────────
    def get_connection(
        self,
        *,
        connection_id: str,
        provider_config_key: str,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Returns {credentials, metadata, connection_config, ...}."""
        params = {
            "provider_config_key": provider_config_key,
            "force_refresh": str(force_refresh).lower(),
        }
        resp = httpx.get(
            f"{self.base_url}/connection/{connection_id}",
            headers=self._headers(),
            params=params,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def delete_connection(
        self,
        *,
        connection_id: str,
        provider_config_key: str,
    ) -> None:
        params = {"provider_config_key": provider_config_key}
        resp = httpx.delete(
            f"{self.base_url}/connection/{connection_id}",
            headers=self._headers(),
            params=params,
            timeout=self.timeout,
        )
        resp.raise_for_status()

    # ── Sync control ────────────────────────────────────────────────────────
    def trigger_sync(
        self,
        *,
        connection_id: str,
        provider_config_key: str,
        sync_names: list[str],
        full_resync: bool = False,
    ) -> None:
        resp = httpx.post(
            f"{self.base_url}/sync/trigger",
            headers=self._headers(),
            json={
                "connection_id":        connection_id,
                "provider_config_key":  provider_config_key,
                "syncs":                sync_names,
                "full_resync":          full_resync,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()

    def fetch_records(
        self,
        *,
        connection_id: str,
        provider_config_key: str,
        model: str,
        modified_after: str | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Returns {records, next_cursor}."""
        params = {
            "connection_id":        connection_id,
            "provider_config_key":  provider_config_key,
            "model":                model,
            "limit":                str(limit),
        }
        if modified_after:
            params["modified_after"] = modified_after
        if cursor:
            params["cursor"] = cursor
        resp = httpx.get(
            f"{self.base_url}/records",
            headers=self._headers(),
            params=params,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    # ── Proxy (Tier 1 transport replacement use case) ───────────────────────
    def proxy(
        self,
        *,
        connection_id: str,
        provider_config_key: str,
        method: str,
        endpoint: str,
        params: dict | None = None,
        data: Any | None = None,
        headers: dict | None = None,
    ) -> httpx.Response:
        """Generic proxy call — uses Nango's stored token to hit vendor API."""
        req_headers = {
            **self._headers(),
            "Connection-Id":        connection_id,
            "Provider-Config-Key":  provider_config_key,
        }
        if headers:
            req_headers.update(headers)
        return httpx.request(
            method.upper(),
            f"{self.base_url}/proxy{endpoint}",
            headers=req_headers,
            params=params,
            json=data if isinstance(data, dict) else None,
            content=data if not isinstance(data, dict) else None,
            timeout=self.timeout,
        )
```

### 1.2 `NangoOAuthBackend`

**New file:** `core/integrations/backends/nango_oauth.py`

```python
"""Nango-backed OAuth.

Authorize URL = a session-token wrapped Nango Connect UI link. Donna
generates the session via Nango's REST API, then redirects the user
to Nango Connect. Connect handles the entire OAuth dance with the
vendor, persists tokens server-side, and redirects back to Donna with
?connection_id=<nango_uuid>.
"""
from __future__ import annotations

import logging
from urllib.parse import urlencode

from django.conf import settings
from django.core import signing

from ._nango_client import NangoClient
from .registry import register_oauth_backend
from .oauth_backend import OAuthBackend
from ..exceptions import OAuthExchangeFailed, OAuthStateInvalid


logger = logging.getLogger(__name__)


_STATE_SALT = "donna.integrations.oauth.state"
_STATE_MAX_AGE_SECONDS = 600


@register_oauth_backend("nango")
class NangoOAuthBackend:
    """OAuth via Nango Connect UI.

    Notes:
    - Token material lives at Nango. Donna stores nango_connection_id
      on Connection.state["nango_connection_id"].
    - get_access_token() round-trips to Nango per call (Nango handles
      refresh under the hood; force_refresh=False is the default).
    - Token cache: 60s TTL keyed on (connection_id, provider_config_key)
      to amortize Nango calls on bursty workloads.
    """

    def __init__(self, client: NangoClient | None = None):
        self.client = client or NangoClient()

    # ── Authorize URL ───────────────────────────────────────────────────────
    def build_authorize_url(
        self, *, workspace, user, connector_slug, redirect_to="",
    ) -> str:
        from donna.core.integrations import get as get_provider

        cls = get_provider(connector_slug)
        provider_config_key = cls.nango_provider_config_key
        if not provider_config_key:
            raise OAuthExchangeFailed(
                f"connector {connector_slug!r} declares oauth_backend='nango' "
                f"but nango_provider_config_key is empty."
            )

        # Create Connect session — Nango returns a short-lived token usable
        # only by this end_user.
        # end_user_id pattern: "<workspace_id>:<user_id>" so callback can
        # recover both. Nango treats this as opaque.
        end_user_id = f"{workspace.id}:{user.id}"
        session = self.client.create_connect_session(
            end_user_id=end_user_id,
            end_user_email=getattr(user, "email", None),
            allowed_integrations=[provider_config_key],
            organization_id=str(workspace.id),
        )
        # Donna's state token still carries enough to identify the connector
        # on callback (Nango's callback URL pattern is fixed per integration).
        state_payload = {
            "workspace_id":         str(workspace.id),
            "user_id":              str(user.id),
            "slug":                 connector_slug,
            "redirect_to":          redirect_to or "",
            "backend":              "nango",
            "nango_session_token":  session["token"],
        }
        state = signing.dumps(state_payload, salt=_STATE_SALT)
        params = {
            "session_token": session["token"],
            # Donna-side state echoed back unchanged by Nango Connect.
            "params[state]": state,
        }
        return f"{settings.NANGO_CONNECT_UI_URL}?{urlencode(params)}"

    # ── Callback ────────────────────────────────────────────────────────────
    def handle_callback(self, *, vendor_slug, code, state, request_query):
        """Nango Connect redirects with ?connection_id=...&providerConfigKey=...

        ``code`` is unused for Nango — kept for signature symmetry. State is
        Donna-side metadata; verified here.
        """
        from donna.integrations.models import Connection
        from donna.workspaces.models import Workspace
        from donna.users.models import User

        try:
            state_payload = signing.loads(
                state, salt=_STATE_SALT, max_age=_STATE_MAX_AGE_SECONDS,
            )
        except signing.BadSignature as exc:
            raise OAuthStateInvalid(f"invalid state: {exc}") from exc

        nango_connection_id = request_query.get("connection_id")
        provider_config_key = request_query.get("providerConfigKey")
        if not nango_connection_id or not provider_config_key:
            raise OAuthExchangeFailed(
                "Nango callback missing connection_id or providerConfigKey"
            )

        # Sanity check — providerConfigKey from Nango must match what the
        # connector declared.
        from donna.core.integrations import get as get_provider
        cls = get_provider(state_payload["slug"])
        if cls.nango_provider_config_key != provider_config_key:
            raise OAuthStateInvalid(
                f"connector {state_payload['slug']} declares "
                f"provider_config_key={cls.nango_provider_config_key!r} but "
                f"Nango returned {provider_config_key!r}"
            )

        workspace = Workspace.objects.get(id=state_payload["workspace_id"])
        user = User.objects.get(id=state_payload["user_id"])

        conn_user = user if cls.token_scope == "user" else None
        # Generic state shape — NOT nango-specific. Backend writes its name
        # under "backend" and the platform-side handle under
        # "external_connection_id"; per-platform extras go in "raw".
        connection, _ = Connection.objects.update_or_create(
            workspace=workspace,
            user=conn_user,
            provider_slug=cls.slug,
            defaults={
                "token":  None,  # platform holds tokens; nullable for non-donna backend
                "config": dict(getattr(cls, "default_config", {}) or {}),
                "state": {
                    "backend":               "nango",
                    "external_connection_id": nango_connection_id,
                    "raw": {
                        "provider_config_key": provider_config_key,
                    },
                },
            },
        )
        return connection

    # ── Revoke ──────────────────────────────────────────────────────────────
    def revoke(self, connection):
        nango_id = (connection.state or {}).get("external_connection_id")
        if not nango_id:
            return
        from donna.core.integrations import get as get_provider
        cls = get_provider(connection.provider_slug)
        provider_config_key = cls.backend_config.get("provider_config_key") or cls.slug
        try:
            self.client.delete_connection(
                connection_id=nango_id,
                provider_config_key=provider_config_key,
            )
        except Exception as exc:
            logger.warning(
                "nango_revoke_failed",
                extra={
                    "connection_id": str(connection.id),
                    "external_connection_id": nango_id,
                    "error": str(exc),
                },
            )

    # ── Token fetch (for Tier-1-style proxy use) ────────────────────────────
    def get_access_token(self, connection):
        """On-demand fetch. Nango returns the live token (refreshed if needed)."""
        nango_id = (connection.state or {}).get("external_connection_id")
        if not nango_id:
            raise ValueError(f"connection {connection.id} has no external_connection_id")
        from donna.core.integrations import get as get_provider
        cls = get_provider(connection.provider_slug)
        provider_config_key = cls.backend_config.get("provider_config_key") or cls.slug
        resp = self.client.get_connection(
            connection_id=nango_id,
            provider_config_key=provider_config_key,
        )
        return resp["credentials"]["access_token"]

    def refresh(self, connection):
        """Force Nango to refresh server-side."""
        nango_id = (connection.state or {}).get("external_connection_id")
        from donna.core.integrations import get as get_provider
        cls = get_provider(connection.provider_slug)
        provider_config_key = cls.backend_config.get("provider_config_key") or cls.slug
        self.client.get_connection(
            connection_id=nango_id,
            provider_config_key=provider_config_key,
            force_refresh=True,
        )
```

### 1.3 `NangoFetchBackend`

**New file:** `core/integrations/backends/nango_fetch.py`

```python
"""Nango sync receiver.

Nango runs syncs server-side per its declared schedule. On each sync
completion (or webhook-triggered sync), Nango POSTs a notification to
Donna's webhook endpoint. The payload shape:

    {
        "type": "sync",
        "connectionId": "<nango uuid>",
        "providerConfigKey": "notion",
        "syncName": "pages",
        "model": "Page",
        "responseResults": {"added": 5, "updated": 1, "deleted": 0},
        "modifiedAfter": "2026-06-24T...",
    }

Donna's handler fetches the actual records via the Nango records API
(pull, not push — keeps payload size bounded), canonicalizes each, and
writes bronze + DP + cortex hop.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ._nango_client import NangoClient
from .registry import register_fetch_backend


if TYPE_CHECKING:
    from donna.integrations.models import Connection


logger = logging.getLogger(__name__)


@register_fetch_backend("nango_sync")
class NangoFetchBackend:
    def __init__(self, client: NangoClient | None = None):
        self.client = client or NangoClient()

    def kickoff_initial_sync(self, connection):
        """Triggered after connect — Nango auto-starts a sync; no-op here."""
        return

    def trigger_sync(self, connection, *, full=False):
        from donna.core.integrations import get as get_provider

        cls = get_provider(connection.provider_slug)
        nango_id = (connection.state or {}).get("external_connection_id")
        sync_names = list(cls.backend_config.get("sync_models", ()) or ())
        provider_config_key = cls.backend_config.get("provider_config_key") or cls.slug
        if not nango_id or not sync_names:
            return
        self.client.trigger_sync(
            connection_id=nango_id,
            provider_config_key=provider_config_key,
            sync_names=sync_names,
            full_resync=full,
        )

    def handle_sync_webhook(self, payload):
        """Called from the Nango webhook view.

        Returns count of records processed.
        """
        from donna.core.integrations import get as get_provider
        from donna.integrations.models import Connection

        nango_id = payload.get("connectionId")
        provider_config_key = payload.get("providerConfigKey")
        model = payload.get("model")
        modified_after = payload.get("modifiedAfter")

        if not (nango_id and provider_config_key and model):
            logger.warning("nango_sync_payload_missing_fields", extra=payload)
            return 0

        # Resolve connection via generic state keys.
        try:
            connection = Connection.objects.get(
                state__backend="nango",
                state__external_connection_id=nango_id,
            )
        except Connection.DoesNotExist:
            logger.warning("nango_sync_unknown_connection", extra={"nango_id": nango_id})
            return 0

        cls = get_provider(connection.provider_slug)
        expected_pck = cls.backend_config.get("provider_config_key") or cls.slug
        if expected_pck != provider_config_key:
            logger.warning(
                "nango_sync_provider_mismatch",
                extra={
                    "connection_id": str(connection.id),
                    "expected": expected_pck,
                    "got": provider_config_key,
                },
            )
            return 0

        # Pull records (cursor-paginated).
        provider = cls()
        cursor: str | None = None
        processed = 0
        while True:
            page = self.client.fetch_records(
                connection_id=nango_id,
                provider_config_key=provider_config_key,
                model=model,
                modified_after=modified_after,
                cursor=cursor,
            )
            for record in page.get("records", []):
                _ingest_one(connection, provider, model, record)
                processed += 1
            cursor = page.get("next_cursor")
            if not cursor:
                break
        return processed


def _ingest_one(connection, provider, model, record):
    """Write bronze + DP + dispatch cortex hop. Idempotent via uq constraint."""
    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage
    from donna.integrations.models import DeliveryPackage
    import hashlib
    import json

    adapter = provider.adapter_for(record)
    canonical = adapter.to_canonical()  # CanonicalEntity instance

    # Bronze key — content-addressed so re-deliveries dedup.
    raw_bytes = json.dumps(record, sort_keys=True).encode()
    content_hash = hashlib.sha256(raw_bytes).hexdigest()
    bronze_key = (
        f"{connection.workspace.id}/"
        f"{connection.provider_slug}/"
        f"{model.lower()}/"
        f"{content_hash}.json"
    )
    if not default_storage.exists(bronze_key):
        default_storage.save(bronze_key, ContentFile(raw_bytes))

    dp, created = DeliveryPackage.objects.update_or_create(
        workspace=connection.workspace,
        provider=connection.provider_slug,
        provider_item_id=str(canonical.external_id),
        defaults={
            "provider_item_type": model.lower(),
            "title":              canonical.title or "",
            "occurred_at":        canonical.occurred_at,
            "metadata":           canonical.metadata,
            "canonical_type":     canonical.canonical_type,
            "canonical_payload":  canonical.as_payload(),
            "storage_key":        bronze_key,
        },
    )

    # Dispatch cortex hop — same task used by Drive/Mail.
    from donna.cortex.tasks import cortex_hop_from_dp
    cortex_hop_from_dp.delay(str(dp.id))
```

### 1.4 `NangoWebhookBackend`

**New file:** `core/integrations/backends/nango_webhook.py`

```python
"""Nango → Donna webhook signature verifier.

Nango signs every outbound webhook with a single deployment-wide secret
(separate from any vendor secrets). The header is
``X-Nango-Signature`` containing ``sha256=<hex>``.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging

from django.conf import settings

from .registry import register_webhook_backend
from ..exceptions import WebhookPayloadInvalid, WebhookSignatureInvalid


logger = logging.getLogger(__name__)


@register_webhook_backend("nango_proxy")
class NangoWebhookBackend:
    signature_header = "X-Nango-Signature"

    def verify(self, payload, signature, *, connection=None):
        if not signature:
            raise WebhookSignatureInvalid("missing X-Nango-Signature")
        secret = (getattr(settings, "NANGO_WEBHOOK_SECRET", "") or "").encode()
        if not secret:
            raise WebhookSignatureInvalid("NANGO_WEBHOOK_SECRET not configured")
        cleaned = signature[len("sha256="):] if signature.startswith("sha256=") else signature
        expected = hmac.new(secret, payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, cleaned):
            raise WebhookSignatureInvalid("Nango HMAC mismatch")
        return True

    def parse(self, payload):
        try:
            return json.loads(payload)
        except (ValueError, TypeError) as exc:
            raise WebhookPayloadInvalid(f"invalid JSON: {exc}") from exc
```

### 1.5 Single Nango webhook endpoint

**New URL:** `POST /api/v1/integrations/nango/webhook` — bypasses
`X-Workspace-Id` (already in `IGNORED_SUFFIXES`).

**New view:** `integrations/api/v1/nango_webhook.py`

```python
"""Nango webhook receiver.

One endpoint for ALL Nango-backed connectors. Nango's webhook payload
identifies the connection + integration; we dispatch to the right
connector internally.
"""
from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from donna.core.integrations.backends import (
    FETCH_BACKENDS,
    WEBHOOK_BACKENDS,
)
from donna.core.integrations.exceptions import (
    WebhookPayloadInvalid,
    WebhookSignatureInvalid,
)


logger = logging.getLogger(__name__)


class NangoWebhookView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        backend = WEBHOOK_BACKENDS["nango_proxy"]()
        signature = request.headers.get(backend.signature_header)
        payload = request.body

        try:
            backend.verify(payload, signature)
        except WebhookSignatureInvalid as exc:
            logger.warning("nango_webhook_signature_invalid", extra={"error": str(exc)})
            return Response({"detail": "invalid signature"}, status=401)

        try:
            parsed = backend.parse(payload)
        except WebhookPayloadInvalid as exc:
            logger.warning("nango_webhook_payload_invalid", extra={"error": str(exc)})
            return Response({"detail": "invalid payload"}, status=400)

        event_type = parsed.get("type")
        if event_type == "sync":
            fetch = FETCH_BACKENDS["nango_sync"]()
            try:
                count = fetch.handle_sync_webhook(parsed)
            except Exception:
                logger.exception("nango_sync_webhook_failed", extra={"payload": parsed})
                return Response(
                    {"detail": "internal error processing sync"},
                    status=500,
                )
            return Response({"processed": count}, status=200)

        if event_type == "auth":
            # Connection created/updated/deleted from Nango side.
            # No-op for v1 — Connection is created in NangoOAuthBackend.handle_callback.
            return Response(status=200)

        if event_type == "forward":
            # Vendor webhook proxied through Nango (e.g. real-time updates).
            # For v1, treat as trigger to fetch records via nango_sync path.
            logger.info("nango_forward_webhook_ignored", extra={"payload": parsed})
            return Response(status=200)

        logger.info("nango_unknown_webhook_type", extra={"type": event_type})
        return Response(status=200)
```

**Edit:** `integrations/urls.py` — register the new endpoint.

```python
# integrations/urls.py
urlpatterns = [
    # ... existing patterns ...
    path("nango/webhook", NangoWebhookView.as_view(), name="nango-webhook"),
]
```

**Edit:** `donna/settings.py` — add Nango settings.

```python
# Nango — managed integration platform (long-tail connectors).
NANGO_BASE_URL = env.str("NANGO_BASE_URL", default="")     # "" disables Nango backend
NANGO_SECRET_KEY = env.str("NANGO_SECRET_KEY", default="")
NANGO_WEBHOOK_SECRET = env.str("NANGO_WEBHOOK_SECRET", default="")
NANGO_CONNECT_UI_URL = env.str(
    "NANGO_CONNECT_UI_URL",
    default="https://connect.nango.dev",
)

# Add to IGNORED_PATHS / IGNORED_SUFFIXES for middleware bypass.
IGNORED_PATHS = [
    # ... existing ...
    "/api/v1/integrations/nango/",
]
```

### 1.6 Connection model — add Nango fields

**Migration 0005:** make `Connection.token` nullable + add `nango_connection_id`.

**Edit:** `integrations/models.py`:

```python
class Connection(TimestampsMixin):
    # ... existing fields ...

    # WAS: token = ForeignKey(OAuthToken, on_delete=CASCADE, ...)
    # NOW: nullable — Nango-backed connections have no Donna OAuthToken.
    token = models.ForeignKey(
        OAuthToken,
        on_delete=models.CASCADE,
        null=True,                                    # CHANGED
        blank=True,                                   # CHANGED
        related_name="connections",
        related_query_name="connection",
        help_text=_(
            "Donna-backend connections only. Null for Nango-backed "
            "connections (Nango holds the tokens; "
            "Connection.state['nango_connection_id'] points to the "
            "Nango side)."
        ),
    )
    # state already has the flexibility — nango_connection_id stored under
    # state["nango_connection_id"]. No new column needed.

    class Meta:
        # Add constraint: token XOR nango_connection_id
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "user", "provider_slug"],
                name="uq_connection_ws_user_provider",
            ),
            models.CheckConstraint(
                check=(
                    Q(token__isnull=False) |
                    (Q(token__isnull=True) & ~Q(state={}))
                ),
                name="connection_has_token_or_nango_id",
            ),
        ]
        indexes = [
            # ... existing ...
            # NEW — fast lookup from Nango webhook.
            models.Index(
                fields=["state"],
                name="conn_state_nango_id_idx",
                condition=Q(state__has_key="nango_connection_id"),
            ),
        ]
```

The state→idx GIN is optional in Phase 1; for Postgres a simple
JSONB GIN on the whole `state` column works:

```python
# migration 0005 — illustrative:
from django.contrib.postgres.indexes import GinIndex

GinIndex(fields=["state"], name="conn_state_gin_idx")
```

### 1.7 ClientCredentials seed for `nango` slug

`ClientCredentials.objects.resolve("nango", ...)` is unused for Nango
backend — there's no per-vendor row needed. The Nango secret key lives
in env vars + `settings.NANGO_SECRET_KEY`, not in `ClientCredentials`.

**Decision:** skip adding any `ClientCredentials` row for Nango. Backend
selection happens on the connector class, not via DB lookup. This keeps
`ClientCredentials` semantics narrow ("OAuth-app creds you negotiated
with a vendor").

### 1.8 Tests

```bash
docker exec donna-server bash -lc "cd /opt/donna && \
  DATABASE_HOST=donna-database \
  uv run python -m django test \
    donna.core.integrations.backends.tests \
    donna.integrations.tests.test_nango_webhook \
    -v 2"
```

Key tests:
- `test_nango_oauth_backend_build_authorize_url` — calls Nango with stubbed httpx,
  asserts returned URL has session_token.
- `test_nango_oauth_backend_handle_callback` — Nango redirect query params
  → Connection with `state["nango_connection_id"]`.
- `test_nango_webhook_view_sync` — POST stubbed sync notification, assert
  records fetched + bronze written + DP created.
- `test_nango_webhook_view_invalid_signature` — wrong signature → 401.

---

## Phase 1.5 — Admin sync to platform (~0.5d)

**Goal:** the Donna admin UI is the only OAuth-app-config interface
sysadmins ever touch. Pasting `client_id` + `client_secret` into the
`ClientCredentials` admin form pushes the values to the active platform
(Nango, or any future replacement) via that platform backend's
`upsert_app_config()` method. Sysadmins never log into Nango.

### 1.5.1 Generic platform-config API on `OAuthBackend`

**Edit:** `core/integrations/backends/oauth_backend.py` — add two
optional methods on the Protocol:

```python
@runtime_checkable
class OAuthBackend(Protocol):
    # ... existing methods ...

    # ── Optional: admin-managed app-config sync ─────────────────────────────
    # Backends that need vendor OAuth-app creds (Donna, Nango, Composio) impl
    # these. Donna backend's impl is a no-op (creds already live on
    # ClientCredentials). Nango/Composio impls push to the platform.
    def upsert_app_config(self, credentials: "ClientCredentials") -> None: ...
    def delete_app_config(self, credentials: "ClientCredentials") -> None: ...
```

Default impls on `DonnaOAuthBackend`:

```python
@register_oauth_backend("donna")
class DonnaOAuthBackend:
    # ... existing methods ...

    def upsert_app_config(self, credentials):
        return  # Donna reads directly from ClientCredentials; nothing to push

    def delete_app_config(self, credentials):
        return
```

Impls on `NangoOAuthBackend`:

```python
@register_oauth_backend("nango")
class NangoOAuthBackend:
    # ... existing methods ...

    def upsert_app_config(self, credentials):
        """Push OAuth-app creds to Nango as an integration config."""
        if not (credentials.client_id and credentials.client_secret and credentials.is_enabled):
            return  # half-configured row; admin re-saves when complete

        # Find the connector that pairs with this ClientCredentials row.
        from donna.core.integrations import all_loaded
        connector_cls = next(
            (c for c in all_loaded()
             if c.oauth_provider_slug == credentials.slug
             and c.oauth_backend_name == "nango"),
            None,
        )
        if connector_cls is None:
            return

        pck = (
            connector_cls.backend_config.get("provider_config_key")
            or connector_cls.slug
        )
        catalog_key = (
            connector_cls.backend_config.get("catalog_key")
            or connector_cls.slug
        )
        scopes = connector_cls.backend_config.get("oauth_scopes", []) or []

        self.client.upsert_integration_config(
            provider_config_key=pck,
            provider=catalog_key,
            oauth_client_id=credentials.client_id,
            oauth_client_secret=credentials.client_secret,
            oauth_scopes=scopes,
        )

    def delete_app_config(self, credentials):
        from donna.core.integrations import all_loaded
        connector_cls = next(
            (c for c in all_loaded()
             if c.oauth_provider_slug == credentials.slug),
            None,
        )
        if connector_cls is None:
            return
        pck = (
            connector_cls.backend_config.get("provider_config_key")
            or connector_cls.slug
        )
        try:
            self.client.delete_integration_config(provider_config_key=pck)
        except Exception:
            pass
```

### 1.5.2 Extend `NangoClient` with config CRUD

**Edit:** `core/integrations/backends/_nango_client.py` — append:

```python
class NangoClient:
    # ... existing methods ...

    # ── Integration config CRUD (admin path) ────────────────────────────────
    def upsert_integration_config(
        self,
        *,
        provider_config_key: str,
        provider: str,
        oauth_client_id: str,
        oauth_client_secret: str,
        oauth_scopes: list[str] | None = None,
    ) -> dict:
        body = {
            "unique_key":         provider_config_key,
            "provider":           provider,
            "oauth_client_id":    oauth_client_id,
            "oauth_client_secret": oauth_client_secret,
            "oauth_scopes":       " ".join(oauth_scopes or []),
        }
        resp = httpx.post(
            f"{self.base_url}/config",
            headers=self._headers(),
            json=body,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def delete_integration_config(self, *, provider_config_key: str) -> None:
        resp = httpx.delete(
            f"{self.base_url}/config/{provider_config_key}",
            headers=self._headers(),
            timeout=self.timeout,
        )
        resp.raise_for_status()

    def list_integration_configs(self) -> list[dict]:
        resp = httpx.get(
            f"{self.base_url}/config",
            headers=self._headers(),
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json().get("configs", [])
```

### 1.5.3 `ClientCredentials.backend` field

**Edit:** `integrations/models.py` — extend `ClientCredentials`:

```python
class ClientCredentials(TimestampsMixin, UserAuditMixin):
    # ... existing fields ...

    class Backend(models.TextChoices):
        DONNA = "donna", "Donna native"
        NANGO = "nango", "Nango (platform-managed)"
        # New backends added here as platforms are added.

    backend = models.CharField(
        _("backend"),
        max_length=16,
        choices=Backend.choices,
        default=Backend.DONNA,
        help_text=_(
            "Where the OAuth app + tokens live. 'donna' = local. "
            "'nango' (or other platform) = on save, secrets pushed to "
            "the platform via the active OAuthBackend's upsert_app_config."
        ),
    )
```

**Migration 0006:** `0006_clientcredentials_backend.py`

```python
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("integrations", "0005_connection_optional_token_nango_state"),
    ]
    operations = [
        migrations.AddField(
            model_name="clientcredentials",
            name="backend",
            field=models.CharField(
                choices=[("donna", "Donna native"), ("nango", "Nango (platform-managed)")],
                default="donna",
                max_length=16,
                verbose_name="backend",
            ),
        ),
    ]
```

### 1.5.4 Post-save signal

**New file:** `integrations/signals.py`

```python
"""Push ClientCredentials changes to the active OAuth platform.

Wired in apps.IntegrationsConfig.ready(). Failures are logged + visible
in admin via messages framework — see admin.py override.
"""
from __future__ import annotations

import logging

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .models import ClientCredentials


logger = logging.getLogger(__name__)


@receiver(post_save, sender=ClientCredentials)
def _push_app_config(sender, instance: ClientCredentials, **kwargs):
    if instance.backend == ClientCredentials.Backend.DONNA:
        return  # Donna reads directly; no push
    _dispatch(instance, action="upsert")


@receiver(post_delete, sender=ClientCredentials)
def _delete_app_config(sender, instance: ClientCredentials, **kwargs):
    if instance.backend == ClientCredentials.Backend.DONNA:
        return
    _dispatch(instance, action="delete")


def _dispatch(credentials: ClientCredentials, *, action: str) -> None:
    """Generic dispatcher — resolves the right OAuthBackend by credentials.backend."""
    from donna.core.integrations.backends import OAUTH_BACKENDS

    backend_cls = OAUTH_BACKENDS.get(credentials.backend)
    if backend_cls is None:
        logger.warning(
            "platform_dispatch_unknown_backend",
            extra={"backend": credentials.backend, "slug": credentials.slug},
        )
        return
    backend = backend_cls()
    method_name = f"{action}_app_config"  # upsert_app_config / delete_app_config
    method = getattr(backend, method_name, None)
    if method is None:
        return  # backend doesn't impl admin sync — silent no-op
    try:
        method(credentials)
    except Exception:
        logger.exception(
            "platform_dispatch_failed",
            extra={
                "action": action,
                "backend": credentials.backend,
                "slug": credentials.slug,
            },
        )
```

**Edit:** `integrations/apps.py` — wire signals:

```python
class IntegrationsConfig(AppConfig):
    name = "donna.integrations"
    label = "integrations"

    def ready(self):
        from . import signals  # noqa: F401 — registers post_save / post_delete

        # ... existing connector discovery ...
```

### 1.5.5 Admin form — surface push errors

**Edit:** `integrations/admin.py`

```python
from django.contrib import admin, messages

from .models import ClientCredentials


@admin.register(ClientCredentials)
class ClientCredentialsAdmin(admin.ModelAdmin):
    list_display = ("slug", "display_name", "backend", "is_enabled", "workspace")
    list_filter = ("backend", "is_enabled")
    search_fields = ("slug", "display_name")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # Synchronously check whether the platform push happened (signal ran).
        # Detect failure via log — for the v1 UX, ping the platform after save
        # to confirm config exists. Optional polish.
        if obj.backend == ClientCredentials.Backend.NANGO:
            from donna.core.integrations.backends._nango_client import NangoClient
            try:
                configs = NangoClient().list_integration_configs()
                slugs = {c.get("unique_key") for c in configs}
                if obj.slug not in slugs:
                    messages.warning(
                        request,
                        f"Saved locally, but Nango doesn't show {obj.slug!r} yet. "
                        f"Check NANGO_BASE_URL reachability + worker logs.",
                    )
            except Exception as exc:
                messages.warning(
                    request,
                    f"Nango unreachable ({exc!s}); config not synced. "
                    f"Run `nango_sync_push` after Nango comes up.",
                )
```

### 1.5.6 Bootstrap + drift commands

**Edit:** `integrations/management/commands/integrations_bootstrap.py` —
seed `backend` field from connector class:

```python
class Command(BaseCommand):
    help = "Seed ClientCredentials rows from registered connectors."

    def handle(self, *args, **opts):
        from donna.core.integrations import all_loaded
        from donna.integrations.models import ClientCredentials

        for cls in all_loaded():
            row, created = ClientCredentials.objects.get_or_create(
                slug=cls.oauth_provider_slug,
                workspace=None,
                defaults={
                    "display_name": cls.display_name,
                    "backend":      cls.oauth_backend_name,  # NEW — match the connector
                    "is_enabled":   False,
                },
            )
            self.stdout.write(
                f"{'created' if created else 'exists'}: "
                f"{cls.oauth_provider_slug} backend={row.backend}"
            )
```

**New command:** `integrations/management/commands/platform_sync_push.py`

```python
"""Re-push ALL non-donna ClientCredentials to their backends.

Use after the platform comes up post-outage, or after bulk-importing
rows via fixtures.
"""
from django.core.management.base import BaseCommand

from donna.core.integrations.backends import OAUTH_BACKENDS
from donna.integrations.models import ClientCredentials


class Command(BaseCommand):
    help = "Push every non-donna ClientCredentials row to its OAuth backend."

    def handle(self, *args, **opts):
        rows = ClientCredentials.objects.exclude(
            backend=ClientCredentials.Backend.DONNA
        ).filter(is_enabled=True)
        for row in rows:
            backend_cls = OAUTH_BACKENDS.get(row.backend)
            if backend_cls is None:
                self.stdout.write(self.style.WARNING(
                    f"{row.slug}: unknown backend {row.backend!r}"
                ))
                continue
            try:
                backend_cls().upsert_app_config(row)
                self.stdout.write(self.style.SUCCESS(f"{row.slug}: pushed"))
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"{row.slug}: FAILED ({exc})"))
```

**New command:** `integrations/management/commands/platform_sync_check.py`

```python
"""Detect drift between Donna ClientCredentials and platform-side configs.

For each non-donna ClientCredentials row: hit platform's list endpoint,
compare. Report missing / stale entries. Does NOT auto-fix — operator
runs platform_sync_push to resolve.
"""
from django.core.management.base import BaseCommand

from donna.core.integrations.backends._nango_client import NangoClient
from donna.integrations.models import ClientCredentials


class Command(BaseCommand):
    help = "Compare Donna ClientCredentials against Nango integration configs."

    def handle(self, *args, **opts):
        # v1: Nango-only. Extend per-backend as platforms are added.
        nango_rows = ClientCredentials.objects.filter(
            backend=ClientCredentials.Backend.NANGO,
            is_enabled=True,
        )
        configs = {c.get("unique_key"): c for c in NangoClient().list_integration_configs()}

        for row in nango_rows:
            cfg = configs.get(row.slug)
            if cfg is None:
                self.stdout.write(self.style.WARNING(f"{row.slug}: MISSING on Nango"))
            elif cfg.get("oauth_client_id") != row.client_id:
                self.stdout.write(self.style.WARNING(
                    f"{row.slug}: client_id DRIFT (donna={row.client_id[:6]}..., nango={cfg['oauth_client_id'][:6]}...)"
                ))
            else:
                self.stdout.write(self.style.SUCCESS(f"{row.slug}: OK"))

        for unique_key in configs.keys() - {r.slug for r in nango_rows}:
            self.stdout.write(self.style.NOTICE(
                f"{unique_key}: ORPHAN on Nango (no enabled Donna row)"
            ))
```

### 1.5.7 Tests

```bash
docker exec donna-server bash -lc "cd /opt/donna && DATABASE_HOST=donna-database \
   uv run python -m django test \
     donna.integrations.tests.test_admin_sync \
     donna.integrations.tests.test_signals \
     -v 2"
```

Cases:
- save `backend=nango` row → mocked `NangoClient.upsert_integration_config` called
- save `backend=donna` row → mock NOT called
- delete `backend=nango` row → `delete_integration_config` called
- save with empty `client_id` → signal early-returns, mock NOT called
- `platform_sync_push` re-pushes all enabled non-donna rows
- `platform_sync_check` reports missing vs OK vs orphan correctly

### Admin workflow after Phase 1.5

```
Django admin → ClientCredentials → notion row
  backend: nango
  client_id: <paste Notion OAuth app id>
  client_secret: <paste Notion OAuth app secret>
  is_enabled: ☑
  [Save]
    ↓
  post_save signal fires
    ↓
  NangoOAuthBackend.upsert_app_config(row) →
  NangoClient.upsert_integration_config(...)
    ↓
  Nango ready to serve Notion Connect sessions
```

Sysadmin never touched Nango. End users never knew Nango exists.

---

## Phase 2 — Self-host stack (~1d)

**Goal:** Nango container as part of `docker-compose.yml`, sharing
Postgres + Redis with Donna.

### 2.1 Docker compose

**Edit:** `server/docker-compose.yml`

```yaml
services:
  postgres:
    # ... unchanged ...
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-donna}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-donna}
      POSTGRES_DB: ${POSTGRES_DB:-donna}
    # NEW — ensure nango DB exists.
    volumes:
      - ./scripts/postgres-init.sh:/docker-entrypoint-initdb.d/01-create-nango-db.sh:ro

  redis:
    # ... unchanged — Nango uses Redis DB index 2 (Donna uses 0, Channels uses 1)

  nango-server:
    image: nangohq/nango-server:latest
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_started
    environment:
      NANGO_DB_HOST:     postgres
      NANGO_DB_PORT:     5432
      NANGO_DB_USER:     ${POSTGRES_USER:-donna}
      NANGO_DB_PASSWORD: ${POSTGRES_PASSWORD:-donna}
      NANGO_DB_NAME:     nango
      NANGO_DB_SSL:      "false"
      NANGO_REDIS_URL:   redis://redis:6379/2
      NANGO_SERVER_URL:  ${NANGO_SERVER_URL:-http://nango-server:3003}
      NANGO_WEBSOCKETS_PATH: /
      # Nango calls Donna's webhook endpoint at this URL when a sync completes.
      # Use docker network DNS in dev; override per env in prod.
      NANGO_SERVER_WEBHOOK_URL: http://web:8000/api/v1/integrations/nango/webhook
      NANGO_SERVER_WEBHOOK_SECRET: ${NANGO_WEBHOOK_SECRET:?Set NANGO_WEBHOOK_SECRET in .env}
    ports:
      - "3003:3003"

  web:
    # ... existing ...
    environment:
      # ... existing ...
      NANGO_BASE_URL:        ${NANGO_BASE_URL:-http://nango-server:3003}
      NANGO_SECRET_KEY:      ${NANGO_SECRET_KEY:?Set NANGO_SECRET_KEY in .env}
      NANGO_WEBHOOK_SECRET:  ${NANGO_WEBHOOK_SECRET:?Set NANGO_WEBHOOK_SECRET in .env}
      NANGO_CONNECT_UI_URL:  ${NANGO_CONNECT_UI_URL:-http://localhost:3009}

  worker:
    # ... existing ...
    environment:
      # ... existing ...
      NANGO_BASE_URL:        ${NANGO_BASE_URL:-http://nango-server:3003}
      NANGO_SECRET_KEY:      ${NANGO_SECRET_KEY:?Set NANGO_SECRET_KEY in .env}
```

**New file:** `server/scripts/postgres-init.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
  CREATE DATABASE nango;
  GRANT ALL PRIVILEGES ON DATABASE nango TO $POSTGRES_USER;
EOSQL
```

### 2.2 .env additions

**Edit:** `server/.env.example`

```
# ─── Nango (managed integration platform) ────────────────────────
NANGO_BASE_URL=http://nango-server:3003
NANGO_SECRET_KEY=replace-with-nango-secret
NANGO_WEBHOOK_SECRET=replace-with-strong-random
NANGO_CONNECT_UI_URL=http://localhost:3009
```

### 2.3 Doctor command

**Edit:** `integrations/management/commands/integrations_doctor.py`
(new — pattern noted in [`server/plans/05-integration-architecture.md`](05-integration-architecture.md))

```python
"""Health-check all integration backends.

Donna backend: walks registered ClientCredentials, validates client_id +
client_secret present, hits authorize_url HEAD to confirm vendor reachable.

Nango backend: hits NANGO_BASE_URL/health.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Health-check all integration backends and registered connectors."

    def handle(self, *args, **opts):
        self._check_donna_backend()
        self._check_nango_backend()

    def _check_donna_backend(self):
        from donna.core.integrations import all_loaded
        from donna.integrations.models import ClientCredentials
        loaded = [c for c in all_loaded() if c.oauth_backend_name == "donna"]
        self.stdout.write(f"Donna backend: {len(loaded)} connectors registered")
        for cls in loaded:
            row = ClientCredentials.objects.filter(slug=cls.oauth_provider_slug).first()
            status = "OK" if (row and row.client_id) else "MISSING_CREDS"
            self.stdout.write(f"  {cls.slug}: {status}")

    def _check_nango_backend(self):
        import httpx
        from django.conf import settings
        if not settings.NANGO_BASE_URL:
            self.stdout.write("Nango backend: DISABLED (NANGO_BASE_URL empty)")
            return
        try:
            resp = httpx.get(f"{settings.NANGO_BASE_URL}/health", timeout=5)
            if resp.status_code == 200:
                self.stdout.write("Nango backend: OK")
            else:
                self.stdout.write(f"Nango backend: UNHEALTHY (status {resp.status_code})")
        except Exception as exc:
            self.stdout.write(f"Nango backend: UNREACHABLE ({exc})")

        # List Nango-backed connectors.
        from donna.core.integrations import all_loaded
        nango = [c for c in all_loaded() if c.oauth_backend_name == "nango"]
        self.stdout.write(f"Nango-backed connectors: {len(nango)}")
        for cls in nango:
            self.stdout.write(f"  {cls.slug}: nango_provider_config_key={cls.nango_provider_config_key}")
```

Verify:
```bash
docker compose exec web ./manage.py integrations_doctor
```

---

## Phase 3 — First Nango connector: Notion (~1.5d)

**Goal:** end-to-end proof — user connects Notion in Donna UI, Nango runs
the OAuth + sync, Donna receives webhook + writes bronze + cortex hop fires.

### 3.1 Nango-side config (manual, one-time)

In Nango dashboard (or via Nango Sync API):

1. Add Notion as integration with Nango's pre-built OAuth provider.
2. Create a sync def named `notion-pages`:
   - Model: `Page`
   - Endpoint(s): `/v1/search` filtered to pages
   - Frequency: `every 1 hour`
   - Auto-start: `true`
   - Track deletes: `true`
3. Note the `provider_config_key` (e.g., `"notion"`).

### 3.2 Donna connector

**New file:** `integrations/connectors/notion/__init__.py` (empty)

**New file:** `integrations/connectors/notion/provider.py`

```python
"""Notion connector — backed by Nango.

No client.py or tasks.py needed. Nango handles OAuth + sync; Donna's
NangoFetchBackend pulls records on each sync notification and feeds
them to NotionAdapter.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from donna.core.integrations import register
from donna.core.integrations.canonical import (
    CanonicalDoc,
    BaseAdapter,
)

if TYPE_CHECKING:
    from donna.workspaces.models import Workspace


@register
class NotionProvider:
    # ── Identity ────────────────────────────────────────────────────────────
    slug = "notion"
    display_name = "Notion"
    category = "knowledge"

    # ── Backend selection ───────────────────────────────────────────────────
    oauth_backend_name   = "nango"
    fetch_backend_name   = "nango_sync"
    webhook_backend_name = "nango_proxy"

    # ── Per-backend opaque config (Nango reads; framework ignores) ──────────
    backend_config = {
        "provider_config_key": "notion",
        "catalog_key":         "notion",  # Nango's pre-built provider name
        "sync_models":         ("Page",),
        "sync_frequency":      "every 1 hour",
        "oauth_scopes":        [],        # Notion app uses no scopes
    }

    # ── Cross-backend ───────────────────────────────────────────────────────
    token_scope = "workspace"
    oauth_provider_slug = "notion"   # ClientCredentials row admin will create
    supports_webhooks = True

    # Donna-backend Protocol fields kept empty — Nango backend ignores.
    default_authorize_url = ""
    default_token_url = ""
    default_scopes: list[str] = []

    config_schema: dict = {
        "type": "object",
        "properties": {
            "include_databases": {"type": "boolean", "default": True},
            "exclude_archived":  {"type": "boolean", "default": True},
        },
        "additionalProperties": False,
    }
    default_config = {"include_databases": True, "exclude_archived": True}

    # ── Adapter factory ─────────────────────────────────────────────────────
    def adapter_for(self, raw: dict) -> BaseAdapter:
        return NotionPageAdapter(raw)

    # ── Workspace resolution (generic state keys) ───────────────────────────
    def resolve_workspace(self, parsed: dict) -> "Workspace":
        from donna.integrations.models import Connection
        nango_id = parsed.get("connectionId") or parsed.get("connection_id")
        conn = Connection.objects.select_related("workspace").get(
            state__backend="nango",
            state__external_connection_id=nango_id,
        )
        return conn.workspace

    # Unused for Nango backend.
    def dispatch_webhook(self, *, parsed, workspace):
        return

    def on_connect(self, *, token, connection):
        return  # Nango auto-starts sync after connect.

    def on_disconnect(self, *, token, connection):
        return

    def validate_config(self, config, *, connection=None):
        from donna.core.integrations.provider import validate_against_schema
        return validate_against_schema(config, self.config_schema)

    def picker(self, resource, params, *, connection):
        raise NotImplementedError
```

**New file:** `integrations/connectors/notion/adapter.py`

```python
"""Notion → CanonicalDoc adapter."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from donna.core.integrations.adapter import BaseAdapter
from donna.core.integrations.canonical import CanonicalDoc


class NotionPageAdapter(BaseAdapter):
    """Maps Nango's Notion `Page` model to CanonicalDoc."""

    canonical_type = "doc"

    def __init__(self, raw: dict):
        self.raw = raw

    def to_canonical(self) -> CanonicalDoc:
        # Nango normalizes Notion's properties dict into a stable shape;
        # the exact field set depends on the sync's mapper. Below is the
        # default Notion sync output.
        page_id = str(self.raw.get("id"))
        title = self._extract_title()
        url = self.raw.get("url") or ""
        created_time = self.raw.get("created_time")
        last_edited_time = self.raw.get("last_edited_time")

        return CanonicalDoc(
            external_id=page_id,
            title=title,
            url=url,
            mime_type="text/markdown",
            occurred_at=_parse_iso(last_edited_time or created_time),
            metadata={
                "source":          "notion",
                "page_id":         page_id,
                "parent_database": self.raw.get("parent", {}).get("database_id"),
                "archived":        self.raw.get("archived", False),
                "created_by":      self.raw.get("created_by", {}).get("id"),
                "last_edited_by":  self.raw.get("last_edited_by", {}).get("id"),
            },
        )

    def to_markdown(self) -> str:
        # Nango Notion sync delivers blocks as a tree; flatten to markdown.
        # Phase 3.1 keeps this simple — block-walker comes later.
        blocks = self.raw.get("blocks", [])
        lines: list[str] = []
        for block in blocks:
            t = block.get("type")
            if t == "paragraph":
                txt = "".join(rt.get("plain_text", "") for rt in block.get("paragraph", {}).get("rich_text", []))
                lines.append(txt)
            elif t == "heading_1":
                txt = "".join(rt.get("plain_text", "") for rt in block.get("heading_1", {}).get("rich_text", []))
                lines.append(f"# {txt}")
            # ... etc for heading_2, heading_3, bulleted_list_item, code, ...
        return "\n\n".join(lines)

    def to_text(self) -> str:
        return self.to_markdown()

    def to_json(self) -> dict:
        return self.raw

    def metadata(self) -> dict:
        return self.to_canonical().metadata

    def _extract_title(self) -> str:
        props = self.raw.get("properties", {})
        for prop in props.values():
            if prop.get("type") == "title":
                return "".join(rt.get("plain_text", "") for rt in prop.get("title", []))
        return self.raw.get("name") or "(untitled)"


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
```

### 3.3 Tests

**New file:** `integrations/connectors/notion/tests/__init__.py`

**New file:** `integrations/connectors/notion/tests/test_notion_ingest.py`

```python
"""End-to-end: Nango sync webhook → bronze + DP + cortex hop dispatched."""
from unittest.mock import patch, MagicMock

from django.test import TestCase
from rest_framework.test import APIClient

from donna.integrations.models import Connection
# ... factories ...


class NotionNangoIngestTest(TestCase):
    def setUp(self):
        self.workspace = ...
        self.user = ...
        self.connection = Connection.objects.create(
            workspace=self.workspace,
            user=self.user,
            provider_slug="notion",
            token=None,
            state={
                "backend": "nango",
                "external_connection_id": "nango-uuid-1",
                "raw": {"provider_config_key": "notion"},
            },
        )

    @patch("donna.core.integrations.backends._nango_client.NangoClient.fetch_records")
    @patch("donna.cortex.tasks.cortex_hop_from_dp.delay")
    def test_sync_webhook_writes_bronze_and_dispatches(self, mock_cortex, mock_fetch):
        mock_fetch.return_value = {
            "records": [
                {
                    "id": "page-1",
                    "url": "https://notion.so/page-1",
                    "created_time": "2026-06-24T10:00:00Z",
                    "last_edited_time": "2026-06-24T11:00:00Z",
                    "properties": {
                        "Name": {
                            "type": "title",
                            "title": [{"plain_text": "Test page"}],
                        }
                    },
                    "blocks": [
                        {
                            "type": "paragraph",
                            "paragraph": {"rich_text": [{"plain_text": "hello"}]},
                        }
                    ],
                }
            ],
            "next_cursor": None,
        }

        client = APIClient()
        payload = {
            "type": "sync",
            "connectionId": "nango-uuid-1",
            "providerConfigKey": "notion",
            "syncName": "notion-pages",
            "model": "Page",
        }
        # ... compute valid HMAC over the body ...
        resp = client.post(
            "/api/v1/integrations/nango/webhook",
            data=payload,
            format="json",
            HTTP_X_NANGO_SIGNATURE=valid_sig,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["processed"], 1)

        from donna.integrations.models import DeliveryPackage
        dp = DeliveryPackage.objects.get(provider_item_id="page-1")
        self.assertEqual(dp.canonical_type, "doc")
        self.assertEqual(dp.title, "Test page")
        mock_cortex.assert_called_once_with(str(dp.id))
```

### 3.4 Manual smoke

1. `docker compose up` — wait for `nango-server` to be healthy.
2. Bruno: hit `GET /api/v1/integrations/notion/` → status `is_configured=True, is_connected=False`.
3. Bruno: hit `POST /api/v1/integrations/notion/connect/` → returns Nango Connect URL.
4. Open the URL in a browser → Nango Connect UI → OAuth Notion → redirect back.
5. Check Donna DB: `Connection(provider_slug="notion", state__nango_connection_id=...)` exists.
6. Wait ≤1h for first sync, OR trigger manually:
   ```bash
   docker compose exec web ./manage.py shell -c "
   from donna.core.integrations.backends import FETCH_BACKENDS
   from donna.integrations.models import Connection
   conn = Connection.objects.get(provider_slug='notion')
   FETCH_BACKENDS['nango_sync']().trigger_sync(conn, full=True)
   "
   ```
7. Tail logs: `docker compose logs -f worker | grep notion`
8. Confirm `DeliveryPackage(provider='notion', ...)` rows exist and cortex hop fired.

---

## Phase 4 — Tier 1 non-migration (~0.5d)

**Goal:** record the architectural decision so future contributors don't
ask "why isn't Drive using Nango."

### 4.1 Doc update

**Edit:** `server/plans/05-integration-architecture.md` — add new section:

```markdown
## Tier classification (updated 2026-06-24)

| Tier | Pattern | Examples | Backend |
|---|---|---|---|
| 1 | Deep custom — binary attachments, OCR sidecars, vendor-specific webhook semantics | Fathom, Gmail, Drive | Donna native |
| 2 | Agent-action — invoked from chat tools, no background sync | (future: gh issue create, jira ticket) | Donna native |
| 3 | Generic sync — JSON-record CRUD, vendor catalog match | Notion, Linear, Slack, HubSpot, Salesforce, Asana, Jira, Confluence, Calendar, Outlook | Nango |

### Why Tier 1 is NOT on Nango

Three concrete blockers:

1. **Binary attachment walks.** Gmail's `_ingest_attachments` walks the
   MIME tree and either uses inline base64 or pulls binaries via
   `client.get_attachment(message_id, attachment_id)`. Nango syncs deliver
   JSON records; binary fetch requires a second proxy call per attachment.
   Replicating the walk inside Donna while delegating fetch to Nango proxy
   = same code, slower path (extra hop), no benefit.

2. **OCR sidecar pattern.** Drive's `_ingest_one_file` writes the binary to
   bronze, runs `extract_to_sidecar(bin_key, suffix=".pdf")`, mirrors the
   sidecar text to metadata. Nango's sync engine has no concept of sidecar
   artifacts. Adding it = Donna-side post-processing identical to current
   code.

3. **Vendor-specific webhook semantics.** Fathom's per-Connection webhook
   registration with rotating `whsec_…` secrets fits the Donna webhook
   handler's per-Connection-state path. Nango can proxy vendor webhooks,
   but Fathom's webhook → Nango → Donna fan-in loses the per-Connection
   secret model.

### When to add a Tier 1 connector that DOES use Nango transport

Use Nango as transport-only when:
- Vendor has standard OAuth + plain JSON record sync (no binary attachments)
- BUT requires Donna-side processing beyond what NangoFetchBackend defaults
  do (e.g. enrichment with cortex data before bronze write)

Set `oauth_backend_name = "nango", fetch_backend_name = "donna_celery"`,
implement `dispatch_webhook` to read records via `NangoClient.fetch_records`,
process Donna-side. Half-and-half not used in v1.
```

---

## Phase 5 — Fleet expansion (~3-5d)

**Goal:** ship 5-10 Nango-backed connectors. Each takes ~0.5-1d once the
adapter pattern is settled.

### 5.1 Candidate list (priority order)

| Slug | Vendor model(s) | Adapter complexity | Why this priority |
|---|---|---|---|
| `linear` | Issue, Project | Low (clean schema) | Engineering workflow context |
| `slack` | Message, Channel | Medium (thread reconstruction) | Communication context |
| `hubspot` | Contact, Deal, Note | Medium (related-object joins) | Sales CRM |
| `jira` | Issue, Sprint | Medium (custom fields) | Engineering / PM |
| `calendar` | Event | Low | Meeting context |
| `outlook_mail` | Message | Medium (HTML body) | Email beyond Gmail |
| `salesforce` | Contact, Account, Opportunity | High (custom objects) | Enterprise CRM |
| `confluence` | Page, Space | Medium | Wiki context |
| `asana` | Task, Project | Low | PM context |
| `intercom` | Conversation | Medium | Customer support |

### 5.2 Per-connector workflow

1. **Nango side** (~15min): add integration, configure sync def, note `provider_config_key`.
2. **Donna side** (~3-6h): create `connectors/<slug>/provider.py` + `adapter.py`.
3. **Test** (~1-2h): sync webhook → bronze + DP assertion.
4. **Cortex schema check** (~30min): does the canonical type exist? If new
   canonical type (e.g. `salesforce_opportunity` doesn't fit `doc`/`email`/`event`),
   extend `cortex/schemas.py` first.

### 5.3 Adapter template

Every Nango adapter follows the same shape (mirror `NotionPageAdapter`):

```python
class <Vendor><Model>Adapter(BaseAdapter):
    canonical_type = "<doc|email|event|person|org|task>"

    def __init__(self, raw: dict):
        self.raw = raw

    def to_canonical(self) -> Canonical<Type>:
        return Canonical<Type>(
            external_id=str(self.raw["id"]),
            title=self.raw.get("<title_field>") or "",
            occurred_at=_parse_iso(self.raw.get("<timestamp>")),
            metadata={...},
        )

    def to_text(self) -> str: return ...
    def to_markdown(self) -> str: return ...
    def to_json(self) -> dict: return self.raw
    def metadata(self) -> dict: return self.to_canonical().metadata
```

---

## Phase 6 — Swap-out path (~0.5d)

**Goal:** any platform (Composio, Paragon, Merge, Pipedream, homegrown,
etc.) can replace Nango without touching connector code, cortex code,
adapters, models, or admin workflow. Document the seam clearly so a
future migration is mechanical.

### What stays vs what changes

| Layer | Swap impact |
|---|---|
| `IntegrationProvider` Protocol | Zero — `backend_config: dict` is opaque |
| Connector `provider.py` (per integration) | Field name swaps (`oauth_backend_name = "composio"`) + `backend_config` keys |
| Connector `adapter.py` | Zero — `BaseAdapter` reads normalized JSON |
| `BaseAdapter` / `CanonicalDoc` / `bronze` | Zero |
| `DeliveryPackage` model | Zero |
| `cortex_hop_from_dp` task | Zero |
| `Connection` model | Zero (state JSONField + generic `state["backend"]` + `state["external_connection_id"]` keys) |
| `ClientCredentials` model | One new value in `Backend` choices enum |
| Admin form (`ClientCredentialsAdmin`) | Zero (form fields stay) |
| Signal in `integrations/signals.py` | Zero (dispatches by `credentials.backend` name) |
| `RegistryService` | Zero (dispatches via `OAUTH_BACKENDS[cls.oauth_backend_name]`) |
| `ProviderWebhookView` / `NangoWebhookView` | One new webhook view if new platform's webhook payload shape differs |
| `core/integrations/backends/<platform>_*.py` | NEW — 3 backend impls (OAuth/Fetch/Webhook) |
| `core/integrations/backends/_<platform>_client.py` | NEW — REST wrapper for the platform |
| `settings.INTEGRATION_BACKENDS` | One added entry per category |
| `docker-compose.yml` | Replace `nango-server` service with the new platform's |
| Per-connector `backend_config` dict | Keys change per platform |

The boundary is **3 files per platform** (`<platform>_oauth.py`,
`<platform>_fetch.py`, `<platform>_webhook.py`) + an SDK wrapper. Every
existing connector keeps working by changing the 3 backend-name fields
+ the `backend_config` dict on its provider class.

### Concrete swap checklist (e.g., Nango → Composio)

1. **Implement 3 backend classes** under `core/integrations/backends/`:
   - `composio_oauth.py` — `ComposioOAuthBackend` (Protocol-compliant, decorated `@register_oauth_backend("composio")`)
   - `composio_fetch.py` — `ComposioFetchBackend`
   - `composio_webhook.py` — `ComposioWebhookBackend`
   - `_composio_client.py` — REST wrapper (mirrors `_nango_client.py`)
2. **Register in settings:**
   ```python
   INTEGRATION_BACKENDS["oauth"]["composio"] = "donna.core.integrations.backends.composio_oauth.ComposioOAuthBackend"
   INTEGRATION_BACKENDS["fetch"]["composio_actions"] = "donna.core.integrations.backends.composio_fetch.ComposioFetchBackend"
   INTEGRATION_BACKENDS["webhook"]["composio_webhook"] = "donna.core.integrations.backends.composio_webhook.ComposioWebhookBackend"
   ```
3. **Add `Composio` to `ClientCredentials.Backend` enum** + migration adding the choice.
4. **Add Composio webhook URL** if payload shape differs from Nango's `{type: "sync", connectionId, ...}`. If close enough, reuse `/nango/webhook` and rename (or add `/composio/webhook` mirror).
5. **Per-connector flip** (per integration migrating):
   ```python
   # connectors/notion/provider.py
   oauth_backend_name   = "composio"        # was "nango"
   fetch_backend_name   = "composio_actions"
   webhook_backend_name = "composio_webhook"
   backend_config = {                       # was Nango-shaped
       "app_name":   "notion",
       "action_ids": ["NOTION_FETCH_PAGES"],
       # ... Composio-shape keys ...
   }
   ```
   `adapter.py` unchanged.
6. **`ClientCredentials` rows admin edit**: flip the `backend` field from `nango` → `composio`. Signal pushes creds to Composio. Existing `Connection` rows tied to old platform are orphaned — script a one-time migration: existing users re-OAuth (rare event; document, don't auto-migrate).
7. **Replace compose service**: swap `nango-server` block for `composio-server` (or whatever the new platform ships).
8. **Run `platform_sync_push`** to push all enabled `backend=composio` ClientCredentials to the new platform.
9. **Decommission Nango**: stop the Nango container, drop the Nango logical DB after a grace period.

No edits required in:
- `cortex/*`
- `chat/*`
- `core/integrations/adapter.py`, `canonical.py`, `bronze.py`, `binary_extract.py`
- Per-connector `adapter.py` files (all of them)
- `integrations/models.py:DeliveryPackage`
- `integrations/api/v1/*` (other than potentially adding a 2nd webhook view)
- Beat schedules
- WS / Celery wiring

### Half-and-half migrations

A connector can move per-integration. Notion on Composio + Linear still
on Nango + Drive still on Donna native works because `oauth_backend_name`
is per-provider-class. No big-bang cutover needed.

### Hard constraints any platform must meet to fit this seam

1. **OAuth Connect-UI-style redirect flow** — platform must accept a
   short-lived session token, present its own consent UI, callback to
   Donna with a stable `external_connection_id`. Platforms that hand
   tokens directly to Donna also work (subset case).
2. **Records pull API** (or webhook push with payloads ≤ proxy size) —
   Donna's `handle_sync_webhook` must be able to retrieve normalized
   records given a `connection_id` + `model`.
3. **HMAC-signed webhooks** with a deployment-wide secret — required
   for `WebhookBackend.verify`.
4. **Programmatic OAuth-app config CRUD** — required for Phase 1.5
   admin sync. Platforms without this (some agent-tool platforms expose
   only per-user OAuth, no admin-managed app config) need the admin to
   set up creds directly in the platform UI; signal becomes no-op.

If a candidate platform fails (1) or (3), it's NOT a drop-in. Skip.
If it fails (4), Phase 1.5 sync is disabled for that backend; admin
workflow gets a second UI step.

### Reference impls roadmap

If/when these are needed, drop new backend classes under
`core/integrations/backends/<platform>_*.py`:

| Platform | When to consider | Compatibility notes |
|---|---|---|
| [Composio](https://composio.dev) | Agent-tool framework, function-call style. Better for Tier 2 (agent actions) than Tier 3 (sync). | OAuth + actions; no native sync engine — fetch is on-demand. Adapter still applies. |
| [Paragon](https://useparagon.com) | If embedded SaaS connector UX > self-host control. | Closed-source; hosted-only. Lock-in higher. |
| [Merge](https://merge.dev) | If unified canonical models per vertical (HRIS, ATS, CRM) > vendor breadth. | Pre-normalizes records — adapter shrinks to identity map. |
| [Pipedream](https://pipedream.com) | If event-driven workflow > batch sync. | Event-driven; needs `handle_sync_webhook` rewritten as event handler. |
| Homegrown | If platform pricing exceeds eng cost OR data residency forbids 3rd-party. | Full ownership; pay for every catalog vendor in dev time. |

---

## Critical files (summary)

### New

| File | Phase | Purpose |
|---|---|---|
| `core/integrations/backends/__init__.py` | 0 | Backend export surface |
| `core/integrations/backends/registry.py` | 0 | Name → backend class lookup |
| `core/integrations/backends/oauth_backend.py` | 0 | `OAuthBackend` Protocol + `DonnaOAuthBackend` |
| `core/integrations/backends/fetch_backend.py` | 0 | `FetchBackend` Protocol + `DonnaCeleryFetchBackend` |
| `core/integrations/backends/webhook_backend.py` | 0 | `WebhookBackend` Protocol + `DonnaHmacWebhookBackend` |
| `core/integrations/backends/_nango_client.py` | 1 | Nango REST API wrapper |
| `core/integrations/backends/nango_oauth.py` | 1 | `NangoOAuthBackend` |
| `core/integrations/backends/nango_fetch.py` | 1 | `NangoFetchBackend` + sync record ingester |
| `core/integrations/backends/nango_webhook.py` | 1 | `NangoWebhookBackend` HMAC verifier |
| `integrations/api/v1/nango_webhook.py` | 1 | Single Nango webhook receiver view |
| `integrations/signals.py` | 1.5 | post_save / post_delete dispatch to active OAuth backend |
| `integrations/management/commands/platform_sync_push.py` | 1.5 | Re-push all non-donna ClientCredentials to backend |
| `integrations/management/commands/platform_sync_check.py` | 1.5 | Drift detector (Donna rows vs platform-side configs) |
| `integrations/management/commands/integrations_doctor.py` | 2 | Health check (Donna + Nango backends) |
| `scripts/postgres-init.sh` | 2 | Create `nango` logical DB at compose startup |
| `integrations/connectors/notion/provider.py` | 3 | First Nango connector |
| `integrations/connectors/notion/adapter.py` | 3 | Notion → CanonicalDoc |
| `integrations/connectors/notion/tests/test_notion_ingest.py` | 3 | End-to-end test |
| `integrations/connectors/<linear,slack,...>/{provider,adapter}.py` | 5 | Fleet expansion |

### Edited

| File | Phase | Change |
|---|---|---|
| `core/integrations/provider.py` | 0 | Add `oauth_backend_name`, `fetch_backend_name`, `webhook_backend_name`, `backend_config` ClassVars |
| `core/integrations/backends/registry.py` | 0 | Settings-driven `import_string` resolver (3rd-party platforms via `pip install` + settings entry) |
| `settings.py` | 0 | `INTEGRATION_BACKENDS` dict |
| `integrations/services.py` | 0 | `RegistryService.{initiate_connect,disconnect,handle_callback}` dispatch via `OAUTH_BACKENDS` |
| `integrations/api/v1/oauth.py` | 0 | Return type shifted from `OAuthToken` to `Connection`; pass `request_query` |
| `integrations/api/v1/webhooks.py` | 0 | Dispatch via `WEBHOOK_BACKENDS` |
| `integrations/models.py` | 1 / 1.5 | `Connection.token` nullable + `CheckConstraint` + GIN index on `state` (P1); `ClientCredentials.backend` field (P1.5) |
| `integrations/urls.py` | 1 | Register Nango webhook endpoint |
| `integrations/apps.py` | 1.5 | Wire `signals.py` in `ready()` |
| `integrations/admin.py` | 1.5 | `ClientCredentialsAdmin` shows backend + flashes warning on platform push failure |
| `integrations/management/commands/integrations_bootstrap.py` | 1.5 | Seed `backend` field from connector's `oauth_backend_name` |
| `core/integrations/backends/oauth_backend.py` | 1.5 | Add `upsert_app_config` / `delete_app_config` Protocol methods + no-op default on `DonnaOAuthBackend` |
| `core/integrations/backends/nango_oauth.py` | 1.5 | Add `upsert_app_config` / `delete_app_config` impls |
| `core/integrations/backends/_nango_client.py` | 1.5 | Add `upsert_integration_config` / `delete_integration_config` / `list_integration_configs` |
| `settings.py` | 1 / 2 | `NANGO_*` env vars + add `/api/v1/integrations/nango/` to `IGNORED_PATHS` |
| `docker-compose.yml` | 2 | Add `nango-server` service, share Postgres + Redis |
| `.env.example` | 2 | `NANGO_*` placeholders |
| `connectors/fathom/provider.py` | 0 | Add explicit `*_backend_name = "donna_*"` + `backend_config = {}` (no behaviour change) |
| `connectors/google/mail/provider.py` | 0 | Same |
| `connectors/google/drive/provider.py` | 0 | Same |
| `server/plans/05-integration-architecture.md` | 4 | Tier table + non-migration rationale |

### Reused (no edit)

- `core/integrations/adapter.py` — `BaseAdapter`, unchanged.
- `core/integrations/canonical.py` — `CanonicalDoc/Email/Event/...`, unchanged.
- `core/integrations/bronze.py` — bronze writer, unchanged.
- `core/integrations/binary_extract.py` — OCR sidecar (only used by Tier 1).
- `integrations/models.py:DeliveryPackage` — unchanged.
- `cortex/tasks.py:cortex_hop_from_dp` — unchanged.

---

## Migration

Two migrations land — one per phase that changes the schema.

**Migration 0005** (Phase 1): `Connection.token` nullable + constraint + index.

```python
# integrations/migrations/0005_connection_optional_token_nango_state.py
from django.contrib.postgres.indexes import GinIndex
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("integrations", "0004_deliverypackage_canonical"),
    ]

    operations = [
        migrations.AlterField(
            model_name="connection",
            name="token",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="connections",
                related_query_name="connection",
                to="integrations.oauthtoken",
            ),
        ),
        migrations.AddConstraint(
            model_name="connection",
            constraint=models.CheckConstraint(
                check=(
                    models.Q(token__isnull=False) |
                    (models.Q(token__isnull=True) & ~models.Q(state={}))
                ),
                name="connection_has_token_or_nango_id",
            ),
        ),
        migrations.AddIndex(
            model_name="connection",
            index=GinIndex(fields=["state"], name="conn_state_gin_idx"),
        ),
    ]
```

No data migration needed — existing Donna-backend connections have
non-null `token`, satisfy the constraint.

**Migration 0006** (Phase 1.5): `ClientCredentials.backend` field.

```python
# integrations/migrations/0006_clientcredentials_backend.py
from django.db import migrations, models


def _backfill_backend(apps, schema_editor):
    """Existing rows default to 'donna' — matches current behaviour."""
    Cred = apps.get_model("integrations", "ClientCredentials")
    Cred.objects.update(backend="donna")


class Migration(migrations.Migration):
    dependencies = [
        ("integrations", "0005_connection_optional_token_nango_state"),
    ]
    operations = [
        migrations.AddField(
            model_name="clientcredentials",
            name="backend",
            field=models.CharField(
                choices=[
                    ("donna", "Donna native"),
                    ("nango", "Nango (platform-managed)"),
                ],
                default="donna",
                max_length=16,
                verbose_name="backend",
            ),
        ),
        migrations.RunPython(_backfill_backend, migrations.RunPython.noop),
    ]
```

---

## Verification

### Per-phase

```bash
# Phase 0 — backend extraction, no behaviour change
docker exec donna-server bash -lc \
  "cd /opt/donna && DATABASE_HOST=donna-database \
   uv run python -m django test \
     donna.core.integrations \
     donna.integrations \
     -v 2"

# Phase 1 — Nango backend present
docker exec donna-server bash -lc \
  "cd /opt/donna && DATABASE_HOST=donna-database \
   uv run python -m django test \
     donna.core.integrations.backends.tests \
     donna.integrations.tests.test_nango_webhook \
     -v 2"

# Phase 1.5 — admin sync wired
docker exec donna-server bash -lc \
  "cd /opt/donna && DATABASE_HOST=donna-database \
   uv run python -m django test \
     donna.integrations.tests.test_signals \
     donna.integrations.tests.test_admin_sync \
     -v 2"
docker exec donna-server ./manage.py platform_sync_check

# Phase 2 — stack
docker compose up -d
docker compose exec web ./manage.py integrations_doctor
# expect: "Nango backend: OK"

# Phase 3 — Notion end-to-end
docker exec donna-server bash -lc \
  "cd /opt/donna && DATABASE_HOST=donna-database \
   uv run python -m django test \
     donna.integrations.connectors.notion.tests \
     -v 2"
```

### Cleanup discipline

After every test run (user hard rule):
```bash
bash server/scripts/cleanup_test_residue.sh
```

### End-to-end smoke (after Phase 3)

1. `docker compose up`
2. Bruno: `POST /api/v1/integrations/notion/connect/` → returns Connect URL
3. Browser: complete Nango Connect flow
4. Bruno: `GET /api/v1/integrations/notion/` → `is_connected=True`
5. Worker logs: `nango_sync_webhook` events appearing
6. Bruno: list `/api/v1/cortex/entities?type=doc&source=notion` → see Notion pages

---

## Risks

| Risk | Mitigation |
|---|---|
| Nango self-host instability when running 10+ syncs | Start with Cloud for first 90 days; observe load; self-host only after pattern is stable |
| Nango holds tokens — vendor offline = both sides notice | Add `NangoOAuthBackend.health_check()` + degrade banner; existing Donna-backend connectors unaffected |
| Nango sync delivery ordering — partial batch failure | Bronze writes idempotent (content-addressed); re-delivery = no-op |
| Connection lifecycle two-phase delete (Donna + Nango) | Donna delete kicks Nango DELETE in `revoke()`; if Nango fails, orphan token at Nango is cosmetic (cleanup script can reconcile) |
| Compose stack gets heavy (8 containers) | Document in [`CLAUDE.md`](../../CLAUDE.md) + provide `docker compose --profile minimal up` excluding Nango for cases where it's not needed |
| Vendor lock-in to Nango — switching cost grows with each connector | Adapter layer stays Donna-owned; switching = re-implement OAuth + sync per connector, but cortex/bronze never changes |
| Cost at scale (Nango Cloud is per-sync-run) | Self-host crossover analysis at month 3 |

---

## Open questions

1. **OAuth backend selection: per-connector class vs per-deployment env?**
   Currently per-connector ClassVar. Could also be env-overridable
   (`DONNA_OAUTH_BACKEND_NOTION=donna` to force Donna OAuth even if the
   connector defaults to Nango). Useful for testing without Nango? Or
   premature flexibility?

2. **Nango sync trigger on Connection PATCH.** When user changes
   `Connection.config.include_databases`, should we auto-trigger a
   full-resync? Currently no. Adding it = `Connection.save()` post-hook
   that compares old/new config + calls `NangoFetchBackend.trigger_sync(full=True)`.

3. **Workspace-scoped Nango accounts?** Self-host = one Nango install per
   Donna deployment (one tenant's Nango secret). Multi-tenant SaaS Donna
   might want per-workspace Nango accounts for billing isolation. Defer
   to post-v1 — single Nango per deployment for now.

4. **Nango sync def authoring — manual UI vs version-controlled YAML.**
   Nango supports both. Self-host can mount a `nango.yaml` for declarative
   sync defs. Cloud requires UI / API. Recommend YAML for self-host so
   sync defs are reviewed alongside connector code.

5. **Should `provider.adapter_for(raw)` accept the model name?**
   Currently `adapter_for(raw: dict) -> BaseAdapter`. Nango sync may
   deliver multiple models (`Page`, `Database`). Could change to
   `adapter_for(raw, *, model="Page")`. Decide once `linear` (multi-model)
   lands.

6. **Health-check / degrade banner.** When Nango is down, all Nango-backed
   connectors silently stop syncing. Should there be a daily Celery beat
   that pings Nango and surfaces an admin notification? Recommend yes —
   add `chat-nango-health` beat that checks `NANGO_BASE_URL/health` every
   5min and creates a notification on transitions.

---
