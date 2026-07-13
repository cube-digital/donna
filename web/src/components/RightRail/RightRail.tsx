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
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { GlyphSlot, GConnectorIcon } from "../Goofy";
import { apiFetch } from "../../api/client";
import { getSubscription } from "../../api/integrations";
import { getNotificationsSse } from "../../lib/sse";
import { useIntegrations } from "../../state/integrations";
import { useNotifications } from "../../state/notifications";
import { useArtifactPreview } from "../../state/artifactPreview";
import { useArtifacts } from "../../state/artifacts";
import type {
  ChannelArtifact,
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
// Attempts `GET /chat/channels/<id>/artifacts/` and renders any returned
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
      `/api/v1/chat/channels/${channelId}/artifacts/`,
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

// ── ArtifactPreviewSection ───────────────────────────────────────────────────
// Plan 13 — when the user clicks a `doc://<uuid>` chip in a message,
// `useArtifactPreview.open(id, channelId)` populates this store and we
// render the artifact's full body here. Close clears the store and
// drops back to the regular rail sections.

interface ArtifactDetail {
  id: string;
  title?: string;
  body?: string;
  status?: string;
  version?: number;
  target_doc_type?: string;
  updated_at?: string;
}

interface ArtifactPreviewSectionProps {
  /** Channel context — used as a fallback when no manual preview is open
   *  so the rail can auto-render the channel's active draft. */
  channelId?: string;
  /** Active-draft id to fall back to when nothing was manually opened. */
  fallbackArtifactId?: string | null;
}

export function ArtifactPreviewSection({
  channelId: channelIdProp,
  fallbackArtifactId,
}: ArtifactPreviewSectionProps = {}) {
  const manualArtifactId = useArtifactPreview((s) => s.artifactId);
  const manualChannelId = useArtifactPreview((s) => s.channelId);
  const close = useArtifactPreview((s) => s.close);
  const dismiss = useArtifactPreview((s) => s.dismiss);
  const openPreview = useArtifactPreview((s) => s.open);
  // Prefer the manually-opened doc:// preview; otherwise auto-render the
  // channel's active draft so the rail behaves like Claude Cowork's
  // file panel.
  const artifactId = manualArtifactId ?? fallbackArtifactId ?? null;
  const channelId = manualChannelId ?? channelIdProp ?? null;
  const isManual = !!manualArtifactId;
  const channelArtifacts = useArtifacts((s) =>
    channelIdProp ? s.byChannel[channelIdProp] : undefined,
  );
  const [artifact, setArtifact] = useState<ArtifactDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filesMenuOpen, setFilesMenuOpen] = useState(false);

  useEffect(() => {
    if (!artifactId || !channelId) {
      setArtifact(null);
      return;
    }
    setLoading(true);
    setError(null);
    let cancelled = false;
    // Workspace-scoped lookup — a doc:// chip may point at a sibling
    // channel's artifact, so the per-channel endpoint can't find it.
    void apiFetch<ArtifactDetail>(`/api/v1/chat/artifacts/${artifactId}/`)
      .then((data) => {
        if (cancelled) return;
        setArtifact(data);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        // 404 → the chip points at an artifact the agent referenced but
        // never actually persisted (or that was deleted). Show a polite
        // dead-link message rather than the raw DRF detail.
        const msg = e instanceof Error ? e.message : String(e);
        if (/404/.test(msg) || /No Artifact matches/.test(msg)) {
          setError("This document link is stale — the artifact no longer exists.");
        } else {
          setError(msg || "Could not load preview.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [artifactId, channelId]);

  if (!artifactId) return null;

  // Burger menu — list every artifact for this channel, newest first.
  const fileList: ChannelArtifact[] = (channelArtifacts ?? [])
    .slice()
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at));

  const subtitlePath = artifact?.target_doc_type
    ? `${artifact.target_doc_type}/${artifact?.title?.toLowerCase().replace(/\s+/g, "-") || "draft"}.md`
    : null;

  const onPickFile = (a: ChannelArtifact) => {
    if (!channelIdProp) return;
    openPreview(a.id, channelIdProp);
    setFilesMenuOpen(false);
  };
  const onDismiss = () => {
    if (isManual) {
      close();
    } else if (channelIdProp) {
      dismiss(channelIdProp);
    }
  };

  return (
    <section className="h-full flex flex-col">
      {/* Files toolbar — burger (left) + label + path + X (right). */}
      <div className="flex items-center gap-2 pb-2 border-b border-border-soft relative">
        <button
          type="button"
          onClick={() => setFilesMenuOpen((v) => !v)}
          aria-label="Open files menu"
          className="grid place-items-center p-1 bg-transparent border-0 text-text-2 cursor-pointer hover:text-text-0 rounded"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="3" y1="6" x2="21" y2="6" />
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="3" y1="18" x2="21" y2="18" />
          </svg>
        </button>
        <span className="text-[12.5px] font-semibold text-text-2">File</span>
        {subtitlePath ? (
          <span className="ml-1 text-[11px] font-mono text-text-3 truncate flex-1">
            {subtitlePath}
          </span>
        ) : (
          <span className="flex-1" />
        )}
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Close file panel"
          className="grid place-items-center p-1 bg-transparent border-0 text-text-3 cursor-pointer hover:text-text-0 rounded"
        >
          <GlyphSlot name="x" size={14} />
        </button>

        {filesMenuOpen && fileList.length > 0 ? (
          <div
            className="absolute top-full left-0 mt-1 w-[280px] max-h-[320px] overflow-y-auto bg-bg-1 border border-border-soft rounded-[10px] shadow-lg z-30 py-1"
            role="menu"
          >
            {fileList.map((a) => {
              const isOpen = a.id === artifactId;
              return (
                <button
                  key={a.id}
                  type="button"
                  role="menuitem"
                  onClick={() => onPickFile(a)}
                  className={
                    "w-full flex items-center gap-2 px-2.5 py-1.5 text-left text-[12.5px] " +
                    (isOpen ? "bg-ai-bg text-text-0" : "text-text-1 hover:bg-bg-2")
                  }
                >
                  <GlyphSlot name="doc" size={14} />
                  <span className="flex-1 truncate">
                    {a.title || "Untitled"}
                    {a.version ? ` · v${a.version}` : ""}
                  </span>
                  <span
                    className={
                      "text-[10px] uppercase tracking-wide " +
                      (a.status === "drafting" ? "text-ai" : "text-text-3")
                    }
                  >
                    {a.status}
                  </span>
                </button>
              );
            })}
          </div>
        ) : null}
      </div>

      {/* Title block — editorial: a grape eyebrow (type · status · version),
          the title, then a hairline rule. No boxed card. */}
      <div className="mt-2.5 px-0.5">
        <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.06em] text-ai-deep">
          <GlyphSlot name="doc" size={11} />
          <span>{artifact?.target_doc_type || "doc"}</span>
          {artifact?.status ? (
            <>
              <span className="text-text-4">·</span>
              <span>{artifact.status}</span>
            </>
          ) : null}
          {artifact?.version ? (
            <>
              <span className="text-text-4">·</span>
              <span>v{artifact.version}</span>
            </>
          ) : null}
        </div>
        <div className="mt-1 text-[16px] font-semibold text-text-0 leading-[1.25]">
          {artifact?.title || "Document"}
        </div>
        <div className="mt-2 h-px bg-border-soft" />
      </div>

      {/* Body — borderless reading page, fills remaining height */}
      <div className="mt-2 flex-1 min-h-0 overflow-y-auto px-0.5 py-1 text-[13px] leading-[1.6] text-text-1">
        {loading ? (
          <div className="text-text-3 text-[12.5px]">Loading…</div>
        ) : error ? (
          <div className="text-red-500 text-[12.5px]">{error}</div>
        ) : artifact?.body ? (
          <div className="prose prose-sm max-w-none [&_h1]:text-[15px] [&_h1]:font-semibold [&_h2]:text-[14px] [&_h2]:font-semibold">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {artifact.body}
            </ReactMarkdown>
          </div>
        ) : (
          <div className="text-text-3 text-[12.5px]">No body yet.</div>
        )}
      </div>
      {artifact?.status ? (
        <div className="mt-1.5 px-1 pt-2 border-t border-border-soft flex items-center gap-2 text-[11px] text-text-3">
          <span
            className={
              "w-2 h-2 rounded-full " +
              (artifact.status === "finalized" ? "bg-ok" : "bg-warn")
            }
          />
          <span>
            {artifact.status === "finalized" ? "Final" : "Drafting"}
            {artifact.updated_at
              ? ` · saved ${new Date(artifact.updated_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
              : ""}
          </span>
        </div>
      ) : null}
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

