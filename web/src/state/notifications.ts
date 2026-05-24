// Notifications store — feeds the bell in TopBar + the (future) feed view.
//
// Two ingress paths:
//   1. `loadInitial()`           one-shot REST seed via api/notifications.list
//   2. `pushFromSse(notif)`      live insert from the SSE stream — caller
//                                normalises the SSE payload to Notification
//                                before invoking us (the SSE payload shape
//                                from NotificationPayload diverges slightly
//                                from the DB serializer).
//
// `unreadCount` is derived from `items` on every mutation so consumers
// (TopBar badge) only need to read one value.

import { create } from "zustand";

import {
  listNotifications,
  markAllRead as apiMarkAllRead,
  markRead as apiMarkRead,
} from "../api/notifications";
import type { Notification } from "../types";

interface NotificationsState {
  items: Notification[];
  unreadCount: number;
  loading: boolean;
  loaded: boolean;
  loadInitial(): Promise<void>;
  pushFromSse(n: Notification): void;
  markRead(ids: string[]): Promise<void>;
  markAllRead(): Promise<void>;
}

function countUnread(items: Notification[]): number {
  let n = 0;
  for (const it of items) if (!it.seen) n += 1;
  return n;
}

export const useNotifications = create<NotificationsState>((set, get) => ({
  items: [],
  unreadCount: 0,
  loading: false,
  loaded: false,

  loadInitial: async () => {
    if (get().loading) return;
    set({ loading: true });
    try {
      const { results } = await listNotifications();
      set({ items: results, unreadCount: countUnread(results), loaded: true });
    } catch {
      // Swallow — bell stays at 0; consumers can retry via re-mount.
    } finally {
      set({ loading: false });
    }
  },

  pushFromSse: (n) => {
    const items = get().items;
    if (items.some((i) => i.id === n.id)) return; // dedupe
    const next = [n, ...items];
    set({ items: next, unreadCount: countUnread(next) });
  },

  markRead: async (ids) => {
    if (!ids.length) return;
    // Optimistic update.
    const prev = get().items;
    const next = prev.map((i) => (ids.includes(i.id) ? { ...i, seen: true } : i));
    set({ items: next, unreadCount: countUnread(next) });
    try {
      await apiMarkRead(ids);
    } catch {
      // Roll back on failure.
      set({ items: prev, unreadCount: countUnread(prev) });
    }
  },

  markAllRead: async () => {
    const prev = get().items;
    const next = prev.map((i) => (i.seen ? i : { ...i, seen: true }));
    set({ items: next, unreadCount: 0 });
    try {
      await apiMarkAllRead();
    } catch {
      set({ items: prev, unreadCount: countUnread(prev) });
    }
  },
}));
