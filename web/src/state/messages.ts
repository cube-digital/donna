// Per-channel message store.
//
// Two write paths:
//   1. REST history load  → loadInitial / loadMore  (full Message rows)
//   2. WebSocket events   → appendFromEvent / updateFromEvent /
//                            removeFromEvent  (MessageWsPayload — flat
//                            author IDs, no nested user/agent object).
//
// Both shapes are normalised into the UI `Message` type that
// `types/index.ts` describes — the WS payload's flat `author_user`
// /`author_agent` UUIDs become minimal stub objects that the UI
// renders as "Unknown" until a REST refresh hydrates the real
// User / AgentRef. (We don't have a /users/{id} fetch wired in v1.
// In practice, history load drives author display; WS events for
// brand-new authors are rare.)
//
// Agent-run detection
// ───────────────────
// The backend doesn't carry a `kind` field on `Message`. We classify
// messages client-side. The rule is:
//
//   - If `author_user` is null and `author_agent` is set AND the body
//     parses as JSON with `{ "kind": "agent-run", ... }`, the message
//     renders as an agent-run card.
//   - Otherwise, the message renders as a regular `"msg"`.
//
// This means: the backend AI worker writes an agent-run by posting a
// Message whose `body` is a JSON-encoded `AgentRunMetadata` blob (plus
// `kind: "agent-run"`). When a real `AgentRun` model lands, we lift
// this rule into a serializer field and delete the parse.
//
// `kind` and `metadata` are stripped before write to the wire (they're
// purely client-derived); we recompute them in `normalize()`.

import { create } from "zustand";

import { getMessages } from "../api/chat";
import type {
  AgentRunMetadata,
  Message,
  MessageKind,
} from "../types";
import type { MessageWsPayload } from "../lib/ws";

interface MessagesState {
  /** Per-channel ordered list, oldest → newest. */
  byChannel: Record<string, Message[]>;
  loading: Record<string, boolean>;
  loadInitial(channelId: string): Promise<void>;
  loadMore(channelId: string, beforeId: string): Promise<void>;
  appendFromEvent(channelId: string, payload: MessageWsPayload): void;
  updateFromEvent(channelId: string, payload: MessageWsPayload): void;
  removeFromEvent(channelId: string, msgId: string): void;
  optimisticInsert(channelId: string, draft: Message): void;
  reconcileOptimistic(
    channelId: string,
    clientMsgId: string,
    real: Message,
  ): void;
}

// ── Helpers ───────────────────────────────────────────────────────────

/**
 * Classify a message body. See module docstring above.
 *
 * Anti-mistake guard: we only attempt JSON.parse on bodies that *look*
 * like JSON (start with `{`) AND come from an agent author — sparing
 * the parser from running on every plain-text human message.
 */
function classifyBody(msg: {
  body: string;
  author_user: unknown;
  author_agent: unknown;
}): { kind: MessageKind; metadata?: AgentRunMetadata } {
  if (!msg.author_agent || msg.author_user) {
    return { kind: "msg" };
  }
  const body = (msg.body ?? "").trimStart();
  if (!body.startsWith("{")) return { kind: "msg" };
  try {
    const parsed = JSON.parse(body) as Record<string, unknown>;
    if (parsed && parsed["kind"] === "agent-run") {
      const { kind: _ignored, ...rest } = parsed;
      void _ignored;
      return { kind: "agent-run", metadata: rest as AgentRunMetadata };
    }
  } catch {
    /* not JSON — fall through */
  }
  return { kind: "msg" };
}

/** Apply `kind` / `metadata` to a REST-shape Message. */
function normalize(msg: Message): Message {
  const cls = classifyBody({
    body: msg.body,
    author_user: msg.author_user,
    author_agent: msg.author_agent,
  });
  return { ...msg, kind: cls.kind, metadata: cls.metadata };
}

/**
 * Turn a WS payload into a UI Message. WS payloads carry author refs
 * as flat UUIDs; we synthesize minimal stubs. Authoritative author
 * objects come back via REST history load.
 */
function fromEvent(payload: MessageWsPayload): Message {
  // Caller contract: only invoked for message.created / message.updated
  // events where id + body are always present.
  const msg: Message = {
    id: payload.id!,
    channel: payload.channel_id,
    body: payload.body!,
    author_user: payload.author_user
      ? {
          id: payload.author_user,
          email: "",
          full_name: "",
          email_verified: false,
        }
      : null,
    author_agent: payload.author_agent
      ? { id: payload.author_agent, name: "" }
      : null,
    created_at: payload.created_at ?? new Date().toISOString(),
    updated_at: payload.updated_at ?? new Date().toISOString(),
    client_msg_id: payload.client_msg_id ?? null,
  };
  return normalize(msg);
}

/** Insertion-sort a single message into a sorted list, dedup on id. */
function insertSorted(list: Message[], msg: Message): Message[] {
  const idx = list.findIndex((m) => m.id === msg.id);
  if (idx >= 0) {
    const copy = list.slice();
    copy[idx] = msg;
    return copy;
  }
  // Most appends are newest-at-end → fast path.
  if (list.length === 0 || list[list.length - 1].created_at <= msg.created_at) {
    return [...list, msg];
  }
  // Find first message with created_at > msg.created_at and insert before it.
  const i = list.findIndex((m) => m.created_at > msg.created_at);
  if (i < 0) return [...list, msg];
  return [...list.slice(0, i), msg, ...list.slice(i)];
}

// ── Store ─────────────────────────────────────────────────────────────

export const useMessages = create<MessagesState>((set, get) => ({
  byChannel: {},
  loading: {},

  loadInitial: async (channelId) => {
    set((s) => ({ loading: { ...s.loading, [channelId]: true } }));
    try {
      const { results } = await getMessages(channelId, { limit: 50 });
      const normalised = results.map(normalize);
      set((s) => ({
        byChannel: { ...s.byChannel, [channelId]: normalised },
        loading: { ...s.loading, [channelId]: false },
      }));
    } catch {
      set((s) => ({ loading: { ...s.loading, [channelId]: false } }));
    }
  },

  loadMore: async (channelId, beforeId) => {
    set((s) => ({ loading: { ...s.loading, [channelId]: true } }));
    try {
      const { results } = await getMessages(channelId, {
        before: beforeId,
        limit: 50,
      });
      const normalised = results.map(normalize);
      set((s) => {
        const existing = s.byChannel[channelId] ?? [];
        // Older messages come back oldest-first; prepend, dedupe by id.
        const existingIds = new Set(existing.map((m) => m.id));
        const additions = normalised.filter((m) => !existingIds.has(m.id));
        return {
          byChannel: {
            ...s.byChannel,
            [channelId]: [...additions, ...existing],
          },
          loading: { ...s.loading, [channelId]: false },
        };
      });
    } catch {
      set((s) => ({ loading: { ...s.loading, [channelId]: false } }));
    }
  },

  appendFromEvent: (channelId, payload) => {
    const incoming = fromEvent(payload);
    const list = get().byChannel[channelId] ?? [];

    // Dedupe optimistic inserts via client_msg_id.
    if (incoming.client_msg_id) {
      const optimisticIdx = list.findIndex(
        (m) => m.client_msg_id === incoming.client_msg_id,
      );
      if (optimisticIdx >= 0) {
        const copy = list.slice();
        // Preserve the optimistic message's author hydration (we
        // optimistically wrote the real User), but adopt the real
        // server-assigned id, timestamps, and body.
        copy[optimisticIdx] = {
          ...copy[optimisticIdx],
          ...incoming,
          author_user: copy[optimisticIdx].author_user ?? incoming.author_user,
          author_agent:
            copy[optimisticIdx].author_agent ?? incoming.author_agent,
        };
        set((s) => ({
          byChannel: { ...s.byChannel, [channelId]: copy },
        }));
        return;
      }
    }

    set((s) => ({
      byChannel: {
        ...s.byChannel,
        [channelId]: insertSorted(list, incoming),
      },
    }));
  },

  updateFromEvent: (channelId, payload) => {
    const incoming = fromEvent(payload);
    set((s) => {
      const list = s.byChannel[channelId] ?? [];
      const idx = list.findIndex((m) => m.id === incoming.id);
      if (idx < 0) return s;
      const copy = list.slice();
      copy[idx] = {
        ...copy[idx],
        ...incoming,
        // Don't downgrade an already-hydrated author.
        author_user: copy[idx].author_user ?? incoming.author_user,
        author_agent: copy[idx].author_agent ?? incoming.author_agent,
      };
      return { byChannel: { ...s.byChannel, [channelId]: copy } };
    });
  },

  removeFromEvent: (channelId, msgId) => {
    set((s) => {
      const list = s.byChannel[channelId];
      if (!list) return s;
      const next = list.filter((m) => m.id !== msgId);
      if (next.length === list.length) return s;
      return { byChannel: { ...s.byChannel, [channelId]: next } };
    });
  },

  optimisticInsert: (channelId, draft) => {
    const normalised = normalize(draft);
    set((s) => {
      const list = s.byChannel[channelId] ?? [];
      return {
        byChannel: {
          ...s.byChannel,
          [channelId]: insertSorted(list, normalised),
        },
      };
    });
  },

  reconcileOptimistic: (channelId, clientMsgId, real) => {
    const normalised = normalize(real);
    set((s) => {
      const list = s.byChannel[channelId] ?? [];
      const idx = list.findIndex((m) => m.client_msg_id === clientMsgId);
      if (idx < 0) {
        // Optimistic wasn't there (maybe already replaced by WS event).
        // Just ensure the real one is present.
        return {
          byChannel: {
            ...s.byChannel,
            [channelId]: insertSorted(list, normalised),
          },
        };
      }
      const copy = list.slice();
      copy[idx] = normalised;
      return { byChannel: { ...s.byChannel, [channelId]: copy } };
    });
  },
}));
