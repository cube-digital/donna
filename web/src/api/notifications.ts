// Notifications HTTP endpoints — backed by
// server/donna/notifications/api/v1/views.py.
//
// Endpoints (mounted under /api/v1/notifications/):
//   GET   /api/v1/notifications/                     list (paginated, envelope-wrapped)
//   PATCH /api/v1/notifications/seen/                bulk mark {seen, ids?}
//   GET   /api/v1/notifications/stream               SSE (handled in lib/sse.ts)
//
// The backend exposes ONE bulk mutator — `PATCH /seen/` with `{seen, ids?}`.
// "markRead(ids)" and "markAllRead()" are convenience facades over the same
// endpoint that match the names the spec/contract calls for.

import { apiFetch } from "./client";
import type { Notification, Paginated } from "../types";

export interface ListNotificationsOpts {
  unreadOnly?: boolean;
}

export async function listNotifications(
  opts: ListNotificationsOpts = {},
): Promise<{ results: Notification[]; count: number }> {
  const params = new URLSearchParams();
  if (opts.unreadOnly) params.set("seen", "false");
  const qs = params.toString();
  // Donna's renderer puts rows directly in `data` (pagination in `meta`),
  // so what comes out of apiFetch IS the array. Tolerate `{results}` too.
  const data = await apiFetch<Notification[] | Paginated<Notification>>(
    `/api/v1/notifications/${qs ? `?${qs}` : ""}`,
  );
  if (Array.isArray(data)) {
    return { results: data, count: data.length };
  }
  return { results: data.results, count: data.count };
}

export async function markRead(ids: string[]): Promise<{ updated: number }> {
  return apiFetch<{ updated: number }>("/api/v1/notifications/seen/", {
    method: "PATCH",
    body: { seen: true, ids },
  });
}

export async function markAllRead(): Promise<{ updated: number }> {
  return apiFetch<{ updated: number }>("/api/v1/notifications/seen/", {
    method: "PATCH",
    body: { seen: true },
  });
}
