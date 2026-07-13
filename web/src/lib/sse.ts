// Notifications SSE client.
//
// Why fetch + ReadableStream instead of EventSource:
//   - EventSource can't set custom headers, so JWT can't ride in
//     `Authorization`. Only a `?token=` query param works there, which
//     leaks the token into proxy access logs.
//   - The backend SSE view (server/donna/notifications/api/v1/views.py)
//     decodes `Authorization: Bearer <jwt>` itself — Django's
//     AuthenticationMiddleware doesn't run DRF auth on async views, so
//     the view reuses `donna.chat.auth.resolve_jwt_user` to resolve the
//     user from the bearer header.
//
// The wire format from server/.../services.py:create_sse_stream_multi is:
//   data: <json>\n\n            ← actual notifications (no event: line)
//   data: {"status":"…"}\n\n    ← status frames (connected, error)
// So we treat every parsed event as the same channel ("notification") —
// callers subscribe with that name. We still parse `event:` lines if the
// backend ever adds them, so this client stays forward-compatible.
//
// Reconnect with exponential backoff (500ms → 30s, jittered) on any
// transport failure, matching the strategy used by lib/ws.ts. When the
// access token isn't available yet (boot ordering with the auth store),
// we schedule a reconnect rather than permanently closing — the token
// will arrive when sign-in completes and the next attempt picks it up.

import { tryRefresh } from "../api/client";
import { getAccess } from "./auth-storage";
import { getActiveWorkspace } from "./auth-storage";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";
const STREAM_PATH = "/api/v1/notifications/stream";

export interface SseEvent {
  event: string;
  data: unknown;
  id?: string;
}

export type SseStatus = "idle" | "connecting" | "open" | "closed";

export interface SseClient {
  start(): void;
  stop(): void;
  on(event: string, handler: (data: unknown) => void): () => void;
  readonly status: SseStatus;
}

type Handler = (data: unknown) => void;

class NotificationsSseClient implements SseClient {
  status: SseStatus = "idle";
  private abort: AbortController | null = null;
  private handlers = new Map<string, Set<Handler>>();
  private backoff = 500;
  private stopped = true;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  on(event: string, handler: Handler): () => void {
    let set = this.handlers.get(event);
    if (!set) {
      set = new Set();
      this.handlers.set(event, set);
    }
    set.add(handler);
    return () => {
      set?.delete(handler);
    };
  }

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    this.backoff = 500;
    void this.connect();
  }

  stop(): void {
    this.stopped = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.abort) {
      this.abort.abort();
      this.abort = null;
    }
    this.status = "closed";
  }

  private emit(event: string, data: unknown): void {
    const set = this.handlers.get(event);
    if (!set) return;
    for (const h of set) {
      try {
        h(data);
      } catch (err) {
        console.error("[sse] handler error", event, err);
      }
    }
  }

  private async connect(): Promise<void> {
    if (this.stopped) return;
    const access = getAccess();
    if (!access) {
      // No JWT yet — auth store hasn't hydrated, or sign-in is in
      // flight. Schedule a reconnect so we pick up the token once it
      // lands instead of permanently closing.
      this.status = "connecting";
      this.scheduleReconnect();
      return;
    }

    this.status = "connecting";
    this.abort = new AbortController();

    const headers: Record<string, string> = {
      Authorization: `Bearer ${access}`,
      Accept: "text/event-stream",
    };
    const wsId = getActiveWorkspace();
    if (wsId) headers["X-Workspace-Id"] = wsId;

    try {
      const res = await fetch(`${API_BASE}${STREAM_PATH}`, {
        method: "GET",
        headers,
        signal: this.abort.signal,
        // keepalive false — we manage lifecycle explicitly.
      });

      if (res.status === 401) {
        // Access token expired. The API client refreshes on its own 401s, but
        // this reconnect loop has its own fetch — without refreshing here it
        // spins forever on the stale token. Refresh once, reset backoff, and
        // let the scheduled reconnect pick up the new token.
        const refreshed = await tryRefresh();
        if (refreshed) this.backoff = 500;
        throw new Error("sse http 401");
      }

      if (!res.ok || !res.body) {
        throw new Error(`sse http ${res.status}`);
      }

      this.status = "open";
      this.backoff = 500; // reset on successful connect
      await this.readLoop(res.body);
    } catch (err) {
      if ((err as { name?: string })?.name === "AbortError") return;
      // Fall through to reconnect.
    }

    if (this.stopped) return;
    this.status = "connecting";
    this.scheduleReconnect();
  }

  private scheduleReconnect(): void {
    const delay = Math.min(this.backoff, 30_000);
    const jitter = Math.random() * 0.25 * delay;
    this.backoff = Math.min(this.backoff * 2, 30_000);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      void this.connect();
    }, delay + jitter);
  }

  /**
   * Parse the SSE wire format from a fetch body stream.
   *
   * Events are separated by `\n\n`. Within an event each non-empty line
   * is either `event: <name>`, `data: <text>`, or `id: <text>` — the
   * spec also allows comments (`: …`) and `retry: …` which we ignore.
   *
   * The backend emits only `data:` lines today; we synthesize an event
   * name of `"notification"` (or `"status"` when the payload has a
   * top-level `status` key — that's how the backend signals connected /
   * error to the stream).
   */
  private async readLoop(body: ReadableStream<Uint8Array>): Promise<void> {
    const reader = body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let sep: number;
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        const raw = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        const parsed = this.parseFrame(raw);
        if (parsed) this.emit(parsed.event, parsed.data);
      }
    }
  }

  private parseFrame(raw: string): SseEvent | null {
    if (!raw.trim()) return null;
    let event = "notification";
    let data = "";
    let id: string | undefined;

    for (const line of raw.split("\n")) {
      if (!line || line.startsWith(":")) continue;
      const idx = line.indexOf(":");
      const field = idx === -1 ? line : line.slice(0, idx);
      const value = idx === -1 ? "" : line.slice(idx + 1).replace(/^ /, "");
      if (field === "event") event = value;
      else if (field === "data") data = data ? `${data}\n${value}` : value;
      else if (field === "id") id = value;
    }

    let parsed: unknown = data;
    if (data) {
      try {
        parsed = JSON.parse(data);
      } catch {
        // Leave as raw string.
      }
    }

    // Promote backend status frames to a separate channel so consumers
    // can opt into them without filtering noise from real notifications.
    if (event === "notification" && isStatusFrame(parsed)) {
      event = "status";
    }
    return { event, data: parsed, id };
  }
}

function isStatusFrame(payload: unknown): payload is { status: string } {
  return (
    !!payload &&
    typeof payload === "object" &&
    "status" in (payload as object) &&
    typeof (payload as { status: unknown }).status === "string"
  );
}

let _singleton: NotificationsSseClient | null = null;

export function getNotificationsSse(): SseClient {
  if (!_singleton) _singleton = new NotificationsSseClient();
  return _singleton;
}
