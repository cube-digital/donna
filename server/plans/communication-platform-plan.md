---
type: plan
domain: chat-platform
status: draft
created: 2026-06-01
updated: 2026-06-01
sources:
  - "[[01 - Projects/08 - Donna AI/Architecture/_index|Architecture catalog]]"
  - "server/plans/02-data-model.md"
  - "server/plans/10-realtime-layer.md"
  - "server/plans/09-auth-and-notifications.md"
  - "server/plans/04-roadmap.md"
applied_in: []
related:
  - "[[01 - Projects/08 - Donna AI/Plans/Cortex Layer Plan|Cortex Layer Plan]]"
  - "[[01 - Projects/08 - Donna AI/Donna AI]]"
tags:
  - type/plan
  - domain/chat-platform
  - domain/realtime
  - status/draft
---

# Plan — Donna Communication Platform (Slack/Discord-grade)

A long-term, phased buildout of Donna's chat surface into a hybrid Slack + Discord communication platform with AI agents as first-class participants on every surface.

## Context

Donna's mission is a multi-tenant chat app with AI agents embedded in every channel. The product vision is a hybrid Slack + Discord experience: channels + DMs + threads + categories + reactions + mentions + search + (eventually) voice, all with AI as a first-class participant.

**Critical context — the foundation is more built than the roadmap doc suggests.** Current state on `main`:

- ✅ `Channel` model unified for channels + DMs (`kind=CHANNEL|DIRECT`, `visibility=PUBLIC|PRIVATE`)
- ✅ `ChannelMembership(role=ADMIN|MEMBER)`
- ✅ `Message(author_user XOR author_agent)` with edit/delete + DB CHECK constraint
- ✅ `ChannelReadState` (per-channel last-read pointer; per-message receipts deliberately rejected)
- ✅ `AgentSession` per channel (N:1, so multiple personas per channel without schema change)
- ✅ `Document` per channel (LWW PATCH)
- ✅ `WorkspaceMembership(role=OWNER|ADMIN|MEMBER|GUEST)` — `GUEST` modeled, unimplemented
- ✅ `ChannelService` as single mutation path used by both REST + WebSocket
- ✅ `ChatConsumer` with `subscribe_channel`, `unsubscribe_channel`, `send_message`, `edit_message`, `delete_message`, `typing`, `mark_read`, `open_dm`, `heartbeat`
- ✅ `AgentStreamConsumer` (consumer scaffold exists; producer worker missing)
- ✅ Presence via Redis TTL keys; JWT WS auth via `Sec-WebSocket-Protocol` subprotocol
- ✅ `Notification(scope=USER|WORKSPACE|USER_IN_WORKSPACE)` + SSE fan-in

**This plan is therefore not "build chat from scratch" — it's "harden the existing surface, then layer Slack/Discord parity features."** The naïve phase order (channels → DMs → groups → permissions) maps mostly to work that's already done, except for known TODOs and missing surfaces.

**Product target (confirmed)**: Hybrid Slack + Discord. Voice/video deferred to a final optional phase. Guests only (no cross-workspace Slack-Connect channels). AI agents are first-class on every chat surface — every phase explicitly handles the agent-author path.

---

## Phase 0 — SSE Auth Fix (blocker)

Without this, no notification-emitting phase can ship. `notifications_sse_view` is async; Django's `AuthenticationMiddleware` doesn't run DRF auth classes in async views, so `request.user` is anonymous. Frontend has a broken reconnect loop on 401.

**Approach**: SSE view decodes the JWT directly from `Authorization: Bearer …` using the same helper the WS subprotocol middleware already uses. Reuse `_resolve_user` in `server/donna/chat/auth.py`.

**Critical files**:
- `server/donna/notifications/api/v1/views.py` — fix anonymous-only SSE view
- `server/donna/chat/auth.py` — reuse `_resolve_user`
- `web/src/lib/sse.ts` — confirm reconnect loop handles late-arriving access tokens
- `server/plans/10-realtime-layer.md` — document the SSE auth pattern so it doesn't regress

---

## Phase 1 — Channels & DMs Hardening

Close the open TODOs on the surface that's already shipped.

**1.1 Channel admin can delete others' messages**
There's a literal `# TODO` in `server/donna/chat/consumers.py:226` AND a parallel one in `server/donna/chat/api/v1/views.py:198`. Both transports must check the same way. Extract `ChannelService._authorize_delete_message(user, message)` and call from REST and WS — don't fix one and forget the other.

**1.2 Private channel invite flow**
`ChannelService.emit_member_added` already exists (`services.py:286`) with **zero callers**. The invite endpoint is small:
- New service method `ChannelService.add_member(channel, user, added_by, role=MEMBER)`
- New endpoint `POST /api/v1/chat/channels/{cid}/members/` (admin adds, or self-join for public)
- Mirror `DELETE /api/v1/chat/channels/{cid}/members/{user_id}/` for kick/leave
- `GET /api/v1/chat/channels/{cid}/members/` listing
- **Dual broadcast**: existing `emit_member_added` fires on `chat-channel-{id}` (existing members), AND a new event `chat.channel.added.to_you` fires on `presence-user-{new_member_uid}` so the invitee learns about the new channel (mirrors the pattern `get_or_create_dm` already uses at `services.py:185`)

**1.3 Group DM creation**
`get_or_create_dm` is hardcoded to 2-member sets at `services.py:158-163`. Add a separate `create_group_dm(workspace, users)` method with exact-set-match semantics. Don't generalize the 2-member path — keep semantics explicit.

**1.4 DM workspace disambiguation**
Two users sharing N workspaces today get a non-deterministic DM channel. Change `get_or_create_dm` to require `workspace_id`. **Wire-format change** — WS `_action_open_dm` gains a `workspace_id` field. Roll out server-side first with default-to-old behavior when field is missing; deploy clients; remove default after rollout window. Bumps WS protocol version — declare it.

**1.5 Browse public channels without joining**
`ChannelListCreateView.get_queryset` (`views.py:52-60`) filters to memberships only. Add `?include_public=true` that ORs with `visibility=PUBLIC, workspace=request.workspace`. `ChannelDetailView.get_queryset` (`views.py:98-102`) needs the same OR. "Join" calls the new `POST /channels/{cid}/members/`. **Gate this server-side for GUEST role** (lands in Phase 2) — without that gating, guests see public channels they shouldn't.

**Critical files**: `server/donna/chat/services.py`, `server/donna/chat/api/v1/views.py`, `server/donna/chat/consumers.py`

---

## Phase 2 — Roles & Permissions

**Pulled before categories.** Categories are visual sugar; permissions unlock invites, guest accounts, audit, and gate every later phase's "who can do this" question. Three sub-phases — ship in order:

**2a — Workspace invite flow**
- `WorkspaceInvitation(token, email, role, expires_at, invited_by, accepted_at)` model
- `POST /api/v1/invitations/` (admin sends), `POST /api/v1/invitations/{token}/accept`, `GET /api/v1/invitations/{token}/` (preview)
- Tokens via `secrets.token_urlsafe`
- Email send via existing `EMAIL_BACKEND` config (`server/donna/donna/settings.py:194`)
- Both invite-by-email and invite-by-link variants

**2b — Guest role enforcement**
Concretely:
- Guests cannot create channels, cannot invite, cannot create/edit workspace settings
- Guests can only be added to specific private channels
- Every channel list query for guests filters to "only channels I'm a member of" — gates the Phase 1.5 browse-public feature

Touch every channel-query path; centralize the guest filter in `ChannelService.visible_channels(user, workspace)` so individual views don't drift.

**2c — Channel settings + audit log**
**Opinionated**: do not ship a Discord-style permission matrix. The existing `ChannelMembership.Role(ADMIN|MEMBER)` covers 95% of cases. For "members can pin", "members can add others", etc., add a `Channel.settings = JSONField(default=dict)` with documented keys. Defaults open; admins flip flags. One migration, no new permissions model.

`AuditLog(actor, action, target, workspace, context)` in a new `donna.audit` app (or `donna.core.models`). `AuditLog.record(...)` called from invite creation, role changes, channel settings changes, member kick.

**Critical files**:
- New: `server/donna/workspaces/models.py` adds `WorkspaceInvitation`
- New: `server/donna/workspaces/services.py` `InvitationService`
- Modified: `server/donna/chat/api/v1/views.py` (guest-aware filtering on every list query)
- New: `server/donna/audit/` app

---

## Phase 3 — Channel Categories (Discord-style)

Now genuinely small with permissions settled.

- `ChannelCategory(workspace, name, position, collapsed_default)` model (`UserAuditMixin` so we know who created it)
- Nullable `Channel.category = FK(ChannelCategory, on_delete=SET_NULL)`
- `POST/GET/PATCH/DELETE /api/v1/chat/categories/`
- Reorder action `POST /api/v1/chat/categories/reorder/` taking `[{id, position}, ...]` in one transaction
- Sparse integer scheme for `position` (100, 200, 300) so middle-insertion is cheap; re-pack when gaps shrink
- WS event `category.created/updated/deleted` on `workspace-{wid}-events` group (reuse `workspace_events_group` at `services.py:51`)

**Critical files**: `server/donna/chat/models.py`, `server/donna/chat/services.py`

---

## Phase 3.5 — Agent Runtime

Donna's diff vs. Slack/Discord is AI. The consumer scaffold exists; the producer doesn't. Without this, "mentions trigger an agent" (Phase 4) and "agent reactions" have nothing to call.

**Full architecture + target-state code:
[`docs/important-docs/00j - agent-implementation-reference.md`](../../docs/important-docs/00j%20-%20agent-implementation-reference.md)**
(phases A0–A1 of that handbook = this phase). Summary:

- **Agent layer under `donna/chat/agents/`** — agent-as-router (docupal `agents/legal` v10 pattern): `ConversationAgent` node emits tool calls XOR final text per turn; `ToolDispatcher` executes against a `ToolRegistry` built by `tools/factory.py`; plain-loop graph, max 6 rounds.
- **LLM via existing `donna/core/llm`** — `LLMProvider.chat(tools=registry.describe_all(), tool_choice="auto")`; native tool calling, no LangChain bridge.
- **Agent dispatch from `send_message`** — `transaction.on_commit → maybe_dispatch_agent(message)`: DM with an `AgentSession` → always; channel → on `@<agent-name>` body match (interim until Phase 4a `Mention` rows). Enqueues `run_agent_turn` (new `donna/chat/tasks.py`).
- **Turn serialization** — redis `SET NX EX` lock per channel (`agents/locks.py`); concurrent turns queue, edits apply serially.
- **Colleague-mode WS (decision 2026-06-12)** — agent emits the *same events through the same groups humans use*: typing start/heartbeat/stop on `chat-channel-{id}-typing`, final message as `chat.message.created` on `channel_group` with `author_agent` set. The `agent-run-{run_id}-tokens` group is demoted to optional panel UI (tool announce lines, config-gated token streaming).
- **Cortex read tools** — `cortex_query`/`read_entity`/`get_context` over an interim `CortexReadFacade` (ORM, heads-only); swapped for `CortexService` when the cortex Phase 4a API lands (swap isolated in `tools/factory.py`).
- **Memory backend** — `AgentSession.memory` JSONField rolling summary (00j §A3); read/write path designed for later store swap.

**Anti-loop guard**: never dispatch an agent run when the source `Message.author_agent` is set, regardless of mentions. Document this in `ChannelService.send_message`.

**Critical files**: `server/donna/chat/agents/` (new), `server/donna/chat/tasks.py` (new), `server/donna/chat/services.py`, `server/donna/chat/consumers.py`

---

## Phase 3.6 — Drafting Surface (conversation-locked documents)

Two people in a DM, a person + agent DM, or a channel co-produce ONE
document anchored to the conversation — membership churn never forks
it (Cowork semantics). Full design + code: [`00j §A2`](../../docs/important-docs/00j%20-%20agent-implementation-reference.md).

- **`Document` gains draft lifecycle** (decision 2026-06-12: extend, don't add a model): `status (drafting|finalized|abandoned)`, `version`, `target_doc_type` (cortex `DocType` vocab), `finalized_entity_id`; partial unique `(channel) WHERE status='drafting'` — the lock.
- **Draft tools** (registry-gated per surface): `create_draft`, `read_draft`, `update_draft_section` (select_for_update + optimistic `expected_version`), `finalize_draft`.
- **Agent is the single writer** — humans direct via messages; turn lock serializes edits. No CRDT/OT in v1.
- **Finalize = the only door into cortex silver**: `linter_check` dry-run → `create_entity(type="doc", author="agent", source="donna://channel/<id>/draft/<id>")` → draft frozen, supersession chain handles future revisions. Gated on the cortex Phase 4a API.
- WS: `chat.document.updated` events on `channel_group`.

**Critical files**: `server/donna/chat/models.py` (Document migration), `server/donna/chat/agents/tools/draft_tools.py` (new), `server/donna/chat/agents/nodes/drafter.py` (new)

---

## Phase 4 — Engagement Primitives

Three sub-phases. Mentions, then threads, then reactions.

**4a — Mentions**
- `Mention(message, mentioned_user, mentioned_agent, mentioned_channel)` with unique constraint per `(message, mentioned_*)` — denormalized, not a JSON column on `Message`, because "all my mentions in workspace X" must be indexable
- Mention parser utility extracts `@user-handle`, `@channel-slug`, `@<agent-name>` from message body
- Called from `ChannelService.send_message` AND `edit_message`
- On edit: diff old vs new mention set; notify added mentions only; don't delete notifications already delivered for removed mentions
- Mention notification via existing `NotificationService.create_alert(scope=USER, workspace=...)`
- When `mentioned_agent` is non-null, dispatch agent run via Phase 3.5

**4b — Threads**
- `Message.parent_message = FK('self', on_delete=SET_NULL, null=True)`
- Denormalized `Message.thread_root_id` (FK to original parent) + `Message.thread_reply_count` (kept in sync inside the same transaction as reply send)
- WS events: `thread.reply` on `chat-channel-{cid}` (so all channel members see counter bump) + new `thread-{root_id}` group for users watching the thread
- Agent threads work for free — `author_agent` already supported; ensure the anti-loop guard from Phase 3.5 also applies in threaded replies

**4c — Reactions**
- `Reaction(message, user, agent, emoji)` with the same author-XOR CHECK constraint pattern as `Message`
- `POST /messages/{id}/reactions/` ({emoji}) and `DELETE /messages/{id}/reactions/{emoji}/`
- WS events `reaction.added` / `reaction.removed` on `chat-channel-{cid}`
- Agents can react — useful for "I read this" / "I'm processing this" UX

**Refactoring note**: `ChannelService.send_message` will grow. Keep the body small — delegate to `_extract_and_record_mentions`, `_update_thread_root`. `_serialize_message` should be the single point where mentions, thread metadata, and reactions get added to event payloads (don't duplicate serialization across REST + WS).

**Critical files**: `server/donna/chat/models.py`, `server/donna/chat/services.py`, `server/donna/chat/consumers.py`

---

## Phase 5a — Attachments, Pinning, Link Previews

- `Attachment(message, file, mime, size, thumbnail, width, height)` using existing `default_storage` (storage backend is already env-pluggable via `DONNA_STORAGE_BACKEND` per `settings.py:209-253`)
- Key convention `messages/{workspace_id}/{channel_id}/{message_id}/{filename}` (mirrors the integrations pattern)
- Upload pattern: direct upload for v1; presigned URLs for large files later
- `generate_thumbnail(attachment_id)` Celery task (Pillow) — defer for files > Nmb until on-demand
- Link unfurling: detect URLs in `send_message`, dispatch `unfurl_link(message_id, url)` task that fetches OG tags + caches in `LinkPreview(url, title, description, image_url, cached_at)`. WS event `message.unfurled` on update
- `PinnedMessage(channel, message, pinned_by)` + endpoints; "members can pin" governed by Phase 2c's channel settings JSON

**Cost controls before launch** (this is where Donna can get expensive fast): per-workspace `max_attachment_size`, per-workspace `max_storage_bytes`, file size hard cap. Reuse `default_storage` size-checking.

**Critical files**: `server/donna/chat/models.py`, new `server/donna/chat/tasks.py`, `server/donna/chat/api/v1/views.py`

---

## Phase 5b — Search & Discovery

- Postgres `SearchVectorField` on `Message.body` (use `django.contrib.postgres.search` — no Elasticsearch in v1) + GIN index
- Update via `save()` override or DB trigger
- `Channel.name`/`Channel.topic` indexed similarly for channel-name search
- `GET /api/v1/chat/search?q=…&channel=…&author=…&after=…&before=…&kind=message|channel`
- **Permissions on search**: workspace-scoped + must respect channel membership (results filtered to "channels I can see"). Phase 2b's `visible_channels` helper pays off here
- Thread context in results: a match in a reply must surface as "matched a reply in thread X" with the right deep link
- Integration content (`DeliveryPackage`) ingested into search later — separate effort

**Critical files**: `server/donna/chat/models.py`, `server/donna/chat/api/v1/views.py`

---

## Phase 6 — Notifications & Focus

- `NotificationPreference(user, workspace, channel?, mute_until, dnd_schedule, keyword_alerts)` — workspace defaults + per-channel overrides
- Aggregate unread count: `GET /api/v1/chat/unread-counts/` returns `{channel_id: count, dm_id: count, mention_count}` for active workspace (powers sidebar badges)
- DM read receipts (opt-in, 2-member DMs only): extend `Message` with `delivered_at`, `read_at_for_peer`. Group DMs get "Seen by N/M" derived from `ChannelReadState` instead — no per-message receipts there (matches the explicit rejection in `02-data-model.md`)
- Email digests via scheduled Celery beat task
- Web push (VAPID) — new `PushSubscription(user, endpoint, p256dh, auth)` model. Defer native mobile

Per-user agent prefs ("don't notify me when agent posts") fit here.

**Critical files**: `server/donna/notifications/models.py`, `server/donna/notifications/services.py`

---

## Phase 7 — Voice & Video (Optional, Deferred)

Mark this phase as optional in the roadmap. Treat as a separate project when committed.

- **LiveKit** over Daily — open-source, self-hostable (aligns with Donna's self-hosting story per `server/plans/06-deployment-and-self-hosting.md`)
- **Huddles over voice channels**: ephemeral call-in-channel (Slack-style) uses existing `ChannelMembership` for permission; no new resource type
- New `VoiceConsumer` (`/ws/voice/{channel_id}/`) issues LiveKit access tokens server-side
- Backend stays minimal — token issuance + member list; LiveKit handles SFU + TURN/STUN

---

## Phase 8 — Operational Hardening (Cross-Cutting)

Not a single phase — interleave a mini-pass after each major phase. Backbone is the 10 deferred items in `server/plans/10-realtime-layer.md:594-630`:

1. **Rate limits** (highest priority pre-launch) — Redis token bucket per user for `send_message`, `typing`, `mark_read`
2. **WS reconnect replay** — server emits per-channel sequence numbers; client gap-fills via REST `GET /channels/{id}/messages?after_seq=…`
3. **Disconnect storms** — switch to `channels_redis.pubsub` backend or shard for workspaces >1k members
4. **Channel layer HA** — Redis Sentinel or Cluster
5. **Authz cache invalidation** — `consumers.py:309-323` caches `(user, channel)` membership; needs invalidation on `chat.channel.member.added/removed`
6. **DM creation race** — model-level unique constraint on sorted member-pair hash
7. **TLS enforcement** in production middleware (wss:// only)
8. **Observability** — structured logs for WS frames; Prometheus counters per consumer
9. **Backpressure** — when `group_send` queue fills, drop oldest typing events first
10. **Agent run group cleanup** — explicit `discard` rather than relying on Redis TTL

**Critical files** (cross-cutting): `server/donna/chat/consumers.py`, `server/donna/core/middleware.py`, new `server/donna/core/rate_limit.py`

---

## Phase Dependencies

```
Phase 0 (SSE fix) ──► every phase that emits Notifications
       │
       ▼
Phase 1 ──► Phase 2 ──► Phase 1.5 browse becomes safe to ship
       │      │
       │      ▼
       │  Phase 3 (categories) — independent of later phases
       │      │
       │      ▼
       │  Phase 3.5 (agent runtime) ──► Phase 4 mentions
       │      │
       ▼      ▼
       Phase 4 (mentions/threads/reactions) ──► Phase 5b search context, Phase 6 prefs
              │
              ▼
       Phase 5a (attachments) ──► Phase 5b (attachment search)
              │
              ▼
       Phase 5b (search)
              │
              ▼
       Phase 6 (notifications/focus)
              │
              ▼
       Phase 7 (voice — independent, anytime after Phase 2)

Phase 8 (operational hardening) — interleaved throughout
```

**Hidden dependencies to keep top-of-mind**:
- Phase 0 SSE fix blocks Phase 4 mention notifications (they route via SSE)
- Phase 2b Guest enforcement must precede Phase 1.5 browse-public going live
- Phase 5a attachments depend on Phase 2c channel settings (governance flags)
- Phase 3.5 agent runtime must land before Phase 4 mention triggers can actually dispatch

---

## Reuse Map (don't reinvent)

| Where | Existing utility to lean on |
|---|---|
| Phase 0 | `donna/chat/auth.py:_resolve_user` for JWT async validation |
| Phase 1 | `ChannelService._broadcast`, `emit_member_added` (defined, zero callers), `presence-user-{uid}` group pattern |
| Phase 2 | `WorkspaceMembershipService` (atomic role transitions), permission classes at `workspaces/api/v1/views.py:32-80`, `EMAIL_BACKEND` |
| Phase 3 | `workspace_events_group` helper at `services.py:51` |
| Phase 3.5 | `AgentStreamConsumer` (consumer ready, producer missing), `AgentSession.memory` JSONField |
| Phase 4 | `NotificationService.create_alert`, `_broadcast`, `channel_group`; centralize all payload extension through `_serialize_message` |
| Phase 5a | `default_storage` (env-pluggable per `settings.py`), existing Celery beat infra |
| Phase 5b | `django.contrib.postgres.search` (Postgres-native — no Elasticsearch) |
| Phase 6 | `NotificationService.set_seen`, `NotificationManager.unread_for_user`, `ChannelReadState` for "Seen by N/M" |
| Phase 7 | LiveKit; reuse `presence-user-{uid}` for call state |
| Phase 8 | `redis_manager`, `structlog` from `core/logging.py`, existing Channels group naming |

---

## Top 5 Risks

1. **DM workspace disambiguation is a wire-format change** — every WS client breaks if rushed. Default-to-old when field missing; deprecate; remove default after rollout window
2. **Channel admin delete TODO has two call sites** — REST and WS will diverge if only one is patched. Extract `_authorize_delete_message` and call from both
3. **Mention parsing on edits = double notifications** — diff old vs new mention set; never re-notify users who were in both sets
4. **Agent reply loop** — `@donna` triggers agent, agent reply contains text that looks like a mention, infinite loop. Never dispatch agent runs when source `Message.author_agent` is set, regardless of mentions
5. **Phase 5a attachment cost** — without per-workspace storage caps and file size limits, a few users blow up the storage bill. Ship caps before launch

---

## Documentation Discipline

Per `CLAUDE.md`: when phases land, update `server/plans/*.md` in the same commit:
- Phase 0 → `10-realtime-layer.md` (SSE auth pattern)
- Phase 1, 2, 3 → `02-data-model.md` (new models, retiring "Open" items)
- Phase 2, 4 → `03-conventions-and-api.md` (audit log, mention payload shape)
- Phase 8 → `10-realtime-layer.md` (close "Open gaps" entries as they land)
- Phase 4–7 each kicks off → `04-roadmap.md` status flip

The roadmap doc is currently stale — Phase 0–2 work is done but listed as todo. Reconcile during Phase 0.

---

## Verification

After each phase:

1. **Migrations**: `DJANGO_SETTINGS_MODULE=donna.settings .venv/bin/python -m django makemigrations && migrate`
2. **Django check**: `... -m django check`
3. **Manual e2e**: start the full stack (`cd server && docker compose up --build`), open the web client, exercise the new surface end-to-end. For chat surfaces, open two browser sessions in different workspaces and confirm:
   - REST round-trip (create, list, edit, delete)
   - WS event delivery (subscribe, receive, ack)
   - Permission gating (try as MEMBER, ADMIN, GUEST per Phase 2)
   - Agent-author path where applicable (Phase 3.5+)
4. **SSE delivery** (Phase 0 onwards): notification fires → arrives in browser within 1s
5. **Rate limit** (Phase 8 mini-passes): script a flood of `send_message` calls; confirm 429 / throttle behavior

For visible UI work, use the preview workflow — start the dev server, navigate, snapshot, share screenshots for sign-off. Don't claim a UI change works without seeing it render.
