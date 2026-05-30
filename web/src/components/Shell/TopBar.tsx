// 44px header across the main + rightrail columns.
// Ported from donnaai/project/sidebar.jsx:183-225, then re-skinned onto
// the Goofy library: search bar is `<GInput kbd="⌘K"/>`, bell + more are
// `<GIconButton/>` stickers, the unread badge is `<GBadge mention/>`.
//
// The crumb on the left reads the route + channels store to pick a
// label ("# general", "Personal · Donna", "Search…"); a hand-lettered
// Caveat subtitle sits underneath. The search box is decorative for now
// (focus + ⌘K kbd hint), wired to navigate to /search on submit. Bell
// routes to /search for v1 since /notifications isn't a real route yet.

import { useMemo } from "react";
import { Link, useLocation, useMatch, useNavigate } from "react-router-dom";

import { useChannels } from "../../state/channels";
import { useNotifications } from "../../state/notifications";
import {
  GBadge,
  GIconButton,
  GlyphSlot,
  type IconName,
} from "../Goofy";

// Build once at module scope — `Intl.PluralRules` allocates a small
// internal collator; cheap, but no reason to re-instantiate per render.
const PLURAL_EN = new Intl.PluralRules("en-US");
function notificationCount(n: number): string {
  // English-only fallback for the v1 string; swap the locale + branches
  // when full i18n lands. Uses the proper CLDR `one`/`other` keys
  // instead of `n === 1 ? "" : "s"` so localisation can plug in later.
  const form = PLURAL_EN.select(n);
  return form === "one" ? `${n} unread notification` : `${n} unread notifications`;
}

interface Crumb {
  icon: IconName;
  label: string;
  /** Optional hand-lettered subtitle (Caveat). */
  subtitle?: string;
  /** Channel rows prefix the label with a `#` glyph in muted ink. */
  hashed?: boolean;
}

export default function TopBar() {
  const navigate = useNavigate();
  const location = useLocation();
  const channelMatch = useMatch("/channels/:channelId");
  const personalMatch = useMatch("/personal/:channelId");
  const channelsById = useChannels((s) => s.byId);
  const unreadCount = useNotifications((s) => s.unreadCount);

  const crumb = useMemo<Crumb>(() => {
    if (channelMatch?.params.channelId) {
      const ch = channelsById[channelMatch.params.channelId];
      if (ch) {
        return {
          icon: ch.kind === "direct" ? "at" : "hash",
          label: ch.name,
          subtitle: "let's talk",
          hashed: ch.kind === "channel",
        };
      }
      return { icon: "hash", label: "Channel", subtitle: "let's talk" };
    }
    if (personalMatch || location.pathname.startsWith("/personal")) {
      return {
        icon: "sparkle",
        label: "Personal · Donna",
        subtitle: "your trusty teammate",
      };
    }
    if (location.pathname.startsWith("/search")) {
      return { icon: "search", label: "Search", subtitle: "find anything" };
    }
    if (location.pathname.startsWith("/agents")) {
      return { icon: "sparkle", label: "Agent profile" };
    }
    if (location.pathname.startsWith("/projects")) {
      return { icon: "folder", label: "Project" };
    }
    return { icon: "home", label: "Workspace" };
  }, [
    channelMatch?.params.channelId,
    personalMatch,
    location.pathname,
    channelsById,
  ]);

  // Electron window drag — the whole top bar acts as the OS title bar.
  // Interactive children opt out via `no-drag`. No-ops in normal browsers.
  const dragStyle = { WebkitAppRegion: "drag" } as React.CSSProperties;
  const noDragStyle = { WebkitAppRegion: "no-drag" } as React.CSSProperties;

  return (
    <div
      // 3-column grid (1fr / auto / 1fr) — guarantees the centre column
      // (search) is centred on the topbar regardless of how wide the
      // crumb on the left is. A naive flex layout would let a variable-
      // width crumb push the search off-centre across routes (which is
      // what the previous `flex-1 + mx-auto` arrangement did — the search
      // bar drifted ~80 px between e.g. `/channels` and `/personal`).
      className="[grid-area:topbar] grid grid-cols-[1fr_auto_1fr] items-center gap-2.5 px-3 bg-bg-0 border-b border-border-soft"
      style={dragStyle}
    >
      {/* Left — crumb. `min-w-0` lets the inner span truncate cleanly when
          the crumb is longer than the 1fr column. `pl-20` reserves the
          macOS traffic-light controls under hiddenInset. */}
      <div className="min-w-0 flex items-center gap-2 pl-20 font-display font-medium text-text-0 text-[14px]">
        <GlyphSlot name={crumb.icon} size={16} />
        {crumb.hashed ? (
          <span className="flex items-baseline gap-1.5 min-w-0">
            <span className="text-text-3 shrink-0">#</span>
            <b className="font-display font-semibold text-text-0 truncate">
              {crumb.label}
            </b>
            {crumb.subtitle ? (
              <span className="font-hand font-bold text-[15px] text-ai-deep leading-none shrink-0">
                {crumb.subtitle}
              </span>
            ) : null}
          </span>
        ) : (
          <span className="flex items-baseline gap-1.5 min-w-0">
            <b className="font-display font-semibold text-text-0 truncate">
              {crumb.label}
            </b>
            {crumb.subtitle ? (
              <span className="font-hand font-bold text-[15px] text-ai-deep leading-none shrink-0">
                {crumb.subtitle}
              </span>
            ) : null}
          </span>
        )}
      </div>

      {/* Centre — search trigger.
          Previously a readonly `<input>` that navigated on focus, which
          breaks Cmd-click + middle-click and is semantically a button
          masquerading as text. Render a real `<Link/>` styled like the
          GInput pill so keyboard, screen-reader, and pointer affordances
          all agree on what's happening. */}
      <div style={noDragStyle} className="w-[560px] max-w-[40vw]">
        <Link
          to="/search"
          aria-label="Search messages, files, agents, or ask Donna"
          className="flex items-center gap-[9px] h-[34px] px-[14px] w-full border-2 border-ink rounded-full shadow-ink-1 bg-bg-1 text-text-3 transition-[box-shadow,border-color] duration-[120ms] hover:border-ai hover:shadow-[3px_3px_0_var(--ai)] outline-none focus-visible:border-ai focus-visible:shadow-[3px_3px_0_var(--ai)]"
        >
          <GlyphSlot name="search" />
          <span className="flex-1 min-w-0 truncate text-[13.5px]">
            Search messages, files, agents, or ask&nbsp;Donna…
          </span>
          <kbd className="font-mono text-[10.5px] font-semibold px-1.5 py-0.5 rounded-[5px] border-[1.5px] border-ink bg-pop-sun text-on-bright">
            ⌘&nbsp;K
          </kbd>
        </Link>
      </div>

      {/* Right — bell + more. `justify-end` pins the cluster flush right
          regardless of crumb width. */}
      <div style={noDragStyle} className="flex gap-1 items-center justify-end">
        <span className="relative inline-block">
          <GIconButton
            icon="bell"
            title={
              unreadCount > 0 ? notificationCount(unreadCount) : "Notifications"
            }
            aria-label={
              unreadCount > 0
                ? `Notifications (${notificationCount(unreadCount)})`
                : "Notifications"
            }
            onClick={() => navigate("/search")}
          />
          {unreadCount > 0 && (
            <span
              aria-hidden="true"
              className="pointer-events-none absolute -top-0.5 -right-0.5"
            >
              <GBadge mention>{unreadCount > 9 ? "9+" : unreadCount}</GBadge>
            </span>
          )}
        </span>
        <GIconButton icon="more" title="More" aria-label="More options" />
      </div>
    </div>
  );
}
