// Chat WebSocket client — single shared connection for the signed-in
// user. Speaks the contract documented in
// `server/donna/chat/consumers.py` (ChatConsumer): one WS at `/ws/`,
// JWT shipped via the `Sec-WebSocket-Protocol` subprotocol list
// (`["bearer", "<jwt>"]`), inbound `{action, ...}` JSON frames, outbound
// `{event, ...}` JSON frames.
//
// Lifecycle
// ─────────
// - Lazily constructed on the first `getChatWs()` call (or first
//   subscribe / send). Auto-(re)connects whenever an access token is
//   present in localStorage.
// - Reconnects with exponential backoff (1 → 2 → 4 … capped at 30s).
//   The retry counter resets to 1s on every successful `connected`
//   event.
// - 4401 = invalid token. We stop reconnect-looping in that case
//   (App.tsx wires global 401 → signOut → kicks back to /auth;
//   redoing it here would race). Other closures (1006 network drop,
//   etc.) retry indefinitely.
// - 25-second heartbeat refreshes the backend presence TTL.
// - On reconnect we resubscribe to the channels the caller asked for
//   before the drop. Callers don't need to babysit subscriptions.
//
// Fan-out
// ───────
// Multiple components subscribe to the same event via `on(event, fn)`,
// which returns an `off` function. We dispatch in the order
// listeners were registered; an error in one handler must not stop
// dispatch — they're each `try`-wrapped.
//
// Event payload note
// ──────────────────
// The consumer spreads `**payload` into each frame, so a
// `message.created` frame looks like:
//   { event: "message.created", id, channel_id, body, author_user,
//     author_agent, created_at, updated_at, client_msg_id }
// (see `_serialize_message` in `chat/services.py`). We model that as
// `EventMap["message.created"] = MessageWsPayload` and hand the
// payload straight to the messages store; UI code adapts via the
// `Message` type cast there.

import { getAccess } from "./auth-storage";
import type { ISODateTime, UUID } from "../types";

// ──────────────────────────────────────────────────────────────────────
// Event payload types
// ──────────────────────────────────────────────────────────────────────

/**
 * Wire shape of a Message inside a chat.* WS event payload.
 * Matches `donna/chat/services.py::_serialize_message` — author refs
 * are flat UUID strings, NOT nested objects (unlike REST). The
 * messages store reconciles this with the REST shape before exposing
 * to the UI.
 */
export interface MessageWsPayload {
  id: UUID;
  channel_id: UUID;
  body: string;
  author_user: UUID | null;
  author_agent: UUID | null;
  created_at: ISODateTime | null;
  updated_at: ISODateTime | null;
  client_msg_id?: string | null;
}

export interface EventMap {
  connected: { user_id: string };
  subscribed: { channel_id: string };
  unsubscribed: { channel_id: string };
  "message.created": MessageWsPayload;
  "message.updated": MessageWsPayload;
  "message.deleted": { channel_id: string; message_id: string };
  typing: { channel_id: string; user_id: string };
  presence: { user_id: string; online: boolean };
  "dm.opened": { channel_id: string; peer_user_id: string };
  "channel.created": Record<string, unknown>;
  "channel.updated": Record<string, unknown>;
  "channel.deleted": { channel_id: string };
  "channel.member.added": { channel_id: string; user_id: string };
  "channel.member.removed": { channel_id: string; user_id: string; removed_by: string };
  "channel.pinned": { channel_id: string };
  "channel.unpinned": { channel_id: string };
  "reaction.added": {
    channel_id: string;
    message_id: string;
    emoji: string;
    user_id: string;
  };
  "reaction.removed": {
    channel_id: string;
    message_id: string;
    emoji: string;
    user_id: string;
  };
  "document.updated": { channel_id: string; document: unknown };
  "read.advanced": {
    channel_id: string;
    user_id: string;
    message_id: string;
    read_at: string | null;
  };
  error: { code: string; detail: string };
}

export type ChatWsAction =
  | "send_message"
  | "typing"
  | "mark_read"
  | "edit_message"
  | "delete_message"
  | "open_dm"
  | "heartbeat";

type ConnectionStatus = "connecting" | "open" | "closed";

export interface ChatWsClient {
  subscribe(channelId: string): void;
  unsubscribe(channelId: string): void;
  send(action: ChatWsAction, payload?: Record<string, unknown>): void;
  on<E extends keyof EventMap>(
    event: E,
    handler: (e: EventMap[E]) => void,
  ): () => void;
  readonly status: ConnectionStatus;
}

// ──────────────────────────────────────────────────────────────────────
// Internal client
// ──────────────────────────────────────────────────────────────────────

const HEARTBEAT_MS = 25_000;
const BACKOFF_MIN_MS = 1_000;
const BACKOFF_MAX_MS = 30_000;

function buildWsUrl(): string {
  const envBase = (import.meta.env.VITE_WS_BASE ?? "").trim();
  if (envBase) {
    return envBase.replace(/\/+$/, "") + "/ws/";
  }
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/ws/`;
}

type Listener<E extends keyof EventMap> = (e: EventMap[E]) => void;

class Client implements ChatWsClient {
  private ws: WebSocket | null = null;
  private _status: ConnectionStatus = "closed";
  private listeners: Map<keyof EventMap, Set<Listener<keyof EventMap>>> =
    new Map();
  /** Channels the caller wants us to be subscribed to. We resubscribe
   *  to every entry on reconnect; calls to `subscribe` are idempotent. */
  private wantedSubs: Set<string> = new Set();
  /** Subset confirmed by the server (received `subscribed` ack). */
  private ackedSubs: Set<string> = new Set();
  private backoffMs = BACKOFF_MIN_MS;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  /** Token was invalid; do not reconnect until externally reset. */
  private dead = false;

  get status(): ConnectionStatus {
    return this._status;
  }

  // ── Public API ──────────────────────────────────────────────────────
  subscribe(channelId: string): void {
    this.wantedSubs.add(channelId);
    this.ensureOpen();
    if (this._status === "open" && !this.ackedSubs.has(channelId)) {
      this.sendRaw({ action: "subscribe_channel", channel_id: channelId });
    }
  }

  unsubscribe(channelId: string): void {
    this.wantedSubs.delete(channelId);
    if (this._status === "open" && this.ackedSubs.has(channelId)) {
      this.sendRaw({ action: "unsubscribe_channel", channel_id: channelId });
      this.ackedSubs.delete(channelId);
    }
  }

  send(action: ChatWsAction, payload: Record<string, unknown> = {}): void {
    this.ensureOpen();
    this.sendRaw({ action, ...payload });
  }

  on<E extends keyof EventMap>(event: E, handler: Listener<E>): () => void {
    let set = this.listeners.get(event);
    if (!set) {
      set = new Set();
      this.listeners.set(event, set);
    }
    set.add(handler as Listener<keyof EventMap>);
    return () => {
      const s = this.listeners.get(event);
      if (s) s.delete(handler as Listener<keyof EventMap>);
    };
  }

  // ── Lifecycle ───────────────────────────────────────────────────────
  closeForTeardown(): void {
    this.dead = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.stopHeartbeat();
    if (this.ws) {
      try {
        this.ws.close(1000, "client teardown");
      } catch {
        /* ignore */
      }
      this.ws = null;
    }
    this._status = "closed";
    this.listeners.clear();
    this.wantedSubs.clear();
    this.ackedSubs.clear();
  }

  // ── Internals ───────────────────────────────────────────────────────
  private ensureOpen(): void {
    if (this.dead) return;
    if (this._status === "open" || this._status === "connecting") return;
    this.connect();
  }

  private connect(): void {
    if (this.dead) return;
    const token = getAccess();
    if (!token) {
      // No token → don't bother. Caller will retry once user signs in.
      this._status = "closed";
      return;
    }

    this._status = "connecting";
    const url = buildWsUrl();
    let ws: WebSocket;
    try {
      ws = new WebSocket(url, ["bearer", token]);
    } catch (err) {
      // Some browsers throw synchronously on bad URLs / bad subprotocol
      // strings (e.g. token with whitespace). Treat as a transient
      // failure and retry on backoff.
      console.warn("ws_construct_failed", err);
      this.scheduleReconnect();
      return;
    }
    this.ws = ws;

    ws.onopen = () => {
      // The "open" handshake completes — we still haven't received the
      // `connected` event. We flip status here so `subscribe()` can
      // start emitting, and consumers can branch on status.
      this._status = "open";
      this.backoffMs = BACKOFF_MIN_MS;
      this.startHeartbeat();
      // Resubscribe to wanted channels.
      for (const cid of this.wantedSubs) {
        this.sendRaw({ action: "subscribe_channel", channel_id: cid });
      }
    };

    ws.onmessage = (ev) => {
      const raw = typeof ev.data === "string" ? ev.data : "";
      if (!raw) return;
      let frame: Record<string, unknown>;
      try {
        frame = JSON.parse(raw) as Record<string, unknown>;
      } catch {
        return;
      }
      const event = frame.event as keyof EventMap | undefined;
      if (!event) return;

      // Ack tracking for subscriptions.
      if (event === "subscribed" && typeof frame.channel_id === "string") {
        this.ackedSubs.add(frame.channel_id);
      } else if (
        event === "unsubscribed" &&
        typeof frame.channel_id === "string"
      ) {
        this.ackedSubs.delete(frame.channel_id);
      }

      // The frame *is* the payload (consumer spread `**payload`). We
      // hand the whole frame (minus `event`) to listeners.
      const { event: _, ...payload } = frame;
      void _;
      const set = this.listeners.get(event);
      if (!set) return;
      for (const handler of set) {
        try {
          (handler as Listener<typeof event>)(
            payload as unknown as EventMap[typeof event],
          );
        } catch (err) {
          console.error("ws_listener_error", { event, err });
        }
      }
    };

    ws.onerror = () => {
      // The browser doesn't expose useful detail here; the subsequent
      // `onclose` will trigger reconnect logic.
    };

    ws.onclose = (ev) => {
      this.stopHeartbeat();
      this.ws = null;
      this._status = "closed";
      this.ackedSubs.clear();
      // 4401 — backend rejected the token. Stop reconnecting; the rest
      // of the app handles auth flow on the next HTTP call.
      if (ev.code === 4401) {
        this.dead = true;
        return;
      }
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    if (this.dead) return;
    if (this.reconnectTimer) return;
    const delay = this.backoffMs;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.backoffMs = Math.min(this.backoffMs * 2, BACKOFF_MAX_MS);
      this.connect();
    }, delay);
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      if (this._status !== "open") return;
      this.sendRaw({ action: "heartbeat" });
    }, HEARTBEAT_MS);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private sendRaw(frame: Record<string, unknown>): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    try {
      this.ws.send(JSON.stringify(frame));
    } catch (err) {
      console.warn("ws_send_failed", err);
    }
  }
}

// ──────────────────────────────────────────────────────────────────────
// Singleton
// ──────────────────────────────────────────────────────────────────────

let singleton: Client | null = null;

export function getChatWs(): ChatWsClient {
  if (!singleton) singleton = new Client();
  return singleton;
}

/** Close the underlying socket — invoke on signOut so the next user
 *  doesn't inherit subscriptions / heartbeat tied to a different JWT. */
export function closeChatWs(): void {
  if (!singleton) return;
  singleton.closeForTeardown();
  singleton = null;
}
