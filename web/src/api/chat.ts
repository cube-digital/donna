// Chat HTTP endpoints — backed by server/donna/chat/api/v1/views.py.
//
// HTTP is used for history pagination + the no-WS-fallback path. The
// preferred send path is the WS `send_message` action in lib/ws.ts;
// `postMessage` here exists for parity / future fallback.
//
// `X-Workspace-Id` is attached automatically by apiFetch from the
// workspace store; channels are scoped server-side via
// WorkspaceMiddleware + the channel queryset.

import { apiFetch } from "./client";
import type { Channel, Message, Paginated } from "../types";

export async function listChannels(): Promise<Channel[]> {
  // Donna's renderer puts rows directly in `data` (pagination in `meta`),
  // so what comes out of apiFetch IS the array. Tolerate `{results}` too
  // for future-proofing.
  const data = await apiFetch<Channel[] | Paginated<Channel>>(
    "/api/v1/chat/channels/",
  );
  return Array.isArray(data) ? data : data.results;
}

export async function getChannel(id: string): Promise<Channel> {
  return apiFetch<Channel>(`/api/v1/chat/channels/${id}/`);
}

export interface CreateChannelInput {
  name: string;
  slug?: string;
  topic?: string;
  visibility?: "public" | "private";
}

export async function createChannel(input: CreateChannelInput): Promise<Channel> {
  return apiFetch<Channel>("/api/v1/chat/channels/", {
    method: "POST",
    body: input,
  });
}

export interface UpdateChannelInput {
  name?: string;
  slug?: string;
  topic?: string;
  visibility?: "public" | "private";
}

export async function updateChannel(
  id: string,
  input: UpdateChannelInput,
): Promise<Channel> {
  return apiFetch<Channel>(`/api/v1/chat/channels/${id}/`, {
    method: "PATCH",
    body: input,
  });
}

export async function deleteChannel(id: string): Promise<void> {
  await apiFetch<void>(`/api/v1/chat/channels/${id}/`, { method: "DELETE" });
}

/**
 * Fetch a page of messages for a channel.
 *
 * The backend (`ChannelMessageListCreateView.get`) returns a plain
 * array already sorted oldest-first (it queries `-created_at` then
 * reverses). It is *not* DRF-paginated, so there's no `results` /
 * `next`. We tolerate either shape so a future refactor to drf
 * pagination doesn't break callers.
 */
export async function getMessages(
  channelId: string,
  opts: { before?: string; limit?: number } = {},
): Promise<{ results: Message[]; next: string | null }> {
  const q = new URLSearchParams();
  if (opts.before) q.set("before", opts.before);
  if (opts.limit !== undefined) q.set("limit", String(opts.limit));
  const qs = q.toString();
  const url = `/api/v1/chat/channels/${channelId}/messages/${qs ? `?${qs}` : ""}`;
  const data = await apiFetch<Message[] | Paginated<Message>>(url);
  if (Array.isArray(data)) {
    return { results: data, next: null };
  }
  return { results: data.results, next: data.next };
}

/**
 * HTTP fallback for sending a message. Most code paths should go
 * through the WS (`ChatWsClient.send("send_message", …)`); both call
 * into the same `ChannelService.send_message` server-side.
 */
export async function postMessage(
  channelId: string,
  body: string,
  clientMsgId?: string,
): Promise<Message> {
  return apiFetch<Message>(`/api/v1/chat/channels/${channelId}/messages/`, {
    method: "POST",
    body: {
      body,
      ...(clientMsgId ? { client_msg_id: clientMsgId } : {}),
    },
  });
}

/** Advance the (user, channel) read pointer to a specific message id. */
export async function markRead(
  channelId: string,
  messageId: string,
): Promise<void> {
  await apiFetch(`/api/v1/chat/channels/${channelId}/read-state/`, {
    method: "POST",
    body: { message_id: messageId },
  });
}
