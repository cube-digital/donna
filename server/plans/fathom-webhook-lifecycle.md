# Fathom webhook lifecycle — auto-register on connect, delete on disconnect

## Why

Fathom OAuth callback today only stores tokens. The webhook URL must be pasted manually into Fathom's dashboard, so:

- A fresh OAuth connection produces no meeting deliveries until the user does extra setup.
- Disconnects leave orphan webhooks pointing at Donna.
- There is no per-Connection HMAC secret — verification falls back to the shared `ClientCredentials.webhook_secret`, which Fathom does not issue (Fathom returns a unique `secret` per webhook).

Fathom's external API supports programmatic management via the same Bearer token the OAuth flow already produces:

- `POST  https://api.fathom.ai/external/v1/webhooks` → `{id, secret, url, ...}`
- `DELETE https://api.fathom.ai/external/v1/webhooks/{id}` → 204

OpenAPI spec lists both `ApiKeyAuth` and `BearerAuth`; existing `FathomClient` already sends `Authorization: Bearer <oauth_token>`.

## Design

### 1. Protocol seam (framework, all connectors benefit)

`donna/core/integrations/provider.py` — add to `IntegrationProvider` Protocol:

```python
def on_connect(self, *, token: "OAuthToken", connection: "Connection") -> None: ...
def on_disconnect(self, *, token: "OAuthToken", connection: "Connection") -> None: ...
```

Default no-op implementations live on the base class. Gmail / Drive inherit no-op → zero behaviour change.

### 2. RegistryService wiring

`donna/integrations/services.py`:

- `handle_callback`: after `Connection.objects.get_or_create(...)`, call `provider.on_connect(token=token, connection=connection)`. On failure → log, delete the just-created Connection + token, propagate user-facing error. Half-configured state is worse than failed connect.
- `disconnect`: order becomes **`on_disconnect` → revoke → delete rows**. Catch + log `on_disconnect` exceptions so vendor-side 404 / network blips do not block local cleanup. Vendor token must still be valid when `on_disconnect` runs (revoke comes after).

### 3. Fathom client methods

`connectors/fathom/client.py`:

```python
def create_webhook(self, *, destination_url, triggered_for,
                   include_transcript=True, include_summary=True,
                   include_action_items=True, include_crm_matches=False) -> dict: ...
def delete_webhook(self, webhook_id: str) -> None: ...
```

Open: current `base_url` is `https://api.fathom.video/external/v1`; docs use `https://api.fathom.ai/external/v1`. Verify which is live before shipping.

### 4. Fathom provider hooks

`connectors/fathom/provider.py`:

- `on_connect`:
  1. Build absolute callback URL via `settings.DONNA_PUBLIC_BASE_URL + reverse('fathom-webhook-callback')`.
  2. `resp = self.client(token).create_webhook(destination_url=..., triggered_for=[...])`.
  3. Merge `{"webhook": {"id": resp["id"], "secret": resp["secret"]}}` into `connection.state` and save.
- `on_disconnect`:
  1. Read `connection.state["webhook"]["id"]`.
  2. `client.delete_webhook(id)`; tolerate 404.

### 5. Per-Connection HMAC secret in verification

Fathom returns a unique `secret` per webhook → cannot use `ClientCredentials.webhook_secret`. Webhook view (`api/v1/webhooks.py`) becomes:

1. `parsed_preview = handler.parse(payload)` — read-only.
2. `workspace = provider.resolve_workspace(parsed_preview)`.
3. Look up `Connection` for that workspace + slug; read `state["webhook"]["secret"]`.
4. `handler.verify(payload, signature, secret=secret)`.
5. `provider.dispatch_webhook(parsed=parsed_preview, workspace=workspace)`.

Parse-before-verify is normally a red flag; mitigated because (a) parse is pure, (b) dispatch happens only after verify, (c) Fathom's resolution key is in the body. Alternative: a `FathomWebhookHandler.verify` that internally parses + looks up Connection — cleaner API but couples handler to ORM. Pick view-layer approach.

### 6. Connection state shape

```json
{
  "webhook": {"id": "...", "secret": "whsec_..."},
  "streams": {...},
  "global": {...}
}
```

Documented under `plans/08-connection-pattern.md` "State conventions". v1 leaves the secret in plain JSON; follow-up may migrate sensitive fields to an `EncryptedTextField` column.

### 7. Settings

`donna/settings.py`:

```python
DONNA_PUBLIC_BASE_URL = env.str("DONNA_PUBLIC_BASE_URL", default=WEB_REDIRECT_HOST)
```

`WEB_REDIRECT_HOST` targets the frontend; backend webhook URL is separate. Dev: must point at a tunnel (ngrok / cloudflared) — Fathom cannot reach `localhost`.

## Tests (to be written with implementation)

- `on_connect` POSTs and persists `state["webhook"]`.
- `on_disconnect` DELETEs; 404 swallowed.
- Webhook view verifies with per-Connection secret; mismatched signature → 401.
- Connect → disconnect → reconnect produces a fresh `webhook.id`; no orphans.

## Out of scope

- Reconciliation task for orphaned webhooks when `on_disconnect` crashes mid-flight.
- Multi-Connection / multi-user under one Fathom OAuth account (existing `resolve_workspace` TODO).
- Programmatic subscriptions for Gmail / Drive (separate plan).

## Open questions (resolve before implementation)

1. Live base URL: `api.fathom.ai` vs `api.fathom.video`?
2. Default `triggered_for`: ship with `my_recordings + my_shared_with_team_recordings`, or all three, or user-configurable via `Connection.config`?
3. Encrypt `state["webhook"]["secret"]` in v1, or defer to follow-up?
4. Dev story: assume tunnel + `DONNA_PUBLIC_BASE_URL`, or only validate in deployed env?
