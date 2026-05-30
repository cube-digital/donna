// Channel view — port of `donnaai/project/channel.jsx:121-160`.
//
// Pulls together the four pieces of the chat surface:
//   1. ChannelHeader (title + member stack + AI pill)
//   2. The scrolling message list with day-dividers between calendar
//      days, oldest at the top.
//   3. A Composer pinned to the bottom (WS send path).
//   4. Realtime: subscribe to the channel on mount, listen for
//      `message.created`/`updated`/`deleted`/`typing` and route them
//      through the messages + presence stores.
//
// Scroll behaviour
// ────────────────
// We auto-scroll to the bottom when *new* messages arrive but ONLY if
// the user is already near the bottom (within 80px of the floor).
// That way someone reading older history isn't yanked away every
// time a new line arrives. The reference is held in `scrollRef`; we
// recompute "near bottom" on every scroll event via `wasAtBottomRef`.
//
// Load older
// ──────────
// When the scroll position approaches the top (< 200px), we fire
// `loadMore` with the id of the oldest currently-loaded message. The
// REST endpoint returns older messages oldest-first; the store
// prepends them, so we capture `scrollHeight` before and adjust
// `scrollTop` after the layout commit to keep the user's anchor row
// in place. Without that the viewport would jump to the new top.
//
// Mark-read
// ─────────
// When the user is at the bottom AND there's a newer message than the
// last one we marked, we send a `mark_read` over the WS. The backend
// fans out a `read.advanced` to other devices. We debounce ~500ms so
// fast scrolling at the bottom doesn't fire per-frame.
//
// Day divider markup
// ──────────────────
// The original CSS used `::before` + `::after` 1px lines flanking the
// label. In Tailwind we render them as explicit children inside a
// 3-col grid (`grid-cols-[1fr_auto_1fr]`) with `h-px bg-border-soft`
// rules; the label sits in the middle column. The wrapper supplies the
// uppercase/tracking text style.

import { useEffect, useLayoutEffect, useMemo, useRef } from "react";
import { useParams } from "react-router-dom";

import ChannelHeader from "../components/Channel/ChannelHeader";
import Composer from "../components/Channel/Composer";
import Message from "../components/Channel/Message";
import {
  ContextSection,
  DocsSection,
  ProgressStub,
} from "../components/RightRail/RightRail";
import { useRightRail } from "../components/Shell/RightRailSlot";
import { getChatWs } from "../lib/ws";
import { useChannels } from "../state/channels";
import { useMessages } from "../state/messages";
import { usePresence, useTypingUserIds } from "../state/presence";
import type { Message as MessageT } from "../types";

const NEAR_BOTTOM_PX = 80;
const LOAD_OLDER_THRESHOLD_PX = 200;
const LOAD_OLDER_MIN_COUNT = 50;
const MARK_READ_DEBOUNCE_MS = 500;

function dayKey(iso: string): string {
  // ISO timestamp → YYYY-MM-DD in local time.
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "unknown";
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function dayLabel(key: string): string {
  if (key === "unknown") return "";
  const [y, m, d] = key.split("-").map(Number);
  const date = new Date(y, m - 1, d);
  const today = new Date();
  const startOfToday = new Date(
    today.getFullYear(),
    today.getMonth(),
    today.getDate(),
  );
  const diffDays = Math.round(
    (date.getTime() - startOfToday.getTime()) / 86_400_000,
  );
  if (diffDays === 0) {
    const monthName = date.toLocaleString(undefined, { month: "short" });
    return `Today · ${monthName} ${date.getDate()}`;
  }
  if (diffDays === -1) {
    const monthName = date.toLocaleString(undefined, { month: "short" });
    return `Yesterday · ${monthName} ${date.getDate()}`;
  }
  // Absolute: "Mon, Apr 11"
  return date.toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

interface GroupedItem {
  type: "divider";
  key: string;
  label: string;
}
interface MessageItem {
  type: "message";
  key: string;
  msg: MessageT;
}
type RowItem = GroupedItem | MessageItem;

function groupByDay(list: MessageT[]): RowItem[] {
  const out: RowItem[] = [];
  let lastDay: string | null = null;
  for (const msg of list) {
    const k = dayKey(msg.created_at);
    if (k !== lastDay) {
      out.push({ type: "divider", key: `d-${k}`, label: dayLabel(k) });
      lastDay = k;
    }
    out.push({ type: "message", key: `m-${msg.id}`, msg });
  }
  return out;
}

// Day divider — 3-col grid with two thin rules flanking the label.
function DayDivider({ label }: { label: string }) {
  return (
    <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3 mt-3.5 mb-2 mx-[18px] text-text-3 text-[11px] tracking-[0.04em] uppercase">
      <span className="h-px bg-border-soft" />
      <span className="px-3">{label}</span>
      <span className="h-px bg-border-soft" />
    </div>
  );
}

// Centred status row (loading / loading-older). Same chrome as DayDivider
// without the flanking rules — just the centered label.
function CenteredStatus({ label }: { label: string }) {
  return (
    <div className="flex justify-center mt-3.5 mb-2 mx-[18px] text-text-3 text-[11px] tracking-[0.04em] uppercase">
      <span className="px-3">{label}</span>
    </div>
  );
}

export default function Channel() {
  const { channelId } = useParams<{ channelId: string }>();
  const channel = useChannels((s) =>
    channelId ? s.byId[channelId] : undefined,
  );
  const messages = useMessages((s) =>
    channelId ? s.byChannel[channelId] : undefined,
  );
  const loading = useMessages((s) =>
    channelId ? !!s.loading[channelId] : false,
  );
  const loadInitial = useMessages((s) => s.loadInitial);
  // `loadMore` is read inside the scroll handler via `useMessages.getState()`
  // so we don't subscribe to it here.
  const appendFromEvent = useMessages((s) => s.appendFromEvent);
  const updateFromEvent = useMessages((s) => s.updateFromEvent);
  const removeFromEvent = useMessages((s) => s.removeFromEvent);
  const markTyping = usePresence((s) => s.markTyping);
  const setCurrentUserId = usePresence((s) => s.setCurrentUserId);
  const typingUserIds = useTypingUserIds(channelId);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const wasAtBottomRef = useRef(true);
  const prevLenRef = useRef(0);
  // Anchor scrollHeight captured BEFORE a `loadMore` to restore position
  // after older messages are prepended. Null means "no load in flight".
  const restoreAnchorRef = useRef<number | null>(null);
  // Guard against firing `loadMore` while a previous call is in flight or
  // when we've exhausted the history (REST returned < limit). Reset each
  // time channelId changes.
  const exhaustedRef = useRef(false);
  // Last message id we've marked-read for the active channel. Stays
  // pristine until we actually fire mark_read once.
  const lastMarkedIdRef = useRef<string | null>(null);
  const markReadTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Load history when the channel id changes.
  useEffect(() => {
    if (!channelId) return;
    exhaustedRef.current = false;
    lastMarkedIdRef.current = null;
    void loadInitial(channelId);
  }, [channelId, loadInitial]);

  // WS subscribe + event wiring. Re-runs only when channelId changes.
  useEffect(() => {
    if (!channelId) return;
    const ws = getChatWs();
    ws.subscribe(channelId);

    const offCreated = ws.on("message.created", (p) => {
      if (p.channel_id !== channelId) return;
      appendFromEvent(channelId, p);
    });
    const offUpdated = ws.on("message.updated", (p) => {
      if (p.channel_id !== channelId) return;
      updateFromEvent(channelId, p);
    });
    const offDeleted = ws.on("message.deleted", (p) => {
      if (p.channel_id !== channelId) return;
      removeFromEvent(channelId, p.message_id);
    });
    const offTyping = ws.on("typing", (p) => {
      if (p.channel_id !== channelId) return;
      markTyping(channelId, p.user_id);
    });
    // `connected` carries our own user id — capture so the typing
    // indicator can filter ourselves out. The handshake may have
    // already fired before this mount; that's fine — the handler will
    // catch the next reconnect or we render the indicator harmlessly
    // until then.
    const offConnected = ws.on("connected", (p) => {
      setCurrentUserId(p.user_id);
    });

    return () => {
      offCreated();
      offUpdated();
      offDeleted();
      offTyping();
      offConnected();
      ws.unsubscribe(channelId);
    };
  }, [
    channelId,
    appendFromEvent,
    updateFromEvent,
    removeFromEvent,
    markTyping,
    setCurrentUserId,
  ]);

  // Track whether the user is near the bottom; updated on every scroll.
  // Also trigger `loadMore` when nearing the top.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const handler = () => {
      const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
      wasAtBottomRef.current = distance < NEAR_BOTTOM_PX;

      // Near-top check for loading older history.
      if (!channelId) return;
      if (exhaustedRef.current) return;
      const state = useMessages.getState();
      const list = state.byChannel[channelId];
      const isLoading = !!state.loading[channelId];
      if (
        !isLoading &&
        list &&
        list.length >= LOAD_OLDER_MIN_COUNT &&
        el.scrollTop < LOAD_OLDER_THRESHOLD_PX &&
        restoreAnchorRef.current === null
      ) {
        const oldest = list[0];
        if (oldest) {
          restoreAnchorRef.current = el.scrollHeight;
          const before = list.length;
          void state.loadMore(channelId, oldest.id).then(() => {
            const after =
              useMessages.getState().byChannel[channelId]?.length ?? before;
            // Nothing came back → consider history exhausted.
            if (after <= before) {
              exhaustedRef.current = true;
              restoreAnchorRef.current = null;
            }
          });
        }
      }
    };
    handler();
    el.addEventListener("scroll", handler, { passive: true });
    return () => el.removeEventListener("scroll", handler);
  }, [channelId]);

  // Snap to bottom when new messages arrive AND the user was already
  // near the bottom (or we just loaded a fresh history page). Also
  // restore scroll anchor after a prepended `loadMore`.
  const list = messages ?? [];
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const grew = list.length > prevLenRef.current;
    prevLenRef.current = list.length;

    // Restore-after-prepend takes precedence over the bottom snap.
    if (restoreAnchorRef.current !== null && grew) {
      const before = restoreAnchorRef.current;
      restoreAnchorRef.current = null;
      const delta = el.scrollHeight - before;
      el.scrollTop += delta;
      return;
    }

    if (!grew) return;
    if (wasAtBottomRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [list]);

  // Mark-read: when at bottom AND newest id changed since last marked,
  // debounce a WS `mark_read`.
  useEffect(() => {
    if (!channelId) return;
    if (list.length === 0) return;
    const newest = list[list.length - 1];
    // Optimistic `tmp-` ids never round-trip; skip them.
    if (newest.id.startsWith("tmp-")) return;
    if (newest.id === lastMarkedIdRef.current) return;
    if (!wasAtBottomRef.current) return;

    if (markReadTimerRef.current) clearTimeout(markReadTimerRef.current);
    markReadTimerRef.current = setTimeout(() => {
      // Re-check the bottom state at fire-time — the user may have
      // scrolled up during the debounce window.
      if (!wasAtBottomRef.current) return;
      lastMarkedIdRef.current = newest.id;
      getChatWs().send("mark_read", {
        channel_id: channelId,
        message_id: newest.id,
      });
    }, MARK_READ_DEBOUNCE_MS);

    return () => {
      if (markReadTimerRef.current) {
        clearTimeout(markReadTimerRef.current);
        markReadTimerRef.current = null;
      }
    };
  }, [channelId, list]);

  const rows = useMemo(() => groupByDay(list), [list]);

  // Right-rail content for this view. `channelId` change re-fires the slot.
  const rrNode = useMemo(
    () => (
      <>
        <ProgressStub />
        <DocsSection channelId={channelId} />
        <ContextSection />
      </>
    ),
    [channelId],
  );
  useRightRail(rrNode);

  if (!channelId) {
    return <div className="p-10">No channel selected.</div>;
  }

  // Typing-pill text — show up to two names, then a "+N" overflow.
  // Until a /users/{id} fetch lands we don't have names for arbitrary
  // user ids; fall back to a short id slice so the chip still renders.
  const typingLabel = formatTypingLabel(typingUserIds);

  return (
    <div className="flex flex-col h-full">
      {channel ? (
        <ChannelHeader channel={channel} channelMessages={list} />
      ) : (
        <div className="flex items-center gap-3 px-[18px] py-2.5 border-b border-border-soft shrink-0">
          <div className="flex items-center gap-1.5 text-[15px] font-semibold text-text-0 tracking-[-0.01em]">
            <span className="text-text-3">#</span>Loading…
          </div>
        </div>
      )}

      <div className="flex-1 overflow-y-auto pt-3.5 pb-2" ref={scrollRef}>
        {restoreAnchorRef.current !== null ? (
          <CenteredStatus label="Loading older messages…" />
        ) : null}
        {loading && list.length === 0 ? <CenteredStatus label="Loading…" /> : null}
        {rows.map((row) =>
          row.type === "divider" ? (
            <DayDivider key={row.key} label={row.label} />
          ) : (
            <Message key={row.key} msg={row.msg} />
          ),
        )}
      </div>

      {typingLabel ? (
        <div className="px-[22px] pt-0.5 pb-1 text-text-3 text-[11.5px] italic min-h-[18px]">
          {typingLabel}
        </div>
      ) : null}

      <Composer channelId={channelId} />
    </div>
  );
}

/**
 * Render "Alice is typing…" / "Alice and Bob are typing…" /
 * "Alice, Bob and 2 others are typing…".
 *
 * We don't currently have a /users/{id} fetch wired, so for now we
 * stub names from the user-id prefix. Once the user store lands we'll
 * replace this with real display names.
 */
function formatTypingLabel(userIds: string[]): string {
  if (userIds.length === 0) return "";
  // 8-char prefix is enough to distinguish typists at-a-glance; the
  // UUIDs are stable so it doesn't flicker between renders.
  const stubName = (id: string) => `user-${id.slice(0, 6)}`;
  const names = userIds.map(stubName);
  if (names.length === 1) return `${names[0]} is typing…`;
  if (names.length === 2) return `${names[0]} and ${names[1]} are typing…`;
  const head = names.slice(0, 2).join(", ");
  return `${head} and ${names.length - 2} others are typing…`;
}
