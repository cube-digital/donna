# Donna UI Kit — workspace settings + profile

Plug-and-play HTML/CSS/React for the workspace settings pages and the profile drawer,
in the Donna design language.

## What's inside

```
donna-ui-kit/
├── index.html        ← open this. All pages, working left-nav, live toggles.
├── icons.svg         ← inline SVG sprite (29 icons, no icon-font, no CDN)
├── css/donna.css     ← design tokens + every component class (the whole system)
└── react/
    ├── Icon.jsx              inline SVG icons  <Icon name="users" />
    ├── SettingsLayout.jsx    shell: sub-nav + header (role-gated)
    ├── GeneralPage.jsx       name / slug / primary domain / danger zone
    ├── MembersPage.jsx       roster, role dropdowns, remove, pending invites
    ├── InvitationsPage.jsx   status filters, resend / revoke / copy-link / re-invite
    ├── ConnectionsPage.jsx   connected vs available, shows cortex file paths
    ├── AgentsPage.jsx        agent card (model / tools / scope) + add agent
    ├── ProfileDrawer.jsx     final profile style
    ├── WorkspaceSettings.jsx example wiring — swap mock data for your API
    │
    ├── ChannelPanel.jsx         tabbed channel drawer (About/Members/Agents/Settings)
    ├── ChannelAboutTab.jsx      topic, created-by, files, pinned
    ├── ChannelMembersTab.jsx    add-from-workspace picker + invite-by-email + roles
    ├── ChannelAgentsTab.jsx     channel-resident agents (@handle) + cortex scope
    ├── ChannelSettingsTab.jsx   name, topic, public/private, archive, delete
    └── ChannelPanelExample.jsx  example wiring (endpoints noted inline)
```

## Use it in React

```jsx
import "donna-ui-kit/css/donna.css";
import WorkspaceSettings from "donna-ui-kit/react/WorkspaceSettings";
import ProfileDrawer from "donna-ui-kit/react/ProfileDrawer";

<WorkspaceSettings role="owner" onBack={() => nav("/")} />
<ProfileDrawer user={me} onSave={saveProfile} onSignOut={signOut} />

import ChannelPanel from "donna-ui-kit/react/ChannelPanel";
<ChannelPanel channel={ch} members={m} candidates={c} agents={a} isChannelAdmin />
```

Components are presentational — every action is a prop (`onInvite`, `onRoleChange`,
`onRevoke`, `onConnect`, …). Wire them to your endpoints:

| UI | endpoint |
|---|---|
| Members list / role change / remove | `/api/v1/members/` |
| Invitations (create, resend, revoke) | `/api/v1/workspaces/invitations/` |
| Workspace name / slug / domain / delete | `/api/v1/workspaces/` |
| Channel members (add / remove) | `/chat/channels/<id>/members/` |
| People to add (not yet in channel) | `/chat/channels/<id>/mention-candidates/` |
| Install / uninstall channel agent | `/chat/channels/<id>/agents/install/` · `/agents/<handle>/` |
| Channel name / topic / visibility | `/chat/channels/<id>/` |

## Channel panel

Two **distinct** invite paths — most apps muddle these:

1. **Add from workspace** — the person already exists; one click. Uses `mention-candidates`.
2. **Invite by email** — creates the workspace invitation *and* queues them into this
   channel, so they land where they were invited rather than in a void.

Roles are `admin` / `member` (`ChannelMembership.Role`). Gate the role dropdowns and
Remove buttons behind `isChannelAdmin`.

**Channel-resident agents are the differentiator.** Your backend has
`is_channel_resident` + `resident_handle`, so an agent can live inside a channel and be
called by its own `@handle` (e.g. `@contracts` in `#legal`). Nothing else does this —
the Agents tab makes it visible.

**Channel context** links a channel to a cortex scope (`clients/cube-digital`), so agents
answer there from that client's meetings/emails/docs first. This is what connects the chat
layer to the cortex layer.

**Archive ≠ Delete.** Archive hides the channel but keeps history + cortex memory — it's
the one people actually want.

## Design rules baked in

- **Warm surfaces, never white.** `--dn-surface` is `oklch(0.978 0.013 92)`.
  Pure white cards glare against the cream — this is the single most important token.
- **Grape is the only accent.** One brand color; green is reserved for live/active status.
- **Flat bold chrome.** Bold 2px ink borders on nav/utility chrome — and **no shadows**.
- **Cream + paper-dot background** (`.dn-paper`).
- **Inter** everywhere.
- **Role-gate the UI**: members read-only, admins invite + configure, owner sees Danger zone.
  The backend enforces this already — match it so nobody hits a 403.

### Final profile style (chosen)
- First two cards **outlined** (`.dn-row--outline`) — transparent, dots show through.
- Text fields **warm fill + bold ink border**, pill radius (`.dn-input--profile`).
- Presence toggle **green when on** (`.dn-toggle--presence.is-on`) — reads as "you are live".

## Tokens

Every color is a CSS variable on `:root` in `css/donna.css`. To retheme, change
`--dn-grape` (accent) or `--dn-bg` / `--dn-surface` (paper). If you use Tailwind,
map them straight across:

```js
colors: {
  grape:   "var(--dn-grape)",
  surface: "var(--dn-surface)",
  ink:     "var(--dn-ink)",
}
```
