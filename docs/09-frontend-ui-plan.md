# 09 · Frontend / UI plan

> Status: implemented (v1). See `web/` for the running code.
> Companion to [`server/plans/`](../server/plans/) which describes the backend.

## Context

A design bundle was exported from claude.ai/design ("DonnaAI") — a React/JSX
prototype of a team-chat product reimagined around AI teammates. The Django
backend at `server/` already implements: email + Google auth, workspaces,
chat (Channel/Message/AgentSession + Django Channels WebSocket at `/ws/`),
notifications (DB + SSE at `/api/v1/notifications/stream`), and the
integration framework with Gmail / Drive / Fathom / Notion / WhatsApp
connectors.

This plan implements the **backend-backed surfaces** of the design (channel
view, personal chat, sidebar, composer, integrations, notifications) in a
new shared `web/` React app, then wires the Electron `desktop/` shell to
wrap that build. Profile, Search, Workspace overview, and Empty-channel
views are stubbed as "Coming soon" placeholders reachable from the nav so
the design language is preserved without scope-creeping the backend.
Agent runs render as messages with a `kind:"agent-run"` metadata shape —
no backend schema change. The design's Vault concept (archival surface +
bottom dock) was removed entirely from this build — the underlying
backend model isn't built and Vault isn't on the near roadmap, so keeping
the placeholder caused more confusion than it preserved fidelity.

Pixel fidelity comes from **Tailwind CSS** with the design's OKLCH tokens
wired in as CSS variables and exposed under named Tailwind colour utilities.
Every component is authored with Tailwind utility classes inline in JSX —
no per-component CSS files. Exact pixel sizes that don't fit the default
scale (the 56 / 252 / 1fr / 320 columns, the 44 px top-bar row, specific
radii like 7 px and 10 px) are expressed via Tailwind's arbitrary value
syntax (e.g. `grid-cols-[56px_252px_1fr_320px]`, `rounded-[10px]`).
A handful of effects that can't be cleanly expressed as utility chains
(the agent-avatar radial gradient that needs a per-instance `--hue`, the
animated pulse ring, the streaming `...` dots, the agent-run card
background) live as helpers in `@layer components` inside `global.css`.

## Architecture

```
donna/
├── web/                       # Vite + React 18 + TS + Tailwind, the canonical UI
│   ├── src/
│   │   ├── main.tsx, App.tsx, vite-env.d.ts
│   │   ├── styles/            # global.css (Tailwind directives + @layer base/components),
│   │   │                      # tokens.css (OKLCH design tokens, theme-light overrides)
│   │   ├── api/               # typed clients: auth, chat, workspaces, notifications, integrations
│   │   ├── lib/               # ws.ts, sse.ts, auth-storage.ts, hueForAgent.ts
│   │   ├── state/             # zustand stores: auth, workspace, channels, messages, presence, notifications, integrations
│   │   ├── components/
│   │   │   ├── Shell/         # AppShell, WsRail, TopBar, Sidebar, RightRailSlot
│   │   │   ├── Ui/            # Ic (26 icons, namespaced + named), Av (human/agent avatar)
│   │   │   ├── Channel/       # Channel view internals: ChannelHeader, Message, AgentRunCard, Composer
│   │   │   └── RightRail/     # Sections + IntegrationModal
│   │   ├── views/             # Auth, WorkspacePicker, OAuthReturn, Channel, Personal, ComingSoon
│   │   └── types/             # shared TS types mirroring backend serializers
│   ├── index.html             # loads Geist + Geist Mono
│   ├── tailwind.config.ts     # OKLCH var-backed colour palette + keyframes + animations
│   ├── postcss.config.js      # tailwindcss + autoprefixer
│   ├── vite.config.ts         # /api + /ws proxy to http://localhost:8000
│   ├── tsconfig.json, package.json, .env.example
├── desktop/                   # Electron shell that wraps the web build
│   ├── src/main.ts            # loads http://localhost:5173 in dev, web/dist in prod
│   └── package.json           # adds concurrently + wait-on for `npm run start:dev`
├── design-source/             # extracted design tarball — original JSX/CSS source kept for reference
└── server/                    # backend; unchanged by this plan
```

Backend remained untouched. All UI code is in `web/`, with a single-file
change in `desktop/src/main.ts` and a few new npm scripts wiring the build
order.

## Implementation surfaces

| Phase | What landed | Key files |
|---|---|---|
| 1. Scaffold | Vite + React + TS + Tailwind (with PostCSS + Autoprefixer), Geist fonts inlined, OKLCH tokens, Tailwind theme mapping every design colour | `vite.config.ts`, `tsconfig.json`, `tailwind.config.ts`, `postcss.config.js`, `src/styles/*` |
| 2. UI primitives | 26-icon set + Avatar with `--hue` CSS-var trick for the AI gradient | `src/components/Ui/Ic.tsx`, `Av.tsx`, `src/lib/hueForAgent.ts` |
| 3. Auth shell | Tabbed sign-in / sign-up + Google button, sign-up auto-signin, JWT persistence + refresh interceptor in `client.ts` | `src/views/Auth.tsx`, `src/api/auth.ts`, `src/lib/auth-storage.ts` |
| 4. App shell + workspace | 4-col × 2-row grid (`AppShell`), `WsRail`, `TopBar`, `Sidebar`, `RightRailSlot` context + outlet, workspace picker with create form | `src/components/Shell/*`, `src/views/WorkspacePicker.tsx`, `src/state/workspace.ts` |
| 5. Channel view | WS subscribe per channel, day-divider grouping, near-bottom auto-scroll, load-older on scroll-up with anchor restore, debounced `mark_read`, typing indicators via dedicated `presence` store | `src/views/Channel.tsx`, `src/components/Channel/*`, `src/lib/ws.ts`, `src/state/{messages,presence}.ts` |
| 6. Composer | Optimistic insert with `client_msg_id` dedupe through WS echo, `/` global focus shortcut, throttled `typing` emit | `src/components/Channel/Composer.tsx` |
| 7. Agent runs | Client-side classification of agent-authored messages whose body parses as JSON `{kind:"agent-run",…}` (no schema change required) | `src/state/messages.ts`, `src/components/Channel/AgentRunCard.tsx` |
| 8. Personal | Two-col history + chat; identity derived from first observed `author_agent` in the channel; backed by DM-kind channels until backend grows an agent-peer model | `src/views/Personal.tsx` |
| 9. Right rail | Context-aware: Channel publishes Progress / Docs / Context / Memory; Personal publishes Donna Today + Memory; ContextSection fetches per-`live` provider `last_synced_at` with a per-slug cache | `src/components/RightRail/RightRail.tsx` |
| 10. Notifications | SSE client over `fetch` + ReadableStream (EventSource can't send Bearer headers); zustand store with optimistic mark-read/all; bell badge in `TopBar` | `src/lib/sse.ts`, `src/api/notifications.ts`, `src/state/notifications.ts` |
| 11. Integrations | Provider list in ContextSection + modal with popup-based OAuth, `last_synced_at` humanized, disconnect with `window.confirm`, OAuth error surfaced via `donna.oauth.return` postMessage | `src/api/integrations.ts`, `src/state/integrations.ts`, `src/components/RightRail/IntegrationModal.tsx`, `src/views/OAuthReturn.tsx` |
| 12. Electron wrap | `BrowserWindow` 1440×900 with hidden traffic-light, loads `http://localhost:5173` in dev or `web/dist/index.html` in prod; new `start:dev`, `build:prod`, `start:prod` scripts | `desktop/src/main.ts`, `desktop/package.json` |

## Tailwind theme

The design tokens stay as OKLCH CSS variables in `src/styles/tokens.css`;
Tailwind's `theme.extend.colors` maps every variable to a named utility:

| Token | Tailwind |
|---|---|
| `--bg-0 .. --bg-4` | `bg-bg-0 .. bg-bg-4` (and `text-`, `border-`, etc.) |
| `--text-0 .. --text-4` | `text-text-0 .. text-text-4` |
| `--border`, `--border-strong` | `border-border-soft`, `border-border-strong` |
| `--ai`, `--ai-dim`, `--ai-deep`, `--ai-bg`, `--ai-glow` | `ai`, `ai-dim`, `ai-deep`, `ai-bg`, `ai-glow` |
| `--ok`, `--warn`, `--danger` | `ok`, `warn`, `danger` |
| `--r-sm`, `--r`, `--r-lg`, `--r-xl` | `rounded-sm`, `rounded`, `rounded-lg`, `rounded-xl` |
| `--shadow-1`, `--shadow-2` | `shadow-soft`, `shadow-elevated` |

Fonts: `font-sans` (Geist), `font-mono` (Geist Mono).

Animations defined as Tailwind keyframes:
`animate-pulse-ring` (agent avatar ring while streaming),
`animate-led-blink` (running-state LED), `animate-dots-pulse`
(streaming thought "..."), `animate-spin-360` (task spinner).

Theme switching is class-based — `body.theme-light` swaps every variable
in `tokens.css`. Tailwind's built-in `dark:*` prefix is NOT used because
dark is the design's primary, not its alternate. The single `--ai-h`
variable controls the AI hue family; change it once and every AI moment
updates in lockstep.

### `@layer components` helpers in `global.css`

The four effects that can't be expressed as utility chains:

- `.av-agent-gradient` (+ `-lg`, `-xl`) — radial gradient + glow on agent
  avatars, reads `--hue` set inline per-instance.
- `.av-pulse-ring` — pulsing ring around an agent avatar mid-stream
  (`::after` + `animate-pulse-ring`).
- `.run-card-bg` — agent-run card linear-gradient body that's hue-aware
  and theme-light aware.
- `.thought-dots` — animated three-dot ellipsis after a thought line
  (`::after` content + steps animation).

Everything else is utility classes inline in JSX.

## Critical backend contracts the frontend honors

### Auth + envelope

Every DRF response goes through
[`donna.core.renderers.StandardJSONRenderer`](../server/donna/core/renderers.py),
wrapping the payload as `{data, meta, message, code}`. Simplejwt's
`TokenObtainPairView` is a DRF `APIView` and IS wrapped, despite first
appearances. `apiFetch` in `web/src/api/client.ts` unwraps the envelope by
default; callers that need the raw response (rare) opt in via `raw: true`.
**Do not pass `raw: true` for any DRF endpoint** — it was the source of the
"signin returns undefined token" footgun (see "Known quirks" below).

### Workspace header

[`WorkspaceMiddleware`](../server/donna/workspaces/middlewares.py) reads
`X-Workspace-Id` on every request **except** the allow-listed paths:
`/admin`, `/swagger`, `/api/auth`, `/health`, `/api/v1/workspaces`,
`/favicon.ico`, `/app`, `/api/v1/notifications/stream`, `/ws`, plus the
`/webhook/callback` and `/oauth/callback` suffixes. The header is attached
automatically by `apiFetch` from the workspace store; callers don't set it
manually.

### Pagination

Donna does NOT use DRF's default pagination. The renderer puts page rows
directly in `data` and pagination metadata (total, page, size, pages,
links) in `meta`. The frontend's list APIs (`listWorkspaces`,
`listChannels`, `listNotifications`, `getMessages`) all use a tolerant
`Array<T> | Paginated<T>` type so a future shape change wouldn't crash
them.

### WebSocket

Single endpoint at `/ws/`. JWT is shipped via the
`Sec-WebSocket-Protocol` subprotocol list as `["bearer", "<jwt>"]` — NOT a
query param. See [`server/donna/chat/auth.py`](../server/donna/chat/auth.py)
for the subprotocol middleware. The client at `web/src/lib/ws.ts` is a
singleton with exponential reconnect (1s → 30s cap), a 25s heartbeat, and
automatic resubscription to wanted channels on reconnect.

Inbound actions: `subscribe_channel`, `unsubscribe_channel`, `send_message`
(carries `client_msg_id` for dedupe), `edit_message`, `delete_message`,
`typing`, `mark_read`, `open_dm`, `heartbeat`.

Outbound events: `connected`, `subscribed`, `unsubscribed`,
`message.created`, `message.updated`, `message.deleted`, `typing`,
`presence`, `channel.created`, `channel.member.added`, `read.advanced`,
`dm.opened`, `error`.

### Notifications API

Reworked in commit `d17a8d7` from `POST /mark-read` + `POST /mark-all-read`
to a single `PATCH /api/v1/notifications/seen/` with body
`{seen: boolean, ids?: string[]}`. The frontend's `markRead` and
`markAllRead` are thin facades over the same endpoint.

### Integrations OAuth flow

Frontend calls `POST /api/v1/integrations/<slug>/connect/`, opens the
returned `authorize_url` in a popup. After the upstream redirect, the
backend's
[`ProviderOAuthCallbackView`](../server/donna/integrations/api/v1/oauth.py)
302s to a frontend route `/oauth/return?status=ok|error&slug=<vendor>&detail=<msg>`.
[`OAuthReturn.tsx`](../web/src/views/OAuthReturn.tsx) `postMessage`s a
`donna.oauth.return` event to `window.opener` so the integrations modal
can refresh, then closes the popup.

## Known quirks worth documenting

1. **Envelope unwrap on auth endpoints** — simplejwt's response IS
   enveloped (it goes through DRF's renderer). The original auth client
   passed `raw: true` and silently lost the tokens. Fixed; the comment in
   `web/src/api/auth.ts` documents this explicitly so future contributors
   don't repeat it.

2. **Pagination shape** — backend uses `data: [...rows...], meta: {...}`,
   not DRF default `results: [...]`. List APIs tolerate both shapes for
   future-proofing.

3. **WebSocket auth via subprotocol** — browsers can't set custom headers
   on `new WebSocket(...)`. The portable way to ship a JWT is the
   subprotocol list. The backend accepts either `["bearer", "<jwt>"]` or
   `["bearer.<jwt>"]`; the frontend uses the two-element form.

4. **SSE auth via fetch + ReadableStream** — `EventSource` can't set
   custom headers either, so the notifications SSE client uses `fetch`
   with `Authorization: Bearer <jwt>` and parses the `text/event-stream`
   body manually. (Note: the backend SSE view currently 401s because it
   doesn't validate JWTs in the async-view path — see "Open issues".)

5. **Local dev port mapping** — docker-compose maps Postgres to
   `host:5551 → container:5432` and Redis to `host:6667 → container:6379`.
   The `server/.env` file is read by BOTH docker-compose (for
   interpolation) and Django (for runtime config). If you put
   `DATABASE_PORT=5551` (the host port) in `.env`, compose will use it as
   the CONTAINER port too and break the mapping. Workaround: keep
   `DATABASE_PORT=5551` in `.env` (Django wants the host-side port) and
   pass `DATABASE_PORT=5432 REDIS_PORT=6379 docker compose up -d ...` so
   the shell override wins for the compose call.

6. **Workspace name on hard refresh** — `WorkspacePicker` was the only
   place that fetched the workspace list, so a deep-link reload left the
   sidebar header showing "Workspace" instead of the real name. Fixed by
   re-fetching the list in `AppShell`'s bootstrap effect.

## How to run

### Backend

```bash
cd server
[ -f .env ] || cp .env.example .env
DATABASE_PORT=5432 REDIS_PORT=6379 docker compose up -d database cache
docker compose ps                                # wait for "healthy"
DJANGO_SETTINGS_MODULE=donna.settings .venv/bin/python -m django migrate
DJANGO_SETTINGS_MODULE=donna.settings .venv/bin/python -m django runserver
# in another terminal:
.venv/bin/celery -A donna worker --loglevel=info
```

### Frontend (browser)

```bash
cd web
npm install              # one-time
npm run dev              # http://localhost:5173
```

### Frontend (Electron)

```bash
cd desktop
npm install              # one-time
npm run start:dev        # spawns web dev server + Electron
# or for a production build:
cd .. && cd web && npm run build && cd ../desktop && npm run start:prod
```

## Verification checklist

1. **Auth flow** — sign up via the form; confirm JWT in localStorage;
   sign-in screen disappears.
2. **Workspace** — pick or create a workspace; confirm `X-Workspace-Id`
   is sent on every subsequent request.
3. **Realtime** — open two browser tabs as different users in the same
   channel; messages cross within ~200ms; typing indicator surfaces.
4. **Notifications** — trigger any backend action that writes a
   `Notification` (e.g. add workspace member); bell badge increments
   without a refresh.
5. **Integrations** — open Context section in the right rail; click
   Connect on a provider; complete OAuth in popup; row flips to `live`.
6. **Stub routes** — click the Files icon in `WsRail` (or any other
   placeholder); `ComingSoon` renders inside the existing 4-column shell
   (no broken layout).
7. **Hard refresh** — F5 on a channel route; you stay signed in, the
   workspace name resolves correctly, the channel re-subscribes.
8. **Electron wrap** — `cd desktop && npm run start:dev`; the Electron
   window shows the same UI as the browser.

## Open issues / follow-ups

- **SSE 401** — `/api/v1/notifications/stream` returns 401 because the
  async view doesn't decode the JWT (Django's `AuthenticationMiddleware`
  doesn't run DRF auth classes). Backend fix: decode the token in
  `notifications_sse_view` directly or accept a `?token=` query param.
  Frontend follow-up: cap reconnect attempts on consecutive 401s so the
  client doesn't loop.
- **`AgentRun` model** — agent runs are currently encoded as JSON-bodied
  messages classified client-side. When a real `AgentRun` model lands,
  lift the rule into a serializer field and delete the parse.
- **Real user display names in typing indicator** — currently shows
  `user-<id-slice>` stubs; unblocks when a `/api/v1/users/<id>/`
  endpoint lands.
- **Streaming `.run-thought` on non-card agent messages** — the design
  has an animated-dots row for messages mid-stream; deferred until the
  backend emits incremental `agent.token` events to the messages
  subscriber.
- **Profile, Search, Workspace overview, Empty channel** — all
  stubbed as `ComingSoon`. The right rail registration pattern via
  `useRightRail` is already in place so each view drops in cleanly when
  built.
- **Project grouping of channels** — no Project model on the backend
  yet; sidebar renders channels flat for v1.

## Design source provenance

The original prototype lives at `design-source/project/` (extracted from
the Anthropic Design tarball at
`/v1/design/h/sYY2PnsEs-nMS9CEJu8niw`). The CSS files are the canonical
reference for token values and class names; the JSX files document the
intended behaviour. We recreate the visuals in React against the same
class names rather than copying the prototype's component structure.

## Decisions worth remembering

- **Tailwind utilities inline in JSX** — every component is styled with
  Tailwind classes directly in JSX, with the design's OKLCH tokens
  exposed as named colour utilities (`bg-bg-1`, `text-ai`, etc.). The
  initial CSS port from the design was a useful intermediate
  (kept under `design-source/project/styles.css` as a reference), but
  the production code uses Tailwind throughout. The build output is
  ~22 KB CSS gzipped, vs ~45 KB for the original verbatim port —
  Tailwind's tree-shaking is a meaningful win on top of the
  consistency benefit. Pixel-exact values that don't fit Tailwind's
  default scale are expressed via arbitrary value syntax
  (`grid-cols-[56px_252px_1fr_320px]`, `rounded-[10px]`,
  `text-[13.5px]`). Effects that can't be expressed as utilities
  (per-instance hue gradient, pulsing ring, streaming dots,
  agent-run card background) live as `@layer components` helpers in
  `global.css`.
- **Zustand over Redux/RTK Query** — small stores
  (auth/workspace/channels/messages/presence/notifications/integrations)
  with no global event bus. Simpler than wiring middleware for the
  single hot path (chat) which already has its own WS singleton.
- **React Router 6 with a flat route gate** — three states (no auth, no
  workspace, full app) handled by a top-level `<App/>` rather than
  nested layouts. Easier to reason about which views are reachable from
  which state.
- **No `createPortal` for the right rail** — the rail is a grid child of
  the app shell, so a portal would detach it from the layout. Instead,
  a context-based slot (`useRightRail` + `<RightRailOutlet/>`) lets
  views declare their right-rail content without rendering through
  React's portal API.
