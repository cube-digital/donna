// 44px header across the main + rightrail columns.
// Ported from donnaai/project/sidebar.jsx:183-225.
//
// The crumb on the left reads the route + channels store to pick a
// label ("# general", "Personal · Donna", "Search…"). The search box
// is decorative for now (focus + ⌘K kbd hint), wired to navigate to
// /search on submit. Bell routes to /search for v1 since /notifications
// isn't a real route yet.

import { useMemo } from "react";
import { useLocation, useMatch, useNavigate } from "react-router-dom";

import { useChannels } from "../../state/channels";
import { useNotifications } from "../../state/notifications";
import { Ic } from "../Ui/Ic";

interface Crumb {
  icon: keyof typeof Ic;
  label: string;
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
          hashed: ch.kind === "channel",
        };
      }
      return { icon: "hash", label: "Channel" };
    }
    if (personalMatch || location.pathname.startsWith("/personal")) {
      return { icon: "sparkle", label: "Personal · Donna" };
    }
    if (location.pathname.startsWith("/search")) {
      return { icon: "search", label: "Search" };
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

  const CrumbIcon = Ic[crumb.icon];

  // Electron window drag — the whole top bar acts as the OS title bar.
  // Interactive children opt out via `no-drag`. No-ops in normal browsers.
  const dragStyle = { WebkitAppRegion: "drag" } as React.CSSProperties;
  const noDragStyle = { WebkitAppRegion: "no-drag" } as React.CSSProperties;

  return (
    <div
      className="[grid-area:topbar] flex items-center gap-2.5 px-3 bg-bg-0 border-b border-border-soft"
      style={dragStyle}
    >
      {/* pl-20 reserves space for macOS traffic-light controls under hiddenInset */}
      <div className="flex items-center gap-2 text-text-2 text-[12.5px] pl-20">
        <CrumbIcon />
        {crumb.hashed ? (
          <>
            <span className="text-text-3">#</span>
            <b className="text-text-0 font-medium">{crumb.label}</b>
          </>
        ) : (
          <b className="text-text-0 font-medium">{crumb.label}</b>
        )}
      </div>

      <form
        style={noDragStyle}
        className="flex-1 max-w-[560px] mx-auto flex items-center gap-2 h-7 px-2.5 bg-bg-2 border border-border-soft rounded text-text-2 text-[12.5px]"
        onSubmit={(e) => {
          e.preventDefault();
          navigate("/search");
        }}
        role="search"
        aria-label="Search"
      >
        <Ic.search />
        <input
          type="text"
          className="flex-1"
          placeholder="Search messages, files, agents, or ask Donna…"
          onFocus={() => navigate("/search")}
          readOnly
        />
        <kbd className="font-mono text-[10.5px] text-text-3 px-[5px] py-px rounded-sm bg-bg-1 border border-border-soft">
          ⌘K
        </kbd>
      </form>

      <div style={noDragStyle} className="flex gap-1">
        <button
          type="button"
          className="relative w-7 h-7 grid place-items-center rounded-md text-text-2 hover:bg-bg-2 hover:text-text-0"
          title={
            unreadCount > 0
              ? `${unreadCount} unread notification${unreadCount === 1 ? "" : "s"}`
              : "Notifications"
          }
          aria-label={
            unreadCount > 0
              ? `Notifications (${unreadCount} unread)`
              : "Notifications"
          }
          onClick={() => navigate("/search")}
        >
          <Ic.bell />
          {unreadCount > 0 && (
            <span
              aria-hidden="true"
              className="pointer-events-none absolute top-0.5 right-0.5 min-w-[14px] h-[14px] px-[3px] rounded-sm bg-ai text-bg-0 text-[9px] font-bold leading-[14px] text-center"
            >
              {unreadCount > 9 ? "9+" : unreadCount}
            </span>
          )}
        </button>
        <button
          type="button"
          className="w-7 h-7 grid place-items-center rounded-md text-text-2 hover:bg-bg-2 hover:text-text-0"
          title="More"
          aria-label="More options"
        >
          <Ic.more />
        </button>
      </div>
    </div>
  );
}
