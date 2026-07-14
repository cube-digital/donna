// Top bar — search pill (centred) + bell/more cluster (right). Left
// column intentionally empty; the channel name is rendered by the
// ChannelHeader directly under this bar, matching the mockup.

import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { useNotifications } from "../../state/notifications";
import type { Notification } from "../../types";
import { GBadge, GlyphSlot } from "../Goofy";

const PLURAL_EN = new Intl.PluralRules("en-US");
function notificationCount(n: number): string {
  const form = PLURAL_EN.select(n);
  return form === "one" ? `${n} unread notification` : `${n} unread notifications`;
}

function relTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const s = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (s < 60) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

const STATUS_DOT: Record<Notification["status"], string> = {
  info: "bg-pop-blue",
  success: "bg-ok",
  warning: "bg-pop-sun",
  error: "bg-danger",
};

function NotificationsPanel() {
  const items = useNotifications((s) => s.items);
  const markRead = useNotifications((s) => s.markRead);
  const markAllRead = useNotifications((s) => s.markAllRead);
  const hasUnread = items.some((i) => !i.seen);

  return (
    <div
      role="dialog"
      aria-label="Notifications"
      className="absolute right-0 top-[calc(100%+8px)] z-50 w-[360px] max-h-[70vh] flex flex-col rounded-[12px] border border-border-soft bg-bg-1 shadow-lg overflow-hidden"
    >
      <div className="flex items-center gap-2 px-3 py-2.5 border-b border-border-soft">
        <span className="font-semibold text-[13px] text-text-0">Notifications</span>
        <span className="flex-1" />
        {hasUnread ? (
          <button
            type="button"
            onClick={() => void markAllRead()}
            className="text-[11.5px] text-ai hover:underline"
          >
            Mark all read
          </button>
        ) : null}
      </div>

      <div className="flex-1 overflow-y-auto">
        {items.length === 0 ? (
          <div className="px-3 py-8 text-center text-[12.5px] text-text-3">
            No notifications yet.
          </div>
        ) : (
          items.map((n) => (
            <button
              key={n.id}
              type="button"
              onClick={() => {
                if (!n.seen) void markRead([n.id]);
              }}
              className={
                "w-full text-left flex gap-2.5 px-3 py-2.5 border-b border-border-soft last:border-b-0 transition-colors " +
                (n.seen ? "hover:bg-bg-2" : "bg-[var(--ai-bg)]/40 hover:bg-[var(--ai-bg)]/70")
              }
            >
              <span
                className={
                  "mt-1.5 w-2 h-2 rounded-full shrink-0 " +
                  (n.seen ? "bg-transparent" : STATUS_DOT[n.status] ?? "bg-pop-blue")
                }
                aria-hidden="true"
              />
              <span className="min-w-0 flex-1">
                <span className="flex items-baseline gap-2">
                  <span className="font-semibold text-[12.5px] text-text-0 truncate">
                    {n.title}
                  </span>
                  <span className="ml-auto shrink-0 text-[10.5px] text-text-4 font-mono">
                    {relTime(n.created_at)}
                  </span>
                </span>
                <span className="block text-[12px] text-text-2 mt-0.5">{n.message}</span>
              </span>
            </button>
          ))
        )}
      </div>
    </div>
  );
}

export default function TopBar() {
  const unreadCount = useNotifications((s) => s.unreadCount);
  const loaded = useNotifications((s) => s.loaded);
  const loadInitial = useNotifications((s) => s.loadInitial);
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLSpanElement>(null);

  // Seed from REST the first time the panel opens (SSE only pushes new ones).
  useEffect(() => {
    if (open && !loaded) void loadInitial();
  }, [open, loaded, loadInitial]);

  // Close on outside click + Escape.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

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
        <span ref={wrapRef} className="relative inline-block">
          <button
            type="button"
            title={unreadCount > 0 ? notificationCount(unreadCount) : "Notifications"}
            aria-label={
              unreadCount > 0
                ? `Notifications (${notificationCount(unreadCount)})`
                : "Notifications"
            }
            aria-haspopup="dialog"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
            className={
              "bg-transparent border-0 p-0 hover:text-text-0 " +
              (open ? "text-text-0" : "text-text-3")
            }
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
          {open && <NotificationsPanel />}
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
