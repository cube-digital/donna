# Plan — Integrate WhatsApp (personal accounts, Baileys sidecar)

## Context

Donna ships Fathom + Gmail connectors. Both fit Donna's existing
single-process Django + Celery framework cleanly because their flows are
either HTTPS-pull (Gmail polling) or HTTPS-push (Fathom webhooks).

WhatsApp does **not** fit that shape. We're targeting **personal WhatsApp
accounts** (so multiple employees from the same company can connect their
own phones and surface chosen chats into Donna). The only realistic path
for personal accounts is the WhatsApp Web multidevice protocol via
`@WhiskeySockets/Baileys` (Node/TypeScript). That requires:

1. A **long-lived WebSocket per connected user** to WhatsApp's edge — not
   compatible with Celery's "task that finishes" model.
2. **No OAuth.** Auth is QR-code pairing → ~5-50 KB credentials blob per
   user, persisted and rehydrated on every reconnect.
3. **A non-Python runtime.** Baileys is the only mature lib that supports
   eager history pull (`syncFullHistory`); whatsmeow (Go) only does
   passive sync. Python wrappers are immature.
4. **Multi-tenant per-user chat selection.** User pairs phone, picks N
   chats from inbox, app subscribes only to those JIDs.
5. **Cross-user dedup at message level.** Alice and Bob in the same group
   both stream the same WhatsApp message; we want one canonical
   `DeliveryPackage` row per message, with an audit join table tracking
   which Donna users have seen it.

Outcome: a Node sidecar service running Baileys, paired with a thin
Django-side connector that fits Donna's existing connector folder
contract.

### Decisions (locked)

| Choice | Decision |
|---|---|
| Library | **Baileys** (Node + TypeScript). Eager history pull, larger community, well-documented QR rendering. |
| Sidecar location | **`/Users/ristoc/Workspaces/cube/donna/whatsapp-sidecar/`** — top-level repo dir alongside `server/`, `desktop/`, `docs/`. Independent runtime, own `package.json`, own `Dockerfile`. |
| Session blob storage | **Donna Postgres** via Django HTTP. Sidecar reads/writes credentials via `POST/GET /api/v1/integrations/whatsapp/sessions/{id}/credentials`. Encrypted at rest via `EncryptedTextField`. |
| Dedup model | First user wins `DeliveryPackage` row; **`WhatsAppMessageSeen(delivery_package, user)`** join table tracks every workspace user who also received the message. |
| History UX | Default **30d on subscribe** + separate `POST /subscriptions/{id}/extend-history` for deeper pulls. Per-chat cursor. |
| Ban risk | User informed at pair time. Mitigations: no automated sends in v1 (read-only ingest), no bulk operations. |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                       Donna Cloud / On-Premise                       │
│                                                                      │
│  ┌──────────────────┐                  ┌────────────────────────┐   │
│  │  Django server   │ <── HTTP/HMAC ──>│ whatsapp-sidecar (Node)│   │
│  │                  │                  │                        │   │
│  │ WhatsAppProvider │                  │   Baileys sockets ─┐   │   │
│  │ WhatsAppViewSet  │                  │   ┌────────────┐   │   │   │
│  │ ProviderWebhook  │                  │   │ alice@ws1  │───┼───┼───┼──► api.whatsapp.com
│  │   Callback       │                  │   │ bob@ws1    │───┼───┼───┼──► (per-user WS)
│  │                  │                  │   │ carol@ws2  │───┼───┼───┼──►
│  │ Postgres ────────┼─── credentials ──┤   └────────────┘   │   │   │
│  │ Redis    ────────┼─── job queue ────┤                    │   │   │
│  └──────────────────┘                  └────────────────────────┘   │
│         │                                                            │
│         └─ Celery worker (ingest_whatsapp_message)                  │
└──────────────────────────────────────────────────────────────────────┘
```

**Event flow on incoming WhatsApp message:**

```
WhatsApp ─┐
          │ (WebSocket)
          ▼
   sidecar receives msg on alice's socket
          │
          │ HMAC-sign body + POST
          ▼
   Django: POST /api/v1/integrations/whatsapp/webhook/callback
          │
          │ ProviderWebhookView (existing) dispatches to WhatsAppProvider
          │
          ▼
   WhatsAppProvider.dispatch_webhook(parsed, workspace)
          │
          ▼
   ingest_whatsapp_message.delay(workspace_id, user_id, message_id, raw)
          │
          ▼
   Celery worker:
     1. DeliveryPackage.objects.update_or_create(
          workspace, "whatsapp", message_id, ...)
        — first user wins, subsequent users no-op the row update.
     2. WhatsAppMessageSeen.objects.get_or_create(package, user)
        — every user who received this WhatsApp msg gets a row.
     3. default_storage.save({ws}/whatsapp/messages/{msg_id}.json, raw)
```

**Pairing flow:**

```
Client (web)                Django                       Sidecar           WhatsApp
    │                         │                              │                 │
    │ POST /sessions          │                              │                 │
    ├────────────────────────►│ create WhatsAppSession       │                 │
    │                         │ status=pending               │                 │
    │                         │                              │                 │
    │                         │ POST /sessions/{id}/pair     │                 │
    │                         ├─────────────────────────────►│ open Baileys    │
    │                         │                              │ socket; emit QR │
    │                         │                              ├────────────────►│
    │                         │                              │ QR string back  │
    │                         │◄─────────────────────────────┤                 │
    │                         │ {qr_string, expires_at}      │                 │
    │ {qr_string}             │                              │                 │
    │◄────────────────────────┤                              │                 │
    │                                                                          │
    │   User scans QR with phone ─────────────────────────────────────────────►│
    │                                                                          │
    │                         │   sidecar receives 'open' event                │
    │                         │   POST /sessions/{id}/credentials              │
    │                         │◄─────────────────────────────┤                 │
    │                         │   store blob, status=paired                    │
    │                         │                              │                 │
    │ GET /sessions/{id}      │                              │                 │
    ├────────────────────────►│                              │                 │
    │ {status=paired, jid}    │                              │                 │
    │◄────────────────────────┤                              │                 │
```

---

## File layout

### Sidecar (`/Users/ristoc/Workspaces/cube/donna/whatsapp-sidecar/`)

```
whatsapp-sidecar/
├── package.json
├── tsconfig.json
├── Dockerfile
├── .dockerignore
├── README.md
└── src/
    ├── index.ts          # HTTP server bootstrap (Fastify)
    ├── config.ts         # env loader (DONNA_DJANGO_URL, HMAC secret, ...)
    ├── auth.ts           # HMAC sign/verify on every Django ↔ sidecar call
    ├── sessions.ts       # Map<sessionId, BaileysClient> — process-local
    ├── baileys/
    │   ├── client.ts     # makeWASocket wrapper, event router
    │   ├── store.ts      # AuthState ↔ Django Postgres blob bridge
    │   └── history.ts    # syncFullHistory + on-demand history fetch
    ├── routes/
    │   ├── sessions.ts   # POST /sessions/:id/pair, GET .../status,
    │   │                  # GET .../chats, DELETE .../
    │   ├── subscriptions.ts  # POST .../subscriptions, extend-history
    │   └── health.ts     # GET /health
    └── webhook.ts        # outgoing: HMAC POST → Django callback URL
```

Key Baileys patterns:

- One `BaileysClient` per `WhatsAppSession` row, keyed by `session_id`.
- `makeWASocket({ auth, printQRInTerminal: false, syncFullHistory: true,
  generateHighQualityLinkPreview: false, browser: ["Donna", "Chrome", "1.0"] })`
- `sock.ev.on('creds.update', ...)` → push blob back to Django.
- `sock.ev.on('connection.update', ...)` → handle qr / open / close.
- `sock.ev.on('messaging-history.set', ...)` → bulk history ingest.
- `sock.ev.on('messages.upsert', ...)` → real-time ingest.
- All events filtered by `WhatsAppChatSubscription` JID list before
  forwarding to Django.

**Sidecar internal HTTP API (called by Django):**

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/sessions/:id/pair` | Open Baileys socket for session; return current QR. Idempotent on reconnect. |
| `GET` | `/sessions/:id/status` | `{state: pending|qr|paired|expired|disconnected, jid?, qr_string?}` |
| `GET` | `/sessions/:id/chats` | List user's WhatsApp chats `[{jid, name, is_group, unread_count, last_msg_at}]` (called after paired) |
| `POST` | `/sessions/:id/subscriptions` | Body: `{jids: [...], history_days: 30}` — start subscription + trigger history pull |
| `POST` | `/sessions/:id/subscriptions/:sub_id/extend-history` | Body: `{days_back: N}` — pull more historical messages for one chat |
| `DELETE` | `/sessions/:id` | Logout, close socket, drop credentials |
| `GET` | `/health` | Process health + connection count |

**Sidecar→Django callback** (single endpoint, reuses existing
`ProviderWebhookView`):

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/integrations/whatsapp/webhook/callback` | All events: `message_received`, `history_batch`, `session_paired`, `session_disconnected`, `creds_update`. Body type discriminated by `event_type` field. |

### Django side (`server/donna/integrations/connectors/whatsapp/`)

Already exists as empty `__init__.py`. Populate with:

```
connectors/whatsapp/
├── __init__.py
├── provider.py        # WhatsAppProvider (registered via @register)
├── client.py          # WhatsAppSidecarClient(BaseHTTPClient) → sidecar HTTP
├── adapter.py         # WhatsAppMessageAdapter (Baileys message → DeliveryPackage)
├── webhook.py         # WhatsAppWebhookHandler — HMAC verify + event-type dispatch
└── tasks.py           # ingest_whatsapp_message (one msg)
                       # ingest_whatsapp_history_batch (many msgs from one history push)
```

### New models — `server/donna/integrations/models.py` (extend)

Three new models live in the existing `integrations` app (next to
`DeliveryPackage`):

```python
class WhatsAppSession(TimestampsMixin):
    id              = UUIDField PK
    workspace       = FK Workspace, CASCADE
    user            = FK User, CASCADE   # the Donna user who paired
    jid             = CharField(64), blank=True   # populated post-pair (e.g. "447...@s.whatsapp.net")
    status          = CharField, choices = {PENDING, QR, PAIRED, EXPIRED, DISCONNECTED}
    credentials_blob = EncryptedTextField, blank=True, null=True
    last_qr_string  = TextField, blank=True
    last_qr_at      = DateTimeField, null=True
    paired_at       = DateTimeField, null=True

    class Meta:
        UniqueConstraint(fields=["user", "jid"], name="uq_wa_session_user_jid",
                         condition=Q(jid__isnull=False) & ~Q(jid=""))


class WhatsAppChatSubscription(TimestampsMixin):
    id                    = UUIDField PK
    session               = FK WhatsAppSession, CASCADE
    jid                   = CharField(255)         # chat JID (group or 1-1)
    chat_name             = CharField(255), blank=True
    is_group              = BooleanField
    enabled               = BooleanField, default=True
    history_pulled_until  = DateTimeField, null=True   # oldest msg ts so far
    initial_window_days   = IntegerField, default=30

    class Meta:
        UniqueConstraint(fields=["session", "jid"], name="uq_wa_subscription_session_jid")


class WhatsAppMessageSeen(TimestampsMixin):
    """Join: which Donna users have each DeliveryPackage in their WhatsApp inbox."""
    id               = UUIDField PK
    delivery_package = FK DeliveryPackage, CASCADE
    user             = FK User, CASCADE
    session          = FK WhatsAppSession, CASCADE   # which paired session received it
    seen_at          = DateTimeField              # WhatsApp msg ts as seen by this user

    class Meta:
        UniqueConstraint(fields=["delivery_package", "user"],
                         name="uq_wa_message_seen_package_user")
```

`DeliveryPackage` unchanged — first-user-wins via existing
`UniqueConstraint(workspace, "whatsapp", provider_item_id)` (WhatsApp
message ID is globally stable per Baileys docs).

### Django HTTP API (under `/api/v1/integrations/whatsapp/`)

A new `WhatsAppViewSet` mounted from `connectors/whatsapp/api.py`. Doesn't
fit `IntegrationViewSet` because it adds many WhatsApp-specific endpoints
(QR, chats, subscriptions). Mount alongside existing integrations URLs:

| Method | Path | Body / params | Returns |
|---|---|---|---|
| `POST` | `/api/v1/integrations/whatsapp/sessions` | (workspace header) | `{session_id, status, qr_string?}` — calls sidecar `/sessions/:id/pair` synchronously |
| `GET` | `/api/v1/integrations/whatsapp/sessions/:id` | — | `{status, jid?, qr_string?, expires_at?}` |
| `GET` | `/api/v1/integrations/whatsapp/sessions/:id/chats` | — | `[{jid, name, is_group, ...}]` (sidecar pass-through) |
| `POST` | `/api/v1/integrations/whatsapp/sessions/:id/subscriptions` | `{jids: [...], history_days: 30}` | Created subs |
| `POST` | `/api/v1/integrations/whatsapp/sessions/:id/subscriptions/:sub_id/extend-history` | `{days_back: N}` | `{enqueued: …}` |
| `DELETE` | `/api/v1/integrations/whatsapp/sessions/:id` | — | 204 |
| `POST` | **`/api/v1/integrations/whatsapp/webhook/callback`** | sidecar HMAC + event payload | 200 fast |
| `POST` | **`/api/v1/integrations/whatsapp/sessions/:id/credentials`** | sidecar HMAC + blob | 204 (sidecar persists creds) |
| `GET`  | **`/api/v1/integrations/whatsapp/sessions/:id/credentials`** | sidecar HMAC | `{credentials_blob}` (sidecar rehydrates on restart) |

Last three are sidecar↔Django; added to `WorkspaceMiddleware.IGNORED_SUFFIXES`.

### Provider class — uses existing framework

```python
@register
class WhatsAppProvider:
    slug                  = "whatsapp"
    display_name          = "WhatsApp"
    category              = "messaging"
    oauth_provider_slug   = "whatsapp"
    token_scope           = "user"
    default_authorize_url = ""   # not OAuth
    default_token_url     = ""
    default_scopes        = []
    supports_webhooks     = True  # sidecar → Django callback

    def client(self, token): raise NotImplementedError(
        "WhatsApp uses WhatsAppSidecarClient bound to a WhatsAppSession, not OAuthToken")
    def oauth_handler(self, cfg): raise NotImplementedError(
        "WhatsApp uses QR-code pairing, not OAuth")
    def webhook_handler(self): return WhatsAppWebhookHandler(config=self._oauth_config())
    def adapter_for(self, raw): return WhatsAppMessageAdapter(raw=raw)
    def resolve_workspace(self, parsed): ...
    def dispatch_webhook(self, *, parsed, workspace): ...
```

`OAuthProvider(slug="whatsapp")` row still gets created by
`integrations_bootstrap` — used only to hold `webhook_secret` (HMAC
shared secret between sidecar and Django) and `is_enabled`. Admin pastes
the secret matching what's set in the sidecar env.

### Adapter — `WhatsAppMessageAdapter`

Raw shape: Baileys `WAMessage` (`messages.upsert` payload).

- `external_id()` → `raw.key.id` (globally stable per WhatsApp)
- `title()` → first 100 chars of message text OR `"[image]" / "[audio]"`
- `occurred_at()` → `raw.messageTimestamp` (epoch seconds) → datetime
- `to_text()` → walk `message.conversation` / `message.extendedTextMessage.text` / caption fields; fall back to media-type placeholder
- `to_markdown()` → header (sender, chat, timestamp) + body
- `to_json()` → raw verbatim
- `metadata()` → `{jid: key.remoteJid, from_jid: key.participant or key.remoteJid, is_group: key.remoteJid.endsWith("@g.us"), from_me: key.fromMe, msg_type: …, has_media: …, media_mime: …, quoted_message_id: …}`

---

## Reused primitives (no new framework code)

| Primitive | Path | How used |
|---|---|---|
| `BaseHTTPClient` | `donna.core.integrations.client` | `WhatsAppSidecarClient` extends it to call sidecar HTTP with HMAC auth header |
| `BaseWebhookHandler` | `donna.core.integrations.webhook` | `WhatsAppWebhookHandler` extends it — overrides `verify` to use sidecar HMAC, parses multi-event payload |
| `ProviderWebhookView` | `donna.integrations.api.v1.webhooks` | Already routes `/integrations/{slug}/webhook/callback` — no change |
| `WorkspaceMiddleware.IGNORED_SUFFIXES` | `donna.workspaces.middlewares` | Already covers `/webhook/callback`; add `/credentials` suffix |
| `DeliveryPackage` | `donna.integrations.models` | Same row schema; `provider="whatsapp"`, `provider_item_id=msg_id` |
| `default_storage` | `STORAGES["default"]` | Raw Baileys message JSON lands at `{ws}/whatsapp/messages/{msg_id}.json` |
| `integrations_bootstrap` mgmt cmd | `donna.integrations.management.commands` | Auto-creates `OAuthProvider(slug="whatsapp")` row stub |
| `@register` + recursive discovery | `donna.integrations.apps` | Picks up `connectors/whatsapp/provider.py` + `tasks.py` |

---

## Celery tasks

```python
# connectors/whatsapp/tasks.py

@shared_task(name="integrations.whatsapp.ingest_message")
def ingest_whatsapp_message(workspace_id, user_id, session_id, raw_message):
    """
    raw_message = Baileys WAMessage dict (already JSON-passed-through).
    1. WhatsAppMessageAdapter(raw)
    2. DeliveryPackage.objects.update_or_create(workspace, "whatsapp", msg_id)
       — first user wins, subsequent users' calls are no-ops on content.
    3. WhatsAppMessageSeen.objects.get_or_create(package, user, session)
       — every user who received the msg gets a row.
    4. default_storage.save({ws}/whatsapp/messages/{msg_id}.json, json.dumps(raw))
       — idempotent overwrite.
    """

@shared_task(name="integrations.whatsapp.ingest_history_batch")
def ingest_whatsapp_history_batch(workspace_id, user_id, session_id, jid, messages):
    """
    Triggered by sidecar 'messaging-history.set' → POST /webhook/callback
    with event_type=history_batch + chunked messages array.
    Iterates `messages` and calls ingest_whatsapp_message inline (no fan-out)
    to avoid Celery flood from a 5000-msg backfill.
    """
```

No Celery beat schedule — WhatsApp is event-driven (push from sidecar).

---

## docker-compose.yml — new service

Add to `server/docker-compose.yml`:

```yaml
  whatsapp-sidecar:
    build:
      context: ../whatsapp-sidecar
      dockerfile: Dockerfile
    image: donna/whatsapp-sidecar:dev
    restart: unless-stopped
    environment:
      NODE_ENV: production
      PORT: "3001"
      DONNA_DJANGO_URL: http://web:8000
      DONNA_WHATSAPP_HMAC_SECRET: ${DONNA_WHATSAPP_HMAC_SECRET:-change-me-dev-only}
      LOG_LEVEL: info
    depends_on:
      web:
        condition: service_started
    ports:
      - "3001:3001"
```

Add to Django web service env:
```yaml
      DONNA_WHATSAPP_SIDECAR_URL: http://whatsapp-sidecar:3001
      DONNA_WHATSAPP_HMAC_SECRET: ${DONNA_WHATSAPP_HMAC_SECRET:-change-me-dev-only}
```

---

## Files to create (full list)

### Sidecar (Node + TypeScript)

| File | Purpose |
|---|---|
| `whatsapp-sidecar/package.json` | `@whiskeysockets/baileys`, `fastify`, `pino`, `typescript`, `tsx` |
| `whatsapp-sidecar/tsconfig.json` | TS config |
| `whatsapp-sidecar/Dockerfile` | Node 22 slim, `npm ci`, compile, run |
| `whatsapp-sidecar/.dockerignore` | `node_modules`, `dist` |
| `whatsapp-sidecar/README.md` | How to run, env vars, ban-risk disclaimer |
| `whatsapp-sidecar/src/index.ts` | Fastify bootstrap |
| `whatsapp-sidecar/src/config.ts` | Env loader |
| `whatsapp-sidecar/src/auth.ts` | HMAC sign/verify |
| `whatsapp-sidecar/src/sessions.ts` | In-memory session registry |
| `whatsapp-sidecar/src/baileys/client.ts` | `makeWASocket` wrapper + event router |
| `whatsapp-sidecar/src/baileys/store.ts` | Auth state ↔ Django blob bridge |
| `whatsapp-sidecar/src/baileys/history.ts` | History pull helpers |
| `whatsapp-sidecar/src/routes/sessions.ts` | Session HTTP routes |
| `whatsapp-sidecar/src/routes/subscriptions.ts` | Subscription HTTP routes |
| `whatsapp-sidecar/src/routes/health.ts` | GET /health |
| `whatsapp-sidecar/src/webhook.ts` | Outgoing event POST to Django |

### Django

| File | Purpose |
|---|---|
| `server/donna/integrations/connectors/whatsapp/provider.py` | `WhatsAppProvider`, `@register` |
| `server/donna/integrations/connectors/whatsapp/client.py` | `WhatsAppSidecarClient(BaseHTTPClient)` |
| `server/donna/integrations/connectors/whatsapp/adapter.py` | `WhatsAppMessageAdapter(BaseAdapter)` |
| `server/donna/integrations/connectors/whatsapp/webhook.py` | `WhatsAppWebhookHandler(BaseWebhookHandler)` — HMAC + event-type dispatch |
| `server/donna/integrations/connectors/whatsapp/tasks.py` | `ingest_whatsapp_message`, `ingest_whatsapp_history_batch` |
| `server/donna/integrations/connectors/whatsapp/api.py` | `WhatsAppViewSet` + sidecar↔Django routes |
| `server/donna/integrations/connectors/whatsapp/urls.py` | URL routing (mounted from `integrations/urls.py`) |
| `server/donna/integrations/models.py` | **EXTEND** — add 3 new models (`WhatsAppSession`, `WhatsAppChatSubscription`, `WhatsAppMessageSeen`) |
| `server/donna/integrations/urls.py` | **EXTEND** — include `connectors/whatsapp/urls.py` under `/api/v1/integrations/whatsapp/` |
| `server/donna/workspaces/middlewares.py` | **EXTEND** — add `/credentials` to `IGNORED_SUFFIXES` (POST + GET) |
| `server/docker-compose.yml` | **EXTEND** — `whatsapp-sidecar` service + 2 env vars on `web` |

### Migrations (will be needed)

One migration in `integrations` app: 3 new tables + 4 indexes + 3 unique
constraints. Per session policy "no migrations right now," I'll write the
model code; you run `makemigrations integrations && migrate` when ready.

---

## Verification

After implementation (assumes Postgres + Redis + web + worker + sidecar all running):

```bash
# 1. Boot
cd server
DJANGO_SETTINGS_MODULE=donna.settings .venv/bin/python -m django check

# 2. WhatsApp connector registered
DJANGO_SETTINGS_MODULE=donna.settings .venv/bin/python -c "
import django; django.setup()
from donna.core.integrations import all_loaded
print(sorted(c.slug for c in all_loaded()))
"
# expect: ['fathom', 'gmail', 'whatsapp']

# 3. Bootstrap creates OAuthProvider(slug='whatsapp')
DJANGO_SETTINGS_MODULE=donna.settings .venv/bin/python -m django integrations_bootstrap

# 4. Manually fill OAuthProvider('whatsapp').webhook_secret via Django admin
#    with same value as DONNA_WHATSAPP_HMAC_SECRET. Flip is_enabled=True.

# 5. Sidecar reachable
curl http://localhost:3001/health
# expect: {"ok": true, "connected_sessions": 0}

# 6. End-to-end pair (with browser):
#    POST /api/v1/integrations/whatsapp/sessions (X-Workspace-Id, auth)
#      → {session_id, qr_string}
#    Render QR in client; user scans with phone
#    GET /api/v1/integrations/whatsapp/sessions/{id}
#      → {status: paired, jid: "44...@s.whatsapp.net"}
#    GET /api/v1/integrations/whatsapp/sessions/{id}/chats
#      → list of chats
#    POST /api/v1/integrations/whatsapp/sessions/{id}/subscriptions
#      body {jids: ["12345-678@g.us"], history_days: 30}
#    Wait ~10s for history pull
#    Verify DeliveryPackage rows + WhatsAppMessageSeen rows created
#    Verify storage_key files exist in {workspace_id}/whatsapp/messages/

# 7. Dedup check (two users in same group)
#    Pair user A and user B from same workspace into same group chat
#    Send a test message to the group from a third device
#    Verify: 1 DeliveryPackage row, 2 WhatsAppMessageSeen rows.
```

---

## Open gaps (deferred, document only)

1. **Session resilience on sidecar restart.** Sidecar process restart →
   in-memory session map cleared → all sockets dropped. v1 strategy:
   sidecar boot iterates `WhatsAppSession.objects.filter(status=PAIRED)`,
   reloads each blob, re-opens socket. Acceptable for small N; needs
   sharding/sticky-routing at >100 concurrent sessions.

2. **Per-chat message scope policy.** A subscribed group chat may
   include messages from non-Donna external participants. v1 stores
   everything. Future: per-chat allowlist of senders, or PII masking.

3. **Outbound message sending.** Out of scope for v1 (read-only ingest).
   When agent actions land, sidecar gets `POST
   /sessions/:id/messages/send` and a new `outgoing-whatsapp-message`
   Celery task or direct HTTP.

4. **Media downloads.** Baileys returns media URLs that need a separate
   `downloadContentFromMessage` call. v1: store metadata only
   (`has_media: true`, `media_mime`); fetch on demand later. Future:
   eager pull → `default_storage` under
   `{ws}/whatsapp/media/{message_id}.{ext}`.

5. **Cross-account history overlap.** When Alice subscribes 30d of group
   X, and Bob (also in group X) joins later with his own 30d window,
   we'd re-fetch messages already in `DeliveryPackage`. Idempotent
   upsert handles it but wastes API + sidecar work. Future: skip
   history pull for JIDs already covered by another paired user in the
   same workspace.

6. **Phone-number pairing (no QR).** Baileys supports
   `sock.requestPairingCode(phone)` returning a code the user types in
   WhatsApp. v1 sticks with QR (simpler UX); add as optional path
   later.

7. **`WhatsAppMessageSeen.session` FK on `CASCADE`.** If a session is
   unpaired/deleted, we lose the audit of "user X saw this message via
   session Y." Could `SET_NULL` instead to preserve audit. Decision
   deferred — `CASCADE` for v1, revisit on real-world delete patterns.

8. **Ban-risk dashboard.** Eventually surface in admin: which sessions
   have been "logged out by phone" (a frequent Baileys disconnect
   reason that often precedes ban). v1: log to structlog, no UI.

---

## Out of scope (explicitly)

- WhatsApp Business Cloud API (see Future section below)
- Sending messages from Donna
- Media file download / OCR
- Per-message PII redaction
- Tests (per session policy)
- Migrations applied (per session policy — model code written, you run
  `makemigrations + migrate` when ready)

---

## Ban-risk mitigations (personal Baileys path)

WhatsApp ToS prohibits automation on personal accounts. Risk is real but
manageable for read-only ingest. Mitigations Donna applies:

| # | Practice | Why |
|---|---|---|
| 1 | Read-only in v1 (no sending) | Sending triggers spam detection. Receiving is mostly invisible. |
| 2 | Warmed accounts only — employees' real numbers used for months/years | New numbers paired then immediately active = flagged. |
| 3 | Stable connections, exponential back-off on reconnect | Churn looks bot-like. |
| 4 | Custom browser fingerprint: `browser: ["Donna", "Chrome", "1.0"]` | Don't spoof official multi-device clients. Real third-party id looks normal. |
| 5 | Throttle historical pulls — chunk over hours, not seconds | Bulk backfill is obvious. |
| 6 | Geo consistency — sidecar IP region matches user's phone region | Phone in UK + Web from Vietnam = instant ban. Self-host = users' infra. Cloud = pin sidecar region per workspace. |
| 7 | On `connection.update` reason=`loggedOut` → alert user, DO NOT auto-reconnect | "Logged out by phone" = soft-ban canary. Hammering reconnect escalates. |
| 8 | One session per number (DB unique on `(user, jid)`) | Multi-pairing = duplicate-device suspicion. |
| 9 | No group-admin operations (no auto add/remove, no group create) | Top historical ban trigger. |
| 10 | Stay on latest Baileys (`^` not pinned exact) | WhatsApp patches protocol; old signatures get flagged. |
| 11 | No contact enumeration on startup | Mass profile reads = scraping signal. |
| 12 | When sending lands (v2): random 2-30s delays, typing indicators, max ~20 msgs/min/account | Velocity caps mirror real users. |

**Realistic estimate:** ~1-5% annualized ban risk per account in read-only
mode. User informed at pair time. Surface session disconnects immediately
in Donna UI so users can re-pair before pattern escalates.

---

## Future: WhatsApp Business Cloud API connector

**Out of scope for v1, documented for future.**

WhatsApp Business Cloud API is a separate Meta product. Different
protocol, different setup, different limitations. Donna will add it as a
**second connector** alongside personal, not a replacement.

### Why it's a separate connector

| Dimension | Personal (`connectors/whatsapp/`) | Business (`connectors/whatsapp_business/`) |
|---|---|---|
| Auth | QR-code pair → credentials blob | Meta OAuth / system user token + verified phone number id |
| Transport | WebSocket via Baileys sidecar | Standard HTTPS webhook + REST API |
| Sidecar needed? | Yes (Node) | No — fits existing Django + Celery directly |
| Ban risk | Real (ToS gray area) | None (sanctioned API) |
| Coverage | All chats user has on their phone | Only customers who messaged the business number, 24h reply window |
| Cost | Free | Free tier + per-conversation pricing |
| Setup difficulty | User scans QR (~10s) | Admin: Meta Business account + number verification + app registration (~30 min, technical) |

### Architecture sketch (for future implementation)

- **Folder:** `server/donna/integrations/connectors/whatsapp_business/`
- **Stack:** Same as Fathom — `provider.py` + `client.py` + `adapter.py`
  + `tasks.py` + `webhook.py` + `oauth.py` (optional, if OAuth flow).
  No sidecar.
- **Provider class:** `slug = "whatsapp_business"`, `oauth_provider_slug =
  "whatsapp_business"`, `supports_webhooks = True`.
- **HTTP client:** `WhatsAppBusinessClient(BaseHTTPClient)`:
  - `base_url = "https://graph.facebook.com/v21.0"` (or current Graph version)
  - Auth header: `Bearer <system_user_access_token>`
  - Methods: `send_message`, `list_messages` (limited), `get_media_url`
- **Webhook handler:** standard HMAC-SHA256 verification using Meta's
  `X-Hub-Signature-256` header. Reuses `BaseWebhookHandler` defaults
  with minor signature-header override.
- **OAuth handler:** Meta's Facebook Login for Business flow (similar
  shape to standard OAuth 2.0 authorization-code; can reuse
  `BaseOAuthHandler` with provider-specific authorize/token URLs).
- **Subscription model:** No per-chat selection. Business numbers receive
  webhook events for every message sent TO the business number. Donna
  ingests all of them.
- **Dedup:** Different `provider` slug (`whatsapp_business`) so it doesn't
  collide with personal `whatsapp` provider items.
- **No new database models needed** — just `DeliveryPackage` rows.

### Setup flow for an on-prem customer

1. Meta Business Account: register the company.
2. Add a phone number to WhatsApp Business Platform (must be a number not
   previously used in the consumer WhatsApp app).
3. Verify domain ownership for the redirect URI.
4. Create a Meta App, enable WhatsApp product, generate system user access
   token.
5. In Donna admin: paste `client_id` (App ID), `client_secret` (App
   secret), `redirect_uri`, system user token into
   `OAuthProvider(slug="whatsapp_business")`. Flip `is_enabled=True`.
6. Configure Meta webhook to `https://{donna-host}/api/v1/integrations/whatsapp_business/webhook/callback`
   with the matching HMAC secret.

### Open questions to revisit when this is built

- **Phone number ID vs OAuth account:** Meta's model gives one app multiple
  phone numbers. Per-workspace phone number selection — extend
  `OAuthToken.metadata` to hold `phone_number_id`?
- **Template messages:** outbound (send) workflow needs pre-approved
  templates from Meta. Out of scope until v2 sending lands.
- **Media handling:** Meta returns media URLs that expire in 5 min.
  Sidecar/worker must download promptly. Same `default_storage` pattern
  as personal flow.
- **Coexistence with personal connector:** if a workspace has both
  personal-Alice and business-AcmeCorp connected, group chats where Alice
  uses her personal number to chat with an Acme customer create overlap.
  Different provider slugs keep DeliveryPackage rows separate but
  WhatsAppMessageSeen-style audit across the two connectors is open.
