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
import type {
  Channel,
  ChannelMembership,
  ChannelMemberRole,
  Message,
  Paginated,
} from "../types";

export interface ListChannelsOpts {
  /** Browse-public mode — also returns public channels the user isn't a member of. */
  includePublic?: boolean;
}

export async function listChannels(opts: ListChannelsOpts = {}): Promise<Channel[]> {
  // Donna's renderer puts rows directly in `data` (pagination in `meta`),
  // so what comes out of apiFetch IS the array. Tolerate `{results}` too
  // for future-proofing.
  const qs = opts.includePublic ? "?include_public=true" : "";
  const data = await apiFetch<Channel[] | Paginated<Channel>>(
    `/api/v1/chat/channels/${qs}`,
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

// ── Membership ──────────────────────────────────────────────────────────────
// Backed by ChannelMembersView + ChannelMemberRemoveView in
// server/donna/chat/api/v1/views.py. Server enforces:
// - GET requires channel membership (403 otherwise)
// - POST with body.user_id requires the caller to be channel admin
// - POST with empty body is self-join (public channels only; guests
//   denied at the workspace level)
// - DELETE on self is leave; DELETE on others requires admin role

/** List every membership row on a channel (caller must be a member). */
export async function listMembers(
  channelId: string,
): Promise<ChannelMembership[]> {
  return apiFetch<ChannelMembership[]>(
    `/api/v1/chat/channels/${channelId}/members/`,
  );
}

/** Admin invites a user. Backend dual-broadcasts so the invitee's WS
 *  fires `channel.added.to_you` on `presence-user-{uid}`. */
export async function addMember(
  channelId: string,
  userId: string,
  role: ChannelMemberRole = "member",
): Promise<ChannelMembership> {
  return apiFetch<ChannelMembership>(
    `/api/v1/chat/channels/${channelId}/members/`,
    { method: "POST", body: { user_id: userId, role } },
  );
}

/** Self-join a public channel (body intentionally empty). */
export async function joinChannel(
  channelId: string,
): Promise<ChannelMembership> {
  return apiFetch<ChannelMembership>(
    `/api/v1/chat/channels/${channelId}/members/`,
    { method: "POST", body: {} },
  );
}

/** Leave (when `userId` matches caller) or admin-kick (otherwise).
 *  204 No Content on success. */
export async function removeMember(
  channelId: string,
  userId: string,
): Promise<void> {
  await apiFetch<void>(
    `/api/v1/chat/channels/${channelId}/members/${userId}/`,
    { method: "DELETE" },
  );
}

// ── DMs ─────────────────────────────────────────────────────────────────────

/** Open or create the 1:1 DM channel between the caller and ``peerUserId``
 *  in the active workspace (header-tenanted). Idempotent: hitting the
 *  endpoint twice with the same peer returns the same channel. */
export async function openDM(peerUserId: string): Promise<Channel> {
  return apiFetch<Channel>("/api/v1/chat/dms/", {
    method: "POST",
    body: { peer_user_id: peerUserId },
  });
}

/** Open or create a group DM with N peers (caller is added implicitly).
 *  Exact-set-match: a group DM already containing exactly this member
 *  set is returned; a subset isn't a match. */
export async function openGroupDM(
  peerUserIds: string[],
): Promise<Channel> {
  return apiFetch<Channel>("/api/v1/chat/dms/group/", {
    method: "POST",
    body: { peer_user_ids: peerUserIds },
  });
}
