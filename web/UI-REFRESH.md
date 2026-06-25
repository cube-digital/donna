# Donna UI refresh — implementation spec

Goal: keep the brand identity (cream paper background, grape `--ai` accent, Donna
character, rounded friendliness) but remove the "goofy sticker" weight — soften
shadows, thin the borders, drop the cursive + hover wiggles, modernize the
message format, and quiet the side panels.

Visual target: `../assets/donna-ui-refresh-mockup.html` (open in a browser).
Stack: React + Tailwind (`web/`), design tokens in `src/styles/tokens.css`,
Tailwind mappings in `tailwind.config.ts`. Components under `src/components/`,
with shared primitives in `src/components/Goofy/*`.

---

## Already implemented (done — do not redo)

These edits are committed in the working tree:

1. `src/styles/tokens.css`
   - `--ink` lifted from near-black `oklch(0.26 0.03 285)` to soft charcoal
     `oklch(0.42 0.022 285)`.
   - `--border-strong` softened to `oklch(0.55 0.02 285 / 0.45)`.
   - Radii calmed: `--r-sm:6` `--r:10` `--r-lg:14` `--r-xl:18`.
   - Hard-offset sticker shadows replaced with soft drop shadows:
     - `--shadow-1: 0 1px 2px oklch(0.26 0.03 285/.08), 0 1px 3px oklch(0.26 0.03 285/.10)`
     - `--shadow-2: 0 4px 10px oklch(0.26 0.03 285/.10), 0 12px 24px oklch(0.26 0.03 285/.08)`
     - `--shadow-ai: 0 4px 14px oklch(0.55 0.23 var(--ai-h)/.28)`
2. `tailwind.config.ts`
   - `shadow-ink-3` / `shadow-ink-4` (hover lift) changed from hard offsets to soft blurred shadows.
   - `animation.wiggle` and `animation.mini-wiggle` set to `none`.
   - `fontFamily.hand` remapped off `Caveat` to the clean sans stack.
3. `src/styles/global.css`
   - Scrollbar slimmed 13px→10px, thumb recolored to `--text-4`/`--text-3`.
   - `.av-agent-gradient` ring softened `0 0 0 2px var(--ink)` → `0 0 0 1px var(--border-strong)`.
   - Global `.gx.wiggly` hover-wiggle rule removed.
4. Inline cleanups: removed Caveat fallback in `src/App.tsx`; dropped the
   "let's talk" subtitle in `src/components/Shell/TopBar.tsx`; swept all
   `shadow-[Npx_Npx_0_var(--…)]` hard offsets to `shadow-ink-1`/`shadow-ai-stamp`
   and removed `hover:rotate-*` tilts across `Goofy/*`, `Shell/WsRail.tsx`,
   `RightRail.tsx`.
5. `src/components/Goofy/GBubble.tsx` — user bubble changed from `bg-pop-blue`
   + `border-2 border-ink` to solid grape `bg-ai` with no border.
6. Typeface switched to **Inter** across the app: `web/index.html` now loads
   `Inter` (400–700) + Geist Mono (dropped Fredoka + Caveat), and
   `tailwind.config.ts` maps `font-sans`, `font-display`, and `font-hand` all to
   the Inter stack.

---

## To implement (this is the new work)

### 1. Borderless agent messages  ·  `src/components/Goofy/GBubble.tsx`, `src/components/Channel/Message.tsx`
The agent (`from="agent"`) branch currently renders a bordered cream card
(`bg-bg-1 border-2 border-ink rounded-[…] shadow-ink-1`). Remove the box entirely:
- No border, no background fill, no shadow on the agent body.
- Layout: avatar (left) + a column with the head row (name + AGENT chip + time)
  and the message text as plain prose on the page.
- Keep `max-w` for readability; add a subtle `hover:bg-[oklch(0.30_0.02_285/.03)]`
  row highlight + `rounded-lg` so hover actions have a target.
- User bubble (`from="user"`) stays the solid-grape bubble (already done).

### 2. Render markdown in message bodies  ·  `src/components/Channel/Message.tsx`
Bodies currently print raw markdown (e.g. literal `**bold**`). Render it:
- Bold/italic/lists/inline `code` → real formatting. Use a small sanitized
  markdown renderer (e.g. `react-markdown` + `remark-gfm`, or the existing
  renderer if one is present — check `src/lib` first).
- `cortex://…`, `gmail://…`, `drive://…` URIs → render as small monospace
  source chips: `bg-ai/10 text-ai-deep rounded px-1.5 font-mono text-[12px]`
  (linkable where possible) instead of raw text.

### 3. Merge the composer into one hairline container  ·  `src/components/Channel/Composer.tsx`
Today it's two stacked bordered boxes (a toolbar card above the input card).
Make it a single container:
- One `border border-border-strong rounded-[14px] bg-bg-1` wrapper.
- Textarea on top (placeholder text), a single tool row along the bottom
  separated by a `border-t border-border-soft`.
- Left of the tool row: B / I / link / code / emoji / @ icons (`text-text-4`,
  hover `text-text-2`). Right: "Agents on standby" grape pill + grape send button.
- Optional: only reveal the formatting icons when the field is focused or non-empty.

### 4. Quiet the left sidebar  ·  `src/components/Shell/Sidebar.tsx`
- Pinned/active channel row: replace the bright `bg-pop-sun` (yellow) highlight
  with a soft grape state — `bg-ai/10 text-ai-deep` + an inset left bar
  `shadow-[inset_3px_0_0_var(--ai)]`. Star icon tinted `text-ai`.
- Search: a quiet filled field (`bg-bg-1 border border-border-strong rounded-[9px]`)
  rather than a heavy pill; ⌘K kbd recolored to neutral (`bg-bg-2`), not yellow.
- Tighten section header spacing; unread dots use `bg-ai` (not blue).

### 5. Trim the right rail  ·  `src/components/RightRail/RightRail.tsx`
- Remove the "Progress / Coming soon" placeholder block (or hide until real) —
  it occupies prime space doing nothing.
- Lead with Docs (show the actual doc name, not a blank icon tile) then a
  collapsible "Context" list (chevron to expand/collapse).
- Make the whole rail collapsible so the chat column can widen.

### 6. Message column + grouping  ·  `src/components/Channel/Channel.tsx`, `Message.tsx`
- Cap the message column at ~`max-w-[720px]` and center it (`mx-auto`) so long
  agent answers don't stretch edge-to-edge.
- Group consecutive messages from the same sender: render the avatar + head row
  once, subsequent lines indented under it.
- Move per-message actions (react / reply / copy) into a hover toolbar instead
  of always-on.

### 7. Channel header cleanup  ·  `src/components/Channel/ChannelHeader.tsx`
- Drop or clarify the cryptic chips (the `??` pill, the bare green `1`).
  Keep "1 AI" and member count as labeled chips with soft fills, not bordered stamps.

---

### 8. Keep the bold chrome accents (do NOT soften these)  ·  `Shell/WsRail.tsx`, `Shell/TopBar.tsx`, `Shell/Sidebar.tsx`
The refresh softens most borders to hairline — but a few "chrome" elements are
intentionally kept BOLD (2px solid ink border) and yellow. The user explicitly
loves these; preserve them:
- **Workspace squares** (the `C` tiles, top + bottom of the far-left rail):
  `bg-pop-sun` (yellow) + `border-2 border-ink` + rounded. Already in `WsRail.tsx`.
- **The `+` add-workspace button**: `border-2 border-ink`, paper fill. Already in `WsRail.tsx`.
- **The ⌘K badge** (both the sidebar Search row and the top-bar search):
  `bg-pop-sun` + `border-[1.5px] border-ink` + `text-on-bright`.
- **The top-bar search field**: `border-2 border-ink rounded-full` pill. Already in `TopBar.tsx`.

These chrome elements are FLAT — bold 2px border, no shadow. (We tried a
hard-offset "pop" shadow on them and removed it; the bold border alone carries the
weight.) Do not add box-shadow to the workspace squares, `+` button, search pill,
or ⌘K badge.

Rule of thumb: bold flat borders live ONLY on navigation/utility chrome (workspace
rail, search, ⌘K). The conversation area and panels stay hairline + borderless.
This concentration is what keeps the personality without reading as goofy. The
earlier "bold borders on everything incl. message bubbles" experiment was
rejected — do not apply 2px borders to messages, cards, or agent bubbles.

## Palette reference (tokens already in `tokens.css`)

| Token | Value | Use |
|---|---|---|
| `--bg-0` cream | `oklch(0.962 0.022 92)` | app background |
| `--bg-1` paper | `oklch(0.995 0.006 92)` | surfaces / cards |
| `--ink` | `oklch(0.42 0.022 285)` | soft charcoal outline (hairline) |
| `--ai` grape | `oklch(0.55 0.23 288)` | brand accent, user bubble, primary actions |
| `--ai-deep` | `oklch(0.42 0.20 288)` | grape text on light fills |
| `--ai-bg` | `grape /0.12` | grape tint (active states, chips) |

Drop / avoid: `--pop-blue` for message bubbles (off-brand). The crayon accents
(`--pop-sun` yellow, `--pop-coral`, `--pop-mint`) should be used sparingly — keep
grape as the single dominant accent; a small green dot for "live" status is fine.

## Constraints
- Keep: cream background **with the paper-dot texture** (the `.paper-dots`
  radial-gradient on the chat canvas — `--paper-dot: oklch(0.26 0.03 285/.05)`,
  `background-size: 22px 22px`; defined in `src/styles/global.css`), grape accent,
  Donna character/avatars, rounded corners, a gentle sense of depth (soft shadows
  — not flat, not hard offsets).
- Remove: hard-offset shadows, 2px near-black outlines, cursive, hover wiggle/rotate,
  bright yellow highlight on the pinned row, boxed agent bubbles, raw markdown.
- Verify with `npx tsc -b` (type-check) after each change.
