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
  ChannelArtifact,
  Message,
  Paginated,
  ReactionAgg,
  UUID,
} from "../types";

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

// ── DMs ─────────────────────────────────────────────────────────────────────

export async function startDM(peerUserId: UUID): Promise<Channel> {
  return apiFetch<Channel>("/api/v1/chat/dms/", {
    method: "POST",
    body: { peer_user_id: peerUserId },
  });
}

export async function startGroupDM(peerUserIds: UUID[]): Promise<Channel> {
  return apiFetch<Channel>("/api/v1/chat/dms/group/", {
    method: "POST",
    body: { peer_user_ids: peerUserIds },
  });
}

// ── Pins ────────────────────────────────────────────────────────────────────

export async function pinChannel(channelId: UUID): Promise<void> {
  await apiFetch(`/api/v1/chat/channels/${channelId}/pin/`, { method: "POST" });
}

export async function unpinChannel(channelId: UUID): Promise<void> {
  await apiFetch(`/api/v1/chat/channels/${channelId}/pin/`, { method: "DELETE" });
}

// ── Channel members ───────────────────────────────────────────────────────

export interface ChannelMemberRow {
  id: UUID;
  user: {
    id: UUID;
    email: string;
    full_name: string;
    picture_url: string | null;
    is_away: boolean;
    status: string;
  };
  role: "admin" | "member";
  created_at: string;
}

export async function listChannelMembers(
  channelId: UUID,
): Promise<ChannelMemberRow[]> {
  const data = await apiFetch<ChannelMemberRow[] | { results: ChannelMemberRow[] }>(
    `/api/v1/chat/channels/${channelId}/members/`,
  );
  return Array.isArray(data) ? data : data.results;
}

export async function addChannelMember(
  channelId: UUID,
  userId: UUID,
  role: "admin" | "member" = "member",
): Promise<void> {
  await apiFetch(`/api/v1/chat/channels/${channelId}/members/`, {
    method: "POST",
    body: { user_id: userId, role },
  });
}

export async function updateChannelMemberRole(
  channelId: UUID,
  userId: UUID,
  role: "admin" | "member",
): Promise<ChannelMemberRow> {
  return apiFetch<ChannelMemberRow>(
    `/api/v1/chat/channels/${channelId}/members/${userId}/`,
    { method: "PATCH", body: { role } },
  );
}

export async function removeChannelMember(
  channelId: UUID,
  userId: UUID,
): Promise<void> {
  await apiFetch(`/api/v1/chat/channels/${channelId}/members/${userId}/`, {
    method: "DELETE",
  });
}

// ── Threading ────────────────────────────────────────────────────────────

export async function getReplies(messageId: UUID): Promise<Message[]> {
  const data = await apiFetch<Message[] | Paginated<Message>>(
    `/api/v1/chat/messages/${messageId}/replies/`,
  );
  return Array.isArray(data) ? data : data.results;
}

export async function postReply(
  channelId: UUID,
  parentMessageId: UUID,
  body: string,
  clientMsgId?: string,
): Promise<Message> {
  return apiFetch<Message>(`/api/v1/chat/channels/${channelId}/messages/`, {
    method: "POST",
    body: {
      body,
      parent_id: parentMessageId,
      ...(clientMsgId ? { client_msg_id: clientMsgId } : {}),
    },
  });
}

// ── Reactions ────────────────────────────────────────────────────────────

export async function addReaction(messageId: UUID, emoji: string): Promise<ReactionAgg> {
  return apiFetch<ReactionAgg>(`/api/v1/chat/messages/${messageId}/reactions/`, {
    method: "POST",
    body: { emoji },
  });
}

export async function removeReaction(messageId: UUID, emoji: string): Promise<void> {
  await apiFetch(`/api/v1/chat/messages/${messageId}/reactions/`, {
    method: "DELETE",
    body: { emoji },
  });
}

// ── Channel documents (Cowork rail) ──────────────────────────────────────

export async function listChannelArtifacts(
  channelId: UUID,
  status?: "drafting" | "finalized" | "abandoned",
): Promise<ChannelArtifact[]> {
  const qs = status ? `?status=${status}` : "";
  const data = await apiFetch<ChannelArtifact[] | Paginated<ChannelArtifact>>(
    `/api/v1/chat/channels/${channelId}/artifacts/${qs}`,
  );
  return Array.isArray(data) ? data : data.results;
}

export async function getChannelArtifact(
  channelId: UUID,
  documentId: UUID,
): Promise<ChannelArtifact> {
  return apiFetch<ChannelArtifact>(
    `/api/v1/chat/channels/${channelId}/artifacts/${documentId}/`,
  );
}

export interface MentionCandidate {
  kind: "agent" | "user" | "special";
  id: string;
  handle: string;
  label: string;
  email?: string;
}

export async function getMentionCandidates(
  channelId: UUID,
  q = "",
  limit = 20,
): Promise<MentionCandidate[]> {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  params.set("limit", String(limit));
  const data = await apiFetch<{ data: MentionCandidate[] }>(
    `/api/v1/chat/channels/${channelId}/mention-candidates/?${params}`,
  );
  return data.data ?? [];
}

// ── Plan 13 §1.3 / §1.5 — HIL answer endpoint ─────────────────────────────
export interface AnswerQuestionBody {
  value: string | null;
  text?: string | null;
}

export interface AnswerQuestionResponse {
  question_id: UUID;
  answer_id: UUID;
  answer_payload: { value: string | null; text: string | null };
}

export async function answerQuestion(
  questionId: UUID,
  body: AnswerQuestionBody,
): Promise<AnswerQuestionResponse> {
  return apiFetch<AnswerQuestionResponse>(
    `/api/v1/chat/messages/${questionId}/answer/`,
    { method: "POST", body },
  );
}

// ── Plan 13 §5.2.2 — channel-resident agent install / uninstall ──────────
export interface ChannelAgentInstall {
  session_id: UUID;
  handle: string;
  name: string;
}

export async function installChannelAgent(
  channelId: UUID,
  payload: { handle: string; name?: string },
): Promise<ChannelAgentInstall> {
  return apiFetch<ChannelAgentInstall>(
    `/api/v1/chat/channels/${channelId}/agents/install/`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export async function uninstallChannelAgent(
  channelId: UUID,
  handle: string,
): Promise<void> {
  await apiFetch<void>(
    `/api/v1/chat/channels/${channelId}/agents/${handle}/`,
    { method: "DELETE" },
  );
}
