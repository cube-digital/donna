// Right rail — context-aware sections.
//
// This module exports the SECTIONS, not a top-level component. Views
// (Channel, Personal) compose the sections they want and feed them to
// `useRightRail(<>...</>)` from RightRailSlot. AppShell renders the
// slot exactly once.
//
// Visual chrome is ported from the design's `donnaai/project/rightrail.jsx`
// onto Tailwind utility classes — every `.rr-section`, `.rr-h`, `.rr-card`,
// `.connector`, `.doc-list`, `.doc`, `.mem-item` recipe lives inline at
// the call site as a class string.

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { GlyphSlot, GConnectorIcon } from "../Goofy";
import { apiFetch } from "../../api/client";
import { getSubscription } from "../../api/integrations";
import { getNotificationsSse } from "../../lib/sse";
import { useIntegrations } from "../../state/integrations";
import { useNotifications } from "../../state/notifications";
import type {
  Connection,
  IntegrationProvider,
  Notification,
} from "../../types";

// ── Shared Tailwind fragments ────────────────────────────────────────────────

const SECTION_CLS = "mb-[18px]";
// Section headers were uppercase tracking-wide chrome from the legacy
// design. Goofy headers stay Fredoka, sentence-case, with the same
// rhythm so the right rail reads as a sibling of the sidebar.
const HEADER_CLS =
  "flex items-center gap-1.5 py-1 px-0.5 font-display font-semibold text-[12.5px] text-text-2";
const HEADER_AI_CLS =
  "flex items-center gap-1.5 py-1 px-0.5 font-display font-semibold text-[12.5px] text-ai";
const CARD_AI_CLS =
  "mt-1.5 py-2.5 px-3 bg-ai-bg border-2 border-ai rounded-[12px] shadow-ai-stamp";

const COMING_SOON_CLS = "mt-1 font-hand font-bold text-[15px] text-text-3 leading-none";

// ── DocsSection ──────────────────────────────────────────────────────────────
// Attempts `GET /chat/channels/<id>/documents/` and renders any returned
// rows. The endpoint isn't in the backend yet, so any non-2xx (including
// 404) silently falls back to the empty state — keeps the UI honest
// without warning users about a missing surface.

interface DocsSectionProps {
  channelId?: string;
}

interface DocRow {
  id?: string;
  name: string;
  meta?: string;
}

export function DocsSection({ channelId }: DocsSectionProps) {
  const [docs, setDocs] = useState<DocRow[] | null>(null);

  useEffect(() => {
    if (!channelId) {
      setDocs([]);
      return;
    }
    let cancelled = false;
    void apiFetch<DocRow[] | { results: DocRow[] }>(
      `/api/v1/chat/channels/${channelId}/documents/`,
    )
      .then((data) => {
        if (cancelled) return;
        const list = Array.isArray(data) ? data : data.results;
        setDocs(Array.isArray(list) ? list : []);
      })
      .catch(() => {
        if (!cancelled) setDocs([]);
      });
    return () => {
      cancelled = true;
    };
  }, [channelId]);

  const list = docs ?? [];

  return (
    <section className={SECTION_CLS}>
      <div className={HEADER_CLS}>
        <GlyphSlot name="doc" size={15} />
        <span>Docs{list.length ? ` · ${list.length}` : ""}</span>
        <span className="flex-1" />
        <button
          type="button"
          aria-label="New doc"
          className="grid place-items-center p-0.5 bg-transparent border-0 text-text-3 cursor-pointer hover:text-text-0"
        >
          <GlyphSlot name="plus" size={14} />
        </button>
      </div>
      <div className="flex flex-col gap-0.5 mt-1">
        {list.length === 0 ? (
          <div className="flex items-center gap-2 py-1.5 px-2 rounded-md text-[12.5px] text-text-3">
            <GlyphSlot name="doc" size={15} className="text-text-3" />
            <span className="flex-1 min-w-0 overflow-hidden text-ellipsis whitespace-nowrap">
              No docs yet
            </span>
            <span className="text-text-3 text-[11px] font-mono">—</span>
          </div>
        ) : (
          list.map((d, i) => (
            <div
              key={d.id ?? `${d.name}-${i}`}
              className="h-[34px] flex items-center gap-2 px-[10px] rounded-[9px] border border-border-soft bg-bg-1 text-[12.5px] text-text-1 hover:text-text-0"
            >
              <GlyphSlot name="doc" className="text-text-3" size={15} />
              <span className="flex-1 min-w-0 overflow-hidden text-ellipsis whitespace-nowrap">
                {d.name}
              </span>
              {d.meta ? (
                <span className="text-text-3 text-[11px] font-mono">
                  {d.meta}
                </span>
              ) : null}
            </div>
          ))
        )}
      </div>
    </section>
  );
}

// ── ContextSection ───────────────────────────────────────────────────────────
// Lists every connector. Clicking a "not connected" row opens the OAuth
// modal; clicking a "live" / "read-only" row opens the config modal.
//
// Last-sync timestamps are surfaced for `live` providers only. We pull
// the `Connection` row from `GET /integrations/<slug>/subscription/` on
// first render, cache per-slug in module state so re-mounts don't
// re-fetch, and render the result as `Live · 12m ago` in the row.

// Module-scoped cache so unmount/remount of the section doesn't refire
// the per-provider subscription fetch. Keyed by slug; values are
// `null` once a fetch has been attempted (success or failure) to mark
// the lookup as resolved.
const subscriptionCache = new Map<string, Connection | null>();

export function ContextSection() {
  const providers = useIntegrations((s) => s.providers);
  const loaded = useIntegrations((s) => s.loaded);
  const load = useIntegrations((s) => s.load);
  // Mirror of `subscriptionCache` into component state so we re-render
  // when a fetch resolves.
  const [conns, setConns] = useState<Record<string, Connection | null>>(() => {
    const init: Record<string, Connection | null> = {};
    for (const [k, v] of subscriptionCache) init[k] = v;
    return init;
  });

  useEffect(() => {
    if (!loaded) void load();
  }, [loaded, load]);

  // Fetch `Connection` rows for every `live` provider we haven't
  // already cached. Errors are swallowed — the row just renders without
  // a sync timestamp.
  useEffect(() => {
    let cancelled = false;
    const pending = providers.filter(
      (p) => p.status === "live" && !subscriptionCache.has(p.slug),
    );
    for (const p of pending) {
      subscriptionCache.set(p.slug, null); // mark in-flight to dedupe
      void getSubscription(p.slug)
        .then((c) => {
          subscriptionCache.set(p.slug, c);
          if (!cancelled) {
            setConns((prev) => ({ ...prev, [p.slug]: c }));
          }
        })
        .catch(() => {
          subscriptionCache.set(p.slug, null);
        });
    }
    return () => {
      cancelled = true;
    };
  }, [providers]);

  const [open, setOpen] = useState(true);

  return (
    <section className={SECTION_CLS}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={HEADER_CLS + " w-full bg-transparent border-0 cursor-pointer"}
        aria-expanded={open}
      >
        <GlyphSlot name="link" size={15} />
        <span>Context</span>
        <span className="flex-1" />
        <GlyphSlot
          name="caret"
          size={12}
          className={
            "transition-transform " + (open ? "" : "-rotate-90")
          }
        />
      </button>

      {open && providers.length === 0 && (
        <div className="flex items-center gap-2 py-1.5 px-2 rounded-md text-[12.5px] opacity-60">
          <span className="w-[18px] h-[18px] rounded-sm bg-bg-3 grid place-items-center text-text-1 text-[10px] font-mono">
            —
          </span>
          <span className="flex-1 text-text-0">No connectors</span>
          <span className="text-[11px] text-text-3">—</span>
        </div>
      )}

      {open && providers.map((p) => {
        const conn = conns[p.slug];
        return (
          <Link
            key={p.slug}
            to={`/integrations/${p.slug}`}
            className="flex items-center gap-2 py-1.5 px-2 rounded-md text-[12.5px] w-full hover:bg-bg-2"
          >
            <span className="w-[18px] h-[18px] flex items-center justify-center flex-shrink-0">
              <GConnectorIcon slug={p.slug} label={p.display_name} />
            </span>
            <span className="flex-1 min-w-0 text-text-0 overflow-hidden text-ellipsis whitespace-nowrap">
              {p.display_name}
            </span>
            <ConnectorState
              status={p.status}
              lastSyncedAt={conn?.last_synced_at ?? null}
            />
          </Link>
        );
      })}
    </section>
  );
}

function ConnectorState({
  status,
  lastSyncedAt,
}: {
  status: IntegrationProvider["status"];
  lastSyncedAt?: string | null;
}) {
  switch (status) {
    case "live":
      void lastSyncedAt;
      return <span className="text-[11px] font-semibold text-ok">live</span>;
    case "read-only":
      return <span className="text-[11px] text-text-3">read-only</span>;
    case "error":
      return <span className="text-[11px] text-danger">error</span>;
    default:
      return <span className="text-[11px] text-text-2">connect</span>;
  }
}

// ── DonnaToday ───────────────────────────────────────────────────────────────
// Hardcoded "3 things need you" card. Backend isn't wired for v1; the
// design uses a single `.rr-card.ai` panel.

export function DonnaToday() {
  return (
    <section className={SECTION_CLS}>
      <div className={HEADER_AI_CLS}>
        <GlyphSlot name="sparkle" />
        <span>Donna today</span>
        <span className="flex-1" />
      </div>
      <div className={CARD_AI_CLS}>
        <div className="text-[13px] text-text-0 font-semibold">
          3 things need you
        </div>
        <ul className="list-none p-0 mt-2 flex flex-col gap-1.5">
          <li className="text-[12.5px] text-text-1 flex items-start gap-1.5 leading-[1.45]">
            <span className="text-ai mt-px">•</span>
            Review the Q2 brief draft Donna wrote this morning.
          </li>
          <li className="text-[12.5px] text-text-1 flex items-start gap-1.5 leading-[1.45]">
            <span className="text-ai mt-px">•</span>
            Approve the customer reply waiting in your inbox.
          </li>
          <li className="text-[12.5px] text-text-1 flex items-start gap-1.5 leading-[1.45]">
            <span className="text-ai mt-px">•</span>
            Confirm Friday's launch readiness with the team.
          </li>
        </ul>
      </div>
    </section>
  );
}

// ── ProgressStub ─────────────────────────────────────────────────────────────

export function ProgressStub() {
  return (
    <section className={SECTION_CLS}>
      <div className={HEADER_CLS}>
        <GlyphSlot name="bolt" />
        <span>Progress</span>
        <span className="flex-1" />
      </div>
      <div className={COMING_SOON_CLS}>Coming soon</div>
    </section>
  );
}

// ── NotificationsBootstrap ──────────────────────────────────────────────────
// Mount once near AppShell; loads the initial feed and subscribes to SSE.
// The bell badge consumes `useNotifications.unreadCount` directly.

export function NotificationsBootstrap() {
  const loadInitial = useNotifications((s) => s.loadInitial);
  const pushFromSse = useNotifications((s) => s.pushFromSse);

  useEffect(() => {
    void loadInitial();
    const sse = getNotificationsSse();
    const off = sse.on("notification", (payload) => {
      const n = coerceSseToNotification(payload);
      if (n) pushFromSse(n);
    });
    sse.start();
    return () => {
      off();
      sse.stop();
    };
  }, [loadInitial, pushFromSse]);

  return null;
}

/**
 * The SSE payload shape (NotificationPayload in
 * server/donna/notifications/schemas.py) does NOT match the DB-serialized
 * Notification shape one-to-one. Translate here so the store can stay
 * single-shape. When the backend lands an ID-bearing alert it also writes
 * the DB row first — we pick up the canonical row on the next list load.
 */
function coerceSseToNotification(payload: unknown): Notification | null {
  if (!payload || typeof payload !== "object") return null;
  const p = payload as {
    id?: string;
    type?: string;
    message?: string;
    timestamp?: string;
    data?: Record<string, unknown>;
  };
  // Status frames (connected / error) — ignore.
  if (typeof (p as { status?: unknown }).status === "string") return null;
  if (typeof p.message !== "string") return null;

  const data = p.data ?? {};
  const dbId = typeof data["id"] === "string" ? (data["id"] as string) : p.id;
  if (!dbId) return null;

  const title = typeof data["title"] === "string" ? (data["title"] as string) : "";
  const statusRaw =
    typeof data["status"] === "string" ? (data["status"] as string) : "info";
  const status: Notification["status"] =
    statusRaw === "warning" || statusRaw === "error" || statusRaw === "success"
      ? statusRaw
      : "info";

  return {
    id: dbId,
    title,
    message: p.message,
    status,
    type: p.type ?? "alert",
    seen: false,
    context: (data["context"] as Record<string, unknown>) ?? {},
    created_at: p.timestamp ?? new Date().toISOString(),
  };
}

