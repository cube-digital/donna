// Top bar — search pill (centred) + bell/more cluster (right). Left
// column intentionally empty; the channel name is rendered by the
// ChannelHeader directly under this bar, matching the mockup.

import { Link, useNavigate } from "react-router-dom";

import { useNotifications } from "../../state/notifications";
import { GBadge, GlyphSlot } from "../Goofy";

const PLURAL_EN = new Intl.PluralRules("en-US");
function notificationCount(n: number): string {
  const form = PLURAL_EN.select(n);
  return form === "one" ? `${n} unread notification` : `${n} unread notifications`;
}

export default function TopBar() {
  const navigate = useNavigate();
  const unreadCount = useNotifications((s) => s.unreadCount);

  const dragStyle = { WebkitAppRegion: "drag" } as React.CSSProperties;
  const noDragStyle = { WebkitAppRegion: "no-drag" } as React.CSSProperties;

  return (
    <div
      className="h-full grid grid-cols-[1fr_auto_1fr] items-center gap-2.5 px-4 border-b border-border-soft"
      style={dragStyle}
    >
      <div />

      <div style={noDragStyle} className="w-[460px] max-w-[40vw]">
        <Link
          to="/search"
          aria-label="Search messages, files, agents, or ask Donna"
          className="flex items-center gap-[9px] h-[34px] px-[14px] w-full border-2 border-ink rounded-full bg-bg-1 text-text-3 transition-[border-color] duration-[120ms] hover:border-ai outline-none focus-visible:border-ai"
        >
          <GlyphSlot name="search" />
          <span className="flex-1 min-w-0 truncate text-[13.5px]">
            Search messages, files, agents, or ask&nbsp;Donna…
          </span>
          <kbd className="font-mono text-[10.5px] font-semibold px-1.5 py-0.5 rounded-[5px] border-[1.5px] border-ink bg-pop-sun text-on-bright">
            ⌘K
          </kbd>
        </Link>
      </div>

      <div style={noDragStyle} className="flex gap-[14px] items-center justify-end text-text-3">
        <span className="relative inline-block">
          <button
            type="button"
            title={unreadCount > 0 ? notificationCount(unreadCount) : "Notifications"}
            aria-label={
              unreadCount > 0
                ? `Notifications (${notificationCount(unreadCount)})`
                : "Notifications"
            }
            onClick={() => navigate("/search")}
            className="bg-transparent border-0 p-0 text-text-3 hover:text-text-0"
          >
            <GlyphSlot name="bell" />
          </button>
          {unreadCount > 0 && (
            <span
              aria-hidden="true"
              className="pointer-events-none absolute -top-1 -right-1"
            >
              <GBadge mention>{unreadCount > 9 ? "9+" : unreadCount}</GBadge>
            </span>
          )}
        </span>
        <button
          type="button"
          title="More"
          aria-label="More options"
          className="bg-transparent border-0 p-0 text-text-3 hover:text-text-0"
        >
          <GlyphSlot name="more" />
        </button>
      </div>
    </div>
  );
}
