# Connection Pattern — One Model for All Per-Tenant Integration Config

> Status: **Locked design contract**. Two connectors in scope: Gmail
> (08a) and Google Drive (08b). Same abstraction extends to future
> connectors without schema work.

## Context

Donna ships multi-tenant connectors (Fathom + Gmail in code, Drive next,
WhatsApp deferred). Each one needs per-tenant **configuration** the user
can revisit:

- Gmail — "ingest only label X" / "last 30d" / "everything"
- Drive — "watch /Engineering recursively" / "only these 4 files"
- Fathom — "everything" (push-based, no filter v1)

Initial design splattered config across multiple typed tables
(`GmailFilter`, `DriveSubscription`, `WhatsAppChatSubscription`,
`IngestConfig`). Collapsed to **one row per (workspace, user, provider)**
with JSON config + JSON state after design review.

## Decisions (locked)

| Choice | Decision | Why |
|---|---|---|
| Model name | **`Connection`** | Airbyte / Nango / Hookdeck / Workato standard. Devs joining recognize it. |
| Cardinality | **One row per `(workspace, user, provider_slug)`** | One binding = one user-editable config object. UNIQUE constraint enforces. |
| User-editable settings | **JSON `config` field** | Connector shape diverges enough that typed columns would explode the schema. JSON Schema validates per-connector. |
| Sync-task-managed state | **Separate JSON `state` field** | Different lifecycle (writer is the task, not the user). Different write contention model. Airbyte's biggest migration lesson — never co-mingle. |
| State sub-shape | **`{"streams": {<id>: {...}}, "global": {...}}`** | Per-resource keying from day one. Airbyte's `LEGACY` → per-stream migration was painful — avoid by shaping correctly upfront. |
| Hot fields | **Real columns** for `last_synced_at`, `last_error_at`, `last_error_msg` | Queryable, indexable, sortable — keep out of JSON. Nango pattern. |
| Config validation | **JSON Schema** declared on Provider class (`config_schema`) | Validated server-side via `jsonschema` lib. Buys free admin form generation later. Airbyte's `connectionSpecification` prior art. |
| Token relationship | **`Connection.token` = FK to `OAuthToken`, N:1, ON DELETE CASCADE** | One OAuthToken per vendor backs multiple Connections (Gmail + Drive share Google OAuth). Token revoke deletes all dependent Connections. |
| Workspace vs user scope | **`workspace` always set, `user` null iff workspace-scoped connector** | `Provider.token_scope` ("workspace" or "user") drives whether `user` is populated. |
| Pair flow | **Auto-create Connection on OAuth pair + on first connector use of a shared token** | User opens config UI and finds existing binding with `default_config`. |
| Endpoints | **Singular `/api/v1/integrations/:slug/subscription/`** (GET, PATCH, DELETE) + nested `/picker/:resource` action | One binding per (workspace, user, provider) → singular resource. Picker nests under binding because it serves the binding's editor. |

## Data model

```python
class Connection(TimestampsMixin):
    """
    Per (workspace, [user], provider) ingest binding. One row holds all
    user-editable config + sync-task-managed state for one connected
    integration. JSON-based, validated per-connector via Provider.config_schema.
    """
    id              = UUIDField, primary_key
    workspace       = FK Workspace,  on_delete=CASCADE
    user            = FK User,       on_delete=CASCADE, null=True       # set iff user-scoped
    provider_slug   = CharField(50)                                      # "gmail", "drive", "fathom"
    token           = FK OAuthToken, on_delete=CASCADE                   # shared across same-vendor connectors

    # User-editable, validated against Provider.config_schema (JSON Schema)
    config          = JSONField, default=dict

    # Sync-task-managed. Shape: {"streams": {<id>: {...}}, "global": {...}}
    state           = JSONField, default=dict

    enabled         = BooleanField, default=True

    # Hot-queryable fields (lifted from state per Nango pattern)
    last_synced_at  = DateTimeField, null=True, db_index=True
    last_error_at   = DateTimeField, null=True
    last_error_msg  = TextField,     blank=True

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["workspace", "user", "provider_slug"],
                name="uq_connection_ws_user_provider",
            ),
        ]
        indexes = [
            Index(fields=["workspace", "provider_slug", "enabled"]),
            Index(fields=["token"]),
        ]
```

## How config / state shape looks per connector

```jsonc
// Gmail — config
{
  "mode": "subscriptions",                    // "everything" | "time_window" | "subscriptions"
  "time_window_days": 30,                     // used iff mode=time_window
  "labels":  ["Label_42", "Label_17"],
  "queries": ["from:boss@acme.com"],
  "domains": ["acme.com", "*.acme.com"]
}

// Gmail — state (per-stream keyed)
{
  "streams": {
    "Label_42":  {"history_id": "...", "last_synced_at": "..."},
    "Label_17":  {"history_id": "...", "last_synced_at": "..."},
    "_global":   {"history_id": "...", "last_synced_at": "..."}     // used by mode=everything/time_window
  },
  "global": {"cold_start_done": true}
}

// Drive — config
{
  "mode": "subscriptions",                    // "everything" | "subscriptions"
  "files":   ["1AbC...", "1DeF..."],
  "folders": [
    {"id": "1XyZ...", "name": "Engineering", "recursive": true},
    {"id": "1QrS...", "name": "Sales",       "recursive": false}
  ]
}

// Drive — state
{
  "streams": {
    "1XyZ...":   {"folder_change_token": "...", "last_synced_at": "..."},
    "1AbC...":   {"file_last_modified": "...", "last_synced_at": "..."}
  },
  "global": {"drive_change_token": "..."}
}

// Fathom — config (workspace-scoped, push-based)
{ "mode": "everything" }

// Fathom — state
{ "global": {"last_event_at": "..."} }
```

## Token / Connection relationship

```
┌─────────────┐  1 : N  ┌───────────────────────────────────────┐
│ OAuthToken  │◄────────│ Connection                            │
│ (vendor)    │         │ provider_slug ∈ vendor's connectors   │
│             │         │ config / state per connector          │
└─────────────┘         └───────────────────────────────────────┘

Example — Alice in Workspace W pairs Google once:
  OAuthToken(workspace=W, user=Alice, provider=google) ← single row
       ▲                ▲
       │                │
       │           ┌────┴──────────────────┐
       │           │ Connection            │
       │           │   provider_slug=drive │
       │           │   config={folders:[…]}│
       │           └───────────────────────┘
       │
  ┌────┴───────────────────┐
  │ Connection             │
  │   provider_slug=gmail  │
  │   config={mode:…}      │
  └────────────────────────┘

Revoke Google → CASCADE deletes both Connections.
Delete just the Gmail Connection → Token survives, Drive Connection
unaffected, can re-create Gmail Connection from token later.
```

## Provider class — new hooks

```python
class GmailProvider:
    slug                  = "gmail"
    display_name          = "Gmail"
    category              = "email"
    oauth_provider_slug   = "google"
    token_scope           = "user"
    supports_webhooks     = False

    # NEW — JSON Schema validating config blob
    config_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type":    "object",
        "properties": {
            "mode": {"enum": ["everything", "time_window", "subscriptions"]},
            "time_window_days": {"type": "integer", "minimum": 1, "maximum": 3650},
            "labels":  {"type": "array", "items": {"type": "string"}},
            "queries": {"type": "array", "items": {"type": "string"}},
            "domains": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["mode"],
        "additionalProperties": False,
    }

    # NEW — default config used when Connection is auto-created
    default_config = {"mode": "time_window", "time_window_days": 30}

    def validate_config(self, config: dict) -> dict:
        """Default impl validates against self.config_schema. Override for cross-field rules."""
        ...

    def picker(self, resource: str, params: dict, *, connection: "Connection") -> dict:
        """Serve picker data. e.g. resource="labels" → return Gmail labels list."""
        ...
```

`BaseAdapter`, `BaseHTTPClient`, `BaseOAuthHandler`, `BaseWebhookHandler`
unchanged. Only `Provider` gains 3 new attributes (`config_schema`,
`default_config`) and 2 new methods (`validate_config`, `picker`).

## API

```
GET    /api/v1/integrations/:slug/subscription/                       # fetch binding
PATCH  /api/v1/integrations/:slug/subscription/                       # update config (validated)
DELETE /api/v1/integrations/:slug/subscription/                       # delete binding (token survives)

GET    /api/v1/integrations/:slug/subscription/picker/:resource       # nested action
```

Each call resolves `Connection.objects.get(workspace=request.workspace,
user=request.user_or_none, provider_slug=slug)`.

`PATCH` body: `{config: {...}}`. Server runs
`provider.validate_config(payload["config"])` then saves.

`Connection` auto-created on OAuth callback when `OAuthToken` lands —
framework knows the provider, runs `provider.default_config`, persists.

## Sync task pattern (uniform across connectors)

```python
@shared_task
def sync_<connector>(connection_id: str) -> dict:
    conn = Connection.objects.select_for_update().get(id=connection_id)
    if not conn.enabled:
        return {"skipped": "disabled"}

    provider = get_provider(conn.provider_slug)
    cfg, state = conn.config, conn.state

    try:
        # Connector-specific dispatch from cfg.mode + cfg.fields
        result = provider.run_sync(conn=conn, config=cfg, state=state)
        conn.state = result.new_state
        conn.last_synced_at = now()
        conn.last_error_at = None
        conn.last_error_msg = ""
    except Exception as exc:
        conn.last_error_at = now()
        conn.last_error_msg = str(exc)[:1000]
        raise
    finally:
        conn.save(update_fields=["state", "last_synced_at", "last_error_at", "last_error_msg"])
```

Beat fanout:

```python
@shared_task
def fanout_<connector>_sync():
    for conn_id in Connection.objects.filter(
        provider_slug="gmail", enabled=True
    ).values_list("id", flat=True):
        sync_gmail.delay(conn_id)
```

Per-message ingest tasks (e.g. `ingest_gmail_message`) unchanged — they
still write to `DeliveryPackage` + `default_storage`.

## Industry validation

Researched against five production OSS connector platforms:

| Tool | Per-tenant model | Config | State | Validation |
|---|---|---|---|---|
| **Airbyte** | 1 `Connection` row per (workspace, source) | JSON blob | `AirbyteStateMessage` JSON, **per-stream-keyed** | Connector's `connectionSpecification` JSON Schema |
| **Nango** | 1 `_nango_connections` row per (account, integration, user) | `connection_config` jsonb | Separate `_nango_sync_*` tables + `last_fetched_at` column | Per-provider config |
| **Singer/Meltano** | 1 catalog per tap+target | `CONFIG` JSON file | `STATE` JSON file, `{bookmarks: {stream: ...}}` | Per-tap spec |
| **n8n** | 1 `workflow` row | `nodes` JSON column | Separate `staticData` JSON column | Node-level Zod schemas |
| **Hookdeck** | 1 `Connection` row | `rules` JSON array | — | — |

**All five converge on Donna's chosen shape.** Single polymorphic row,
JSON config, JSON state separate from config, per-connector schema
validation. Donna inherits the convergence + their lessons-learned:

1. **State keyed per-resource from day one** — Airbyte's LEGACY→STREAM
   migration was the most painful. Donna avoids by shaping state
   `{"streams": {<id>: {...}}, "global": {...}}` upfront, even when v1
   has only one cursor.
2. **JSON Schema for config**, not ad-hoc Python validation —
   Airbyte's `connectionSpecification` enables auto-form-generation.
3. **Credentials stay separate** from config — Donna already separates
   `OAuthToken` from `Connection`. Match.
4. **Hot fields outside JSON** — Nango lifted `last_fetched_at` to a
   column. Donna lifts `last_synced_at`, `last_error_at`,
   `last_error_msg`.

## OAuth storage — alignment

| Industry | Donna |
|---|---|
| Per-vendor template (Airbyte connector spec, Nango `_nango_configs`, n8n credential type) | ✅ `OAuthProvider` (slug, client_id, client_secret, scopes, URLs) |
| Per-tenant token (Airbyte `source.config`, Nango `_nango_connections.credentials`, n8n `CredentialsEntity`) | ✅ `OAuthToken` (workspace, user, access_token, refresh_token, expires_at, scope) |
| At-rest encryption | ✅ `EncryptedTextField` |
| Server-side refresh | ✅ `GoogleOAuthHandler.refresh()` + `BaseGoogleClient` 401 retry |

No change needed to OAuth layer. `Connection.token` joins to existing
`OAuthToken`. Token N:1 with Connection — one Google OAuth backs Gmail
+ Drive Connections.

## Pair / disconnect flow

```
1. User clicks "Connect Google" (covers Gmail + Drive in one OAuth flow)
2. OAuth callback creates/updates OAuthToken(provider=google)
3. Framework reads list of registered connectors with oauth_provider_slug="google"
   For each: auto-create Connection row (or refresh existing) with provider.default_config
4. Frontend redirects to /integrations/gmail/configure (or /integrations/drive/configure)
5. User edits Connection.config via PATCH

Disconnect:
- DELETE /api/v1/integrations/gmail/subscription/  → Connection row only; token survives
- DELETE /api/v1/integrations/oauth/google/        → OAuthToken + CASCADE all Connections
```

## What changes in existing code

- **`donna/integrations/models.py`** — add `Connection` model. `DeliveryPackage` unchanged.
- **`donna/core/integrations/provider.py`** — extend Protocol with
  `config_schema`, `default_config`, `validate_config(config)`,
  `picker(resource, params, *, connection)`.
- **`donna/integrations/api/v1/views.py`** — add `ConnectionViewSet`
  (singular detail action, no list/create — auto-managed).
- **`donna/integrations/api/v1/oauth.py`** — `ProviderOAuthCallbackView`
  upserts Connection rows for every connector sharing the vendor.
- **`donna/integrations/connectors/google/mail/tasks.py`** — `sync_gmail_inbox`
  and `fanout_gmail_sync` re-keyed from `OAuthToken` to `Connection`.
- **`donna/integrations/connectors/google/mail/provider.py`** — add
  `config_schema`, `default_config`, `validate_config`, `picker`.
- **`pyproject.toml`** — add `jsonschema>=4.20` dep.

## Files to create

| File | Purpose |
|---|---|
| `server/plans/08a-gmail-integration.md` | Gmail-specific plan (filters, label picker, time window) |
| `server/plans/08b-google-drive-integration.md` | Drive-specific plan (hybrid Picker + browser, progressive scope) |
| `server/donna/integrations/api/v1/connections.py` | `ConnectionViewSet` — singular detail + picker action |

## Migration impact

One new model (`Connection`). Per session policy, model code lands
without running migrations until explicitly unblocked.

## Open gaps (deferred)

1. **Form-generation from `config_schema`** — Airbyte auto-generates the
   admin form from `connectionSpecification`. Donna v1 hand-codes
   forms; revisit when 3+ connectors share patterns.
2. **Per-connector state migration** — if `state` shape changes,
   need a migration helper. v1 keeps shape stable; bake migration tool
   when first shape change lands.
3. **Connection-level rate limit** — Airbyte/Nango both throttle per
   connection. Donna v1 relies on per-connector code; lift to framework
   when first noisy connector lands.
4. **`enabled=false` semantics** — does it pause sync only, or also
   reject new ingest from push connectors? v1: pause sync, accept push
   (push events queued, ingested when re-enabled). Revisit if memory
   pressure shows up.
5. **`select_for_update` in sync task** — currently used. If multiple
   connectors fanout overlap, lock contention possible. v1: accept;
   revisit at scale.

## Out of scope

- Auto-generated admin forms from JSON Schema (deferred)
- Per-connection rate limiting (deferred)
- Connection-level audit log (TimestampsMixin gives basic created/modified; full audit deferred)
- Cross-Connection dedup beyond `DeliveryPackage.UniqueConstraint`
- WhatsApp Connection (see `whats-app-integration.md` — deferred)
