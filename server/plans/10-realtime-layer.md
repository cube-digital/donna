# Plan — Realtime layer: SSE per-(user, workspace) + WebSocket chat/DM/agent

## Context

Donna shipped SSE-based notifications keyed by user only
(`user-{uid}-notifications`). Two new requirements landed:

1. **SSE must scope per user AND per workspace** — workspace-wide
   announcements (billing, integration sync events, "channel created")
   should reach members of that workspace even when no specific user is
   the target.
2. **Chat needs a different transport** — Slack-style channels + DMs +
   agent token streaming. SSE is one-way and forces a separate HTTP
   POST per message/typing/read-receipt. WebSockets fit the bidirectional
   + high-frequency shape.

The chat data model already exists in `donna/chat/models.py`:
`Channel(kind=CHANNEL|DIRECT)`, `ChannelMembership`, `AgentSession`,
`Message`, `Document`. Views/services/URLs are empty stubs ready to
populate. No `DirectMessage` row needed — DMs are
`Channel(kind=DIRECT)` with exactly two members. No reactions /
threading / attachments in v1 per `plans/02-data-model.md`.

`donna/workspaces/models.py` defines `Workspace` + `WorkspaceMembership`
(roles OWNER/ADMIN/MEMBER/GUEST). User's workspace memberships drive
which SSE/WS subscriptions the server opens on their behalf.

This plan keeps **one shared Redis pubsub backbone** (`redis_manager`
in `donna/core/cache/redis_cache.py`) and adds **two transports** that
both read from it.

---

## Locked decisions

| Choice | Decision |
|---|---|
| Transport split | **SSE** = sparse server push (notifications, integration sync events, activity feed). **WebSocket** = chat messages, typing, presence, agent token streaming. |
| WS framework | **Django Channels 4** + `channels_redis` (uses existing Redis at `CELERY_BROKER_URL`). |
| ASGI server | **uvicorn** (already in `pyproject.toml`); routes HTTP + WS via combined `ProtocolTypeRouter` in `donna/asgi.py`. |
| SSE channels | Three flavours: `user-{uid}-notifications`, `workspace-{wid}-notifications`, `user-{uid}-workspace-{wid}-feed`. Server fans in all relevant channels per connection. |
| WS connection model | **One WS per user** (not per workspace). Subscribe/unsubscribe per resource via WS messages. Workspace switching = subscription churn, not reconnect. |
| WS channel naming | `presence-user-{uid}`, `workspace-{wid}-events`, `chat-channel-{cid}`, `chat-channel-{cid}-typing`, `chat-dm-{cid}` (DM = Channel with kind=DIRECT, same channel naming as group), `agent-run-{run_id}-tokens`. |
| Read tracking | **Per-channel last-read pointer** — one row per `(user, channel)` with `last_read_message_id` + `last_read_at`. Slack-style; cheap; no per-message rows. New model `ChannelReadState`. |
| Agent token streaming | **WebSocket** — `agent-run-{run_id}-tokens` joined by the requesting user only; agent worker publishes token chunks. |
| Presence | **Redis ephemeral only** — `presence:user:{uid}` SET key with 30s TTL refreshed by WS heartbeat. Typing = pubsub event, not stored. No `last_seen_at` column v1. |
| WS auth | **JWT in `Sec-WebSocket-Protocol` subprotocol header** — server reads `bearer.<token>`, validates via simplejwt, attaches `scope["user"]` before consumer accepts. |
| Workspace authorization | Every WS subscribe checks `WorkspaceMembership` for the target workspace; every channel subscribe checks `ChannelMembership`. Authorization at subscribe time, not message time. |
| Workspace middleware bypass | `/ws/` prefix added to `WorkspaceMiddleware.IGNORED_PATHS` (WS handshake is GET to `/ws/...`, doesn't carry `X-Workspace-Id`; workspace context derived from subscribed channels instead). |
| SSE rewrite scope | `NotificationService.create_alert` gains `workspace=` + `scope=` kwargs; `notifications_sse_view` reads user's `WorkspaceMembership` set and fans in. |

---

## Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│ Browser (one user, one tab)                                            │
│                                                                        │
│  EventSource ─► /api/v1/notifications/stream         (SSE)             │
│  WebSocket   ─► wss://api.donna/ws/    (subprotocol: bearer.JWT)       │
│                                                                        │
└──────────┬──────────────────────────────────────────────────┬──────────┘
           │ HTTP(S) (HTTP/1.1 long-lived)                    │ WS (ws/wss)
           ▼                                                  ▼
┌────────────────────────────────┐         ┌─────────────────────────────────┐
│ uvicorn (ASGI)                 │         │ uvicorn (ASGI)                  │
│                                │         │                                 │
│ Django HTTP stack              │         │ Channels WS stack               │
│ ├── DRF views                  │         │ ├── donna.chat.consumers        │
│ └── notifications_sse_view ◄─┐ │         │ │     ├── ChatConsumer          │
│       async gen reads pubsub │ │         │ │     └── AgentStreamConsumer   │
│                              │ │         │ └── channel_layer (Redis)       │
└──────────────────────────────┼─┘         └──────────────┬──────────────────┘
                               │                          │
                               ▼                          ▼
                          ┌─────────────────────────────────────────────┐
                          │ Redis pubsub  (donna.core.cache.redis_cache)│
                          │                                             │
                          │  user-{uid}-notifications                   │
                          │  workspace-{wid}-notifications              │
                          │  user-{uid}-workspace-{wid}-feed            │
                          │  presence-user-{uid}                        │
                          │  workspace-{wid}-events                     │
                          │  chat-channel-{cid}                         │
                          │  chat-channel-{cid}-typing                  │
                          │  chat-dm-{cid}             (Channel kind=DIRECT) │
                          │  agent-run-{run_id}-tokens                  │
                          └─────────────────────────────────────────────┘
                                            ▲
                                            │ publish
                                            │
                          ┌─────────────────┴────────────────────┐
                          │ Publishers                            │
                          │  • Celery tasks (integration sync)    │
                          │  • Service layer (chat send, agent)   │
                          │  • Signal handlers (workspace events) │
                          └───────────────────────────────────────┘
```

---

## SSE — extend current implementation

### Channel scheme (final)

| Channel | Producer | Consumer trigger |
|---|---|---|
| `user-{uid}-notifications` | Personal events (password changed, mention received, DM badge bump) | Every SSE connection |
| `workspace-{wid}-notifications` | Workspace-wide (billing, settings changed, integration connected) | Every SSE connection — for each `wid` in user's memberships |
| `user-{uid}-workspace-{wid}-feed` | User-scoped within workspace (sync completed, agent task done, integration disconnected) | Every SSE connection — for each `wid` in user's memberships |

### `NotificationService.create_alert` — new signature

```python
class NotificationStatus(models.TextChoices): ...   # unchanged


class NotificationScope(models.TextChoices):
    USER              = "user",              _("User")               # personal
    WORKSPACE         = "workspace",         _("Workspace")          # broadcast to all members
    USER_IN_WORKSPACE = "user_in_workspace", _("User in workspace")  # user-scoped, workspace-tagged


class NotificationService:
    @staticmethod
    def create_alert(
        user,                              # required (audit + DB row owner even for workspace scope)
        title,
        message,
        notification_type="info",
        data=None,
        store=True,
        workspace=None,                    # required iff scope != USER
        scope=NotificationScope.USER,
    ):
        # 1. Persist
        if store:
            Notification.objects.create(
                user=user, workspace=workspace, title=title, message=message,
                type=notification_type, scope=scope, context=data or {},
            )
        # 2. Publish — choose channel by scope
        channel = _channel_for_scope(scope, user_id=user.id, workspace_id=workspace.id if workspace else None)
        redis_manager.publish_event(channel, json.dumps(payload.to_dict()))
```

`scope` field becomes part of `Notification` model so the DB knows what
channel the row was emitted on (used for UI filtering + replay on
reconnect).

### SSE view — fan-in per user's workspaces

```python
async def notifications_sse_view(request):
    # Inline JWT auth — AuthenticationMiddleware doesn't run DRF auth
    # on async views, so request.user is anonymous here. Reuse the
    # WS subprotocol helper so we have a single JWT validation path.
    user = await _authenticate_sse_request(request)   # → donna.chat.auth.resolve_jwt_user
    if user is None or not user.is_authenticated:
        return _unauthenticated_sse_response()

    workspace_ids = await get_user_workspace_ids(user.id)   # async DB call
    channels = [f"user-{user.id}-notifications"]
    for wid in workspace_ids:
        channels.append(f"workspace-{wid}-notifications")
        channels.append(f"user-{user.id}-workspace-{wid}-feed")

    async def stream():
        async for chunk in NotificationService.create_sse_stream_multi(channels):
            yield chunk
    return StreamingHttpResponse(stream(), content_type="text/event-stream")
```

`create_sse_stream_multi(channels: list[str])` subscribes to all
channels at once (single `pubsub.subscribe(*channels)` call) and
multiplexes into one yield loop. Replaces single-channel
`create_sse_stream`.

### Notification model — new `scope` field

```python
class Notification(TimestampsMixin):
    # ... existing fields ...
    scope = models.CharField(max_length=32, choices=NotificationScope.choices,
                              default=NotificationScope.USER)
    # Index for "list notifications I should see in this workspace":
    #   (user_id, workspace_id, -created_at)
```

Backward-compatible migration: existing rows default to `USER`.

---

## WebSocket — chat + DM + presence + agent

### URL layout

```
ws://api.donna/ws/                     unified endpoint, subprotocol auth
   → ChatConsumer (handles all chat/DM/presence/workspace events for the user)

ws://api.donna/ws/agent/{run_id}/      per-run agent token stream
   → AgentStreamConsumer
```

One `ChatConsumer` per user handles everything chat-related. Separate
`AgentStreamConsumer` per agent run because runs are short-lived (open
when starting a prompt, close when done) and isolate failure modes.

### `ChatConsumer` — message protocol

**Client → Server actions (incoming WS frame):**

```json
{ "action": "subscribe_channel",   "channel_id": "uuid" }
{ "action": "unsubscribe_channel", "channel_id": "uuid" }
{ "action": "send_message",        "channel_id": "uuid", "body": "hi", "client_msg_id": "uuid" }
{ "action": "edit_message",        "message_id": "uuid", "body": "..." }
{ "action": "delete_message",      "message_id": "uuid" }
{ "action": "typing",              "channel_id": "uuid" }              // ephemeral
{ "action": "mark_read",           "channel_id": "uuid", "message_id": "uuid" }
{ "action": "heartbeat" }                                              // refreshes presence TTL
{ "action": "open_dm",             "peer_user_id": "uuid" }            // resolve/create kind=DIRECT Channel
```

**Server → Client events (outgoing WS frame):**

```json
{ "event": "connected",          "user_id": "..." }
{ "event": "message.created",    "channel_id": "...", "message": {...} }
{ "event": "message.updated",    "channel_id": "...", "message": {...} }
{ "event": "message.deleted",    "channel_id": "...", "message_id": "..." }
{ "event": "typing",             "channel_id": "...", "user_id": "..." }
{ "event": "presence",           "user_id": "...", "online": true }
{ "event": "channel.created",    "workspace_id": "...", "channel": {...} }
{ "event": "channel.member.added", "channel_id": "...", "user_id": "..." }
{ "event": "read.advanced",      "channel_id": "...", "user_id": "...", "message_id": "..." }
{ "event": "dm.opened",          "channel_id": "...", "peer_user_id": "..." }
{ "event": "error",              "code": "...", "detail": "..." }
```

### Subscribe lifecycle

On `connect()`:
1. Auth JWT from `Sec-WebSocket-Protocol` subprotocol header.
2. `await self.channel_layer.group_add(f"presence-user-{uid}", self.channel_name)`
3. For each workspace the user belongs to: `group_add(f"workspace-{wid}-events")`
4. Mark presence: `redis_manager.set(f"presence:user:{uid}", "1", ex=30)` + publish `{event: "presence", online: true}` to `presence-user-{uid}`.
5. Send `{event: "connected"}`.

On `subscribe_channel`:
1. Authorize: `ChannelMembership.objects.filter(user=self.user, channel_id=cid).exists()`.
2. `group_add(f"chat-channel-{cid}")` + `group_add(f"chat-channel-{cid}-typing")`.

On `open_dm(peer_user_id)`:
1. Validate caller + peer share at least one workspace.
2. `ChannelService.get_or_create_dm(user, peer)` — returns/creates `Channel(kind=DIRECT)` with both as members.
3. Auto-subscribe both groups for caller; return `{event: "dm.opened", channel_id: …}`.
4. Server-side: publish `{event: "dm.opened"}` on `presence-user-{peer_uid}` so peer's WS knows too.

On `disconnect()`:
1. Leave all groups.
2. Delete presence key (or let TTL expire).
3. Publish `{event: "presence", online: false}`.

### `AgentStreamConsumer` — token streaming

```python
class AgentStreamConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        run_id = self.scope["url_route"]["kwargs"]["run_id"]
        self.user = await get_user_from_subprotocol(self.scope)
        if not self.user:
            await self.close(code=4401)
            return
        # Authorize: caller owns this agent run, OR channel of the run
        if not await user_can_view_run(self.user, run_id):
            await self.close(code=4403)
            return
        await self.channel_layer.group_add(f"agent-run-{run_id}-tokens", self.channel_name)
        await self.accept(subprotocol="bearer")
```

Agent worker (Celery task or sync handler) publishes token chunks:

```python
# In agent execution code, per emitted token
async_to_sync(channel_layer.group_send)(
    f"agent-run-{run_id}-tokens",
    {"type": "agent.token", "payload": {"token": chunk, "run_id": run_id}},
)
```

Consumer's `agent_token` method forwards to WS frontend.

---

## New + modified models

### NEW — `donna/chat/models.py` (extend)

```python
class ChannelReadState(TimestampsMixin):
    """
    Per (user, channel) last-read pointer. Drives unread badges.
    Slack-style; one row per (user, channel), not per message.
    """
    id              = UUIDField PK
    user            = FK User
    channel         = FK Channel
    last_read_message = FK Message, null=True   # null when channel never opened
    last_read_at    = DateTimeField, null=True

    class Meta:
        constraints = [
            UniqueConstraint(fields=["user", "channel"],
                             name="uq_channel_read_state_user_channel"),
        ]
        indexes = [Index(fields=["user", "channel"])]
```

### MODIFY — `donna/notifications/models.py`

Add `scope` field (CharField, choices). Migration: backward-compatible
default `USER`.

### NEW — `donna/chat/services.py` (populate stub)

`ChannelService.send_message()`, `.edit_message()`, `.delete_message()`,
`.get_or_create_dm()`, `.advance_read_pointer()`.

Each method:
1. Performs the DB mutation.
2. Calls `channel_layer.group_send` to push the event to subscribed WS
   clients.
3. (When relevant) calls `NotificationService.create_alert` to push a
   notification (e.g., DM message → mentioned user gets a notification).

---

## File-by-file plan

```
donna/
├── asgi.py                                MODIFY — ProtocolTypeRouter (HTTP + WS)
├── settings.py                            MODIFY — INSTALLED_APPS += "channels",
│                                                    CHANNEL_LAYERS, ASGI_APPLICATION
├── core/cache/redis_cache.py              MODIFY — add sync `set_ex(key, value, ttl)`
│                                                    + `get(key)` helpers for presence
├── notifications/
│   ├── models.py                          MODIFY — add NotificationScope choices + scope field
│   ├── services.py                        MODIFY — create_alert(scope=, workspace=) routing;
│   │                                                add create_sse_stream_multi(channels)
│   └── api/v1/views.py                    MODIFY — notifications_sse_view fans in user's
│                                                    workspace channels
├── chat/
│   ├── models.py                          MODIFY — + ChannelReadState
│   ├── services.py                        POPULATE — ChannelService (send/edit/delete/
│   │                                                  get_or_create_dm/advance_read)
│   ├── consumers.py                       NEW    — ChatConsumer, AgentStreamConsumer
│   ├── routing.py                         NEW    — WS URL routing
│   ├── auth.py                            NEW    — subprotocol JWT extraction helper
│   ├── api/v1/views.py                    POPULATE — ChannelViewSet, MessageViewSet,
│   │                                                  DM helpers, read endpoints
│   ├── api/v1/serializers.py              POPULATE — ChannelSerializer, MessageSerializer
│   └── urls.py                            POPULATE — HTTP-side chat routes
└── workspaces/
    └── middlewares.py                     MODIFY — add "/ws" to IGNORED_PATHS

pyproject.toml                             MODIFY — add channels>=4.1, channels_redis>=4.2
```

No new app needed. `channels` is added as a third-party app in
`INSTALLED_APPS` only.

---

## Settings additions

```python
# settings.py

INSTALLED_APPS = [
    # ...
    "channels",                           # NEW — must precede django.contrib.staticfiles
    # ...
]

ASGI_APPLICATION = "donna.asgi.application"

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [env.str("CHANNELS_REDIS_URL", default=env.str("CELERY_BROKER_URL"))],
        },
    },
}

# Presence TTL — WS clients heartbeat at half this interval.
DONNA_PRESENCE_TTL_SECONDS = env.int("DONNA_PRESENCE_TTL_SECONDS", default=30)
```

### `donna/asgi.py`

```python
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "donna.settings")
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator

from donna.chat.routing import websocket_urlpatterns
from donna.chat.auth import SubprotocolJWTAuthMiddlewareStack

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(
        SubprotocolJWTAuthMiddlewareStack(URLRouter(websocket_urlpatterns))
    ),
})
```

### `donna/chat/routing.py`

```python
from django.urls import re_path
from .consumers import AgentStreamConsumer, ChatConsumer

websocket_urlpatterns = [
    re_path(r"^ws/$",                            ChatConsumer.as_asgi()),
    re_path(r"^ws/agent/(?P<run_id>[^/]+)/?$",   AgentStreamConsumer.as_asgi()),
]
```

### `donna/chat/auth.py` — subprotocol JWT middleware

Reads `Sec-WebSocket-Protocol: bearer.<token>` header from `scope["subprotocols"]`,
validates via `rest_framework_simplejwt`, sets `scope["user"]` before
consumer's `connect()` runs. Closes 4401 if invalid.

---

## HTTP-side chat API (sibling to WS)

WS handles realtime; HTTP REST handles persistence + history. Frontend
flow: REST loads channel history on open, then WS pushes new events.

```
GET    /api/v1/chat/channels/                   list user's channels in current workspace
POST   /api/v1/chat/channels/                   create channel
GET    /api/v1/chat/channels/{id}/              retrieve
DELETE /api/v1/chat/channels/{id}/              archive

GET    /api/v1/chat/channels/{id}/messages/     paginated history (before=, limit=)
POST   /api/v1/chat/channels/{id}/messages/     send (alternative to WS send_message)
PATCH  /api/v1/chat/messages/{id}/              edit
DELETE /api/v1/chat/messages/{id}/              delete

POST   /api/v1/chat/dms/                        body: {peer_user_id} → get_or_create_dm
GET    /api/v1/chat/channels/{id}/read-state/   { last_read_message_id, last_read_at, unread_count }
POST   /api/v1/chat/channels/{id}/read-state/   body: {message_id} — advance pointer
```

`POST /messages/` and WS `send_message` both call
`ChannelService.send_message()`. Service does the DB write + the
`group_send`. Single code path, two entry points.

---

## Authentication + authorization flow

### SSE
- The `/api/v1/notifications/stream` endpoint is a **plain async Django
  view**, not DRF — Django's `AuthenticationMiddleware` does not run
  DRF authenticators on async views, so `request.user` is always
  `AnonymousUser` here.
- The view therefore decodes `Authorization: Bearer <jwt>` itself and
  resolves the user via `donna.chat.auth.resolve_jwt_user` — the
  same helper the WS subprotocol middleware uses. Single JWT
  validation path across both async transports.
- A missing or invalid bearer header returns a single `event: error`
  SSE frame with HTTP 401 (`_unauthenticated_sse_response`). Frontend
  reconnects with exponential backoff; the loop also tolerates a
  not-yet-hydrated access token at boot.
- Once authenticated, the view reads `WorkspaceMembership` set and
  builds the channel list. No per-channel authz at subscribe —
  workspace membership is the authorization (you see workspace events
  because you're a member).

### WS connect
- `SubprotocolJWTAuthMiddlewareStack` reads `bearer.<token>` from
  `Sec-WebSocket-Protocol`, validates token, sets `scope["user"]`.
- Consumer's `connect()` rejects with `close(4401)` if anonymous.

### WS per-action authorization

| Action | Check |
|---|---|
| `subscribe_channel` | `ChannelMembership.objects.filter(user=u, channel=c).exists()` |
| `send_message` | same |
| `edit/delete_message` | message author == user OR ChannelMembership.role == ADMIN |
| `open_dm` | both users share at least one `WorkspaceMembership` |
| `mark_read` | same as `subscribe_channel` |

Authorization checks are async DB calls; cache per (user, channel) in
consumer state to avoid hammering DB on every action.

---

## Reused primitives (no new framework code)

| Primitive | Path | How used |
|---|---|---|
| `redis_manager` | `donna/core/cache/redis_cache.py` | Sync publish, async client; extend with `set_ex`/`get` for presence |
| `NotificationService` | `donna/notifications/services.py` | Extended with scope + workspace routing |
| `Channel`, `ChannelMembership`, `Message`, `AgentSession` | `donna/chat/models.py` | Already defined; no schema change beyond ChannelReadState |
| `Workspace`, `WorkspaceMembership` | `donna/workspaces/models.py` | Authorization checks |
| `rest_framework_simplejwt` | already installed | JWT validation in WS subprotocol middleware |
| `uvicorn` | already in deps | ASGI server, serves HTTP + WS |
| `channels_redis` channel_layer | new dep | `group_send`/`group_add` over Redis |

---

## Migrations needed (deferred per session policy)

- `notifications/0002_notification_scope.py` — `Notification.scope` (default `USER`)
- `chat/0002_channel_read_state.py` — new `ChannelReadState` model

Run `makemigrations notifications chat && migrate` when ready.

---

## Out of scope (explicitly)

- Message reactions, threads, attachments (already deferred in
  `plans/02-data-model.md`)
- Per-message read receipts (we use per-channel pointer)
- `User.last_seen_at` persistence (Redis ephemeral only)
- Voice / video calling
- Server-side history replay on WS reconnect (frontend re-fetches via
  REST + bumps last-seen pointer)
- WS message compression (perMessageDeflate) — defer until volume
  measured
- Notification preferences (everyone gets everything v1)
- Tests (per session policy)
- Migrations applied (per session policy)

---

## Verification

After implementation (assumes Postgres + Redis + uvicorn ASGI worker):

```bash
cd server
DJANGO_SETTINGS_MODULE=donna.settings .venv/bin/python -m django check
DJANGO_SETTINGS_MODULE=donna.settings .venv/bin/python -m django makemigrations
DJANGO_SETTINGS_MODULE=donna.settings .venv/bin/python -m django migrate

# Start uvicorn (replaces runserver for WS support)
.venv/bin/uvicorn donna.asgi:application --host 0.0.0.0 --port 8000 --reload

# SSE — confirm workspace fan-in
TOKEN=$(curl -sX POST localhost:8000/api/auth/signin \
    -d '{"email":"alice@acme.test","password":"S3curePass!"}' | jq -r .access)

curl -N -H "Authorization: Bearer $TOKEN" localhost:8000/api/v1/notifications/stream &
# In another shell — publish to user channel and workspace channel
.venv/bin/python -c "
import django; django.setup()
from donna.notifications.services import NotificationService, NotificationScope
from donna.users.models import User
from donna.workspaces.models import Workspace
u = User.objects.get(email='alice@acme.test')
ws = Workspace.objects.first()
NotificationService.create_alert(u, 'Personal', 'hello you')
NotificationService.create_alert(u, 'Workspace', 'team update',
    workspace=ws, scope=NotificationScope.WORKSPACE)
"
# SSE stream should emit BOTH events with workspace_id tag on the second.

# WebSocket — chat send + receive
# (use wscat or browser console)
wscat -c "ws://localhost:8000/ws/" -s "bearer.${TOKEN}"
< {"event": "connected", "user_id": "..."}
> {"action": "subscribe_channel", "channel_id": "<cid>"}
> {"action": "send_message", "channel_id": "<cid>", "body": "hi", "client_msg_id": "..."}
< {"event": "message.created", "channel_id": "<cid>", "message": {...}}

# Agent token streaming
wscat -c "ws://localhost:8000/ws/agent/<run_id>/" -s "bearer.${TOKEN}"
# Server emits {event: "agent.token", token: "..."} per chunk.

# Read pointer
curl -X POST localhost:8000/api/v1/chat/channels/<cid>/read-state/ \
    -H "Authorization: Bearer $TOKEN" \
    -d '{"message_id":"<mid>"}'
# WS subscribers in same channel receive {event: "read.advanced", user_id, message_id}.
```

---

## Open gaps (deferred, document only)

1. **Disconnect storms** — workspace event broadcast (e.g. "channel
   created") fans out to all members' WS connections. v1 sends one
   `group_send` per workspace group; Channels' `RedisChannelLayer`
   handles fan-out efficiently to ~1k members. Revisit at scale.
2. **Message ordering across WS disconnect** — client receives a
   message via WS, disconnects, reconnects, gets it again via REST
   history. Frontend deduplicates by `id`. Server doesn't replay WS
   events on reconnect; client REST-syncs.
3. **Rate limiting** — no v1. `send_message` and `typing` are unbounded
   per user. Add Redis token bucket per user when abuse appears.
4. **Channel layer high-availability** — `RedisChannelLayer` uses a
   single Redis instance. v2: switch to `channels_redis.pubsub` (newer
   backend) or shard across multiple Redis nodes when load demands.
5. **Presence across WS reconnect** — short blips show user as offline
   for up to TTL. Acceptable; add `last_seen_at` persistence later if
   "last seen X ago" UI is needed.
6. **DM creation race** — two users opening DM to each other
   simultaneously race on `get_or_create_dm`. Use unique constraint on
   sorted-member-pair to prevent duplicate Channel rows; service catches
   IntegrityError and re-fetches.
7. **Subprotocol JWT exposure** — token is in `Sec-WebSocket-Protocol`
   header (not URL), so it doesn't appear in access logs by default,
   but is visible to anyone with packet capture on plaintext WS.
   Production must enforce TLS (wss://).
8. **Channels' `group_send` is fire-and-forget** — if a WS client is
   disconnected mid-send, message is lost from that session. Acceptable
   given client re-syncs via REST on reconnect.
9. **Per-channel state caching in consumer** — to avoid hammering DB
   on every WS action, consumer caches authorization decisions per
   `(user, channel)`. Cache invalidated on `disconnect`. If user's
   channel membership changes mid-session, they may briefly retain
   stale access. Acceptable v1.
10. **Agent run lifecycle** — `agent-run-{run_id}` group should be
    cleaned up after run completes; `discard` from group + close the
    WS. Channels handles consumer cleanup; group entries are TTL'd by
    Redis automatically.
