// Per-integration modal — opened from the ContextSection rows in the right
// rail. Shows status, scope, and either a "Connect" button (triggers OAuth
// in a popup) or a disconnect + raw-config view for live providers.
//
// The OAuth flow is:
//   1. POST /integrations/<slug>/connect/  →  { authorize_url }
//   2. window.open(authorize_url, "_blank", "width=520,height=620")
//   3. Backend handles the OAuth dance, then 302s to /oauth/return on
//      the frontend, which posts a `donna.oauth.return` message to
//      window.opener (this window) and closes itself.
//   4. We listen for the message and refresh the integrations store.
//
// JSON-schema-driven config editing is deferred to v2; we show the raw
// `Connection.config` as a <pre> block + a stub "Configure" button so
// the surface area exists.

import { useCallback, useEffect, useState } from "react";

import {
  connectIntegration,
  disconnectIntegration,
  getSubscription,
} from "../../api/integrations";
import { useIntegrations } from "../../state/integrations";
import type { Connection, IntegrationProvider } from "../../types";

interface IntegrationModalProps {
  provider: IntegrationProvider;
  onClose: () => void;
}

interface OAuthReturnMessage {
  kind?: string;
  status?: string;
  slug?: string | null;
  error?: string | null;
  detail?: string | null;
}

/** Short relative time ("just now", "12m ago", "2h ago", …). */
function humanizeTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const diffMs = Date.now() - d.getTime();
  const sec = Math.round(diffMs / 1000);
  if (sec < 60) return "just now";
  const min = Math.round(sec / 60);
  if (min < 60) return `${min} min ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr} hr ago`;
  const day = Math.round(hr / 24);
  if (day < 7) return `${day} days ago`;
  return d.toLocaleString();
}

// ── Shared Tailwind fragments ────────────────────────────────────────────────

const PRIMARY_BTN =
  "text-[13px] py-2 px-4 rounded-lg border border-text-0 bg-text-0 text-bg-0 cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed";
const DANGER_BTN =
  "text-[13px] py-2 px-3.5 rounded-lg border border-border-strong bg-bg-2 text-text-0 cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed";
const CONFIGURE_BTN =
  "text-[13px] py-2 px-3.5 rounded-lg border border-border-strong bg-bg-2 text-text-1 opacity-50 cursor-not-allowed";

export default function IntegrationModal({
  provider,
  onClose,
}: IntegrationModalProps) {
  const reloadProviders = useIntegrations((s) => s.load);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [conn, setConn] = useState<Connection | null>(null);
  const [popup, setPopup] = useState<Window | null>(null);

  const isConnected =
    provider.status === "live" || provider.status === "read-only";

  // Listen for the post-OAuth callback message from /oauth/return.
  useEffect(() => {
    function onMsg(e: MessageEvent) {
      if (e.origin !== window.location.origin) return;
      const payload = e.data as OAuthReturnMessage | undefined;
      if (payload?.kind !== "donna.oauth.return") return;
      setBusy(false);
      setPopup(null);
      if (payload.status === "ok") {
        void reloadProviders();
        // Optimistically refetch the subscription so the modal shows
        // the new Connection without an extra click.
        void getSubscription(provider.slug)
          .then(setConn)
          .catch(() => {});
      } else if (payload.status === "error") {
        // Backend redirect carries `?detail=<msg>` (see oauth.py); the
        // /oauth/return view posts that into the message body.
        setErr(payload.detail || payload.error || "OAuth failed.");
      } else if (payload.error) {
        setErr(payload.error);
      }
    }
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, [provider.slug, reloadProviders]);

  // Pull the existing Connection row for connected providers so we can
  // surface `last_synced_at` + the raw config blob.
  useEffect(() => {
    if (!isConnected) {
      setConn(null);
      return;
    }
    let cancelled = false;
    void getSubscription(provider.slug)
      .then((c) => {
        if (!cancelled) setConn(c);
      })
      .catch(() => {
        if (!cancelled) setConn(null);
      });
    return () => {
      cancelled = true;
    };
  }, [isConnected, provider.slug]);

  const handleConnect = useCallback(async () => {
    setBusy(true);
    setErr(null);
    try {
      const { authorize_url } = await connectIntegration(provider.slug);
      const w = window.open(
        authorize_url,
        "_blank",
        "width=520,height=620,noopener=no",
      );
      if (!w) {
        setErr("Couldn't open the OAuth popup — check your browser settings.");
        setBusy(false);
        return;
      }
      setPopup(w);
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  }, [provider.slug]);

  const handleDisconnect = useCallback(async () => {
    const ok = window.confirm(
      `Disconnect ${provider.display_name}? Donna will stop receiving updates from this account.`,
    );
    if (!ok) return;
    setBusy(true);
    setErr(null);
    try {
      await disconnectIntegration(provider.slug);
      await reloadProviders();
      setConn(null);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [provider.slug, provider.display_name, reloadProviders]);

  // Detect popup-closed-without-completion so the button is re-enabled.
  useEffect(() => {
    if (!popup) return;
    const t = setInterval(() => {
      if (popup.closed) {
        setBusy(false);
        setPopup(null);
        clearInterval(t);
      }
    }, 500);
    return () => clearInterval(t);
  }, [popup]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`${provider.display_name} integration`}
      className="fixed inset-0 z-50 grid place-items-center bg-black/40"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="bg-bg-1 border border-border-strong rounded-xl shadow-elevated w-[480px] max-w-[90vw] overflow-hidden">
        <div className="flex items-start justify-between py-4 px-[18px] border-b border-border-soft">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-lg bg-bg-3 grid place-items-center text-text-1 text-[11px] font-mono font-semibold tracking-[0.04em]">
              {provider.display_name.slice(0, 2).toUpperCase()}
            </div>
            <div>
              <div className="text-[14px] font-semibold text-text-0">
                {provider.display_name}
              </div>
              <div className="mt-0.5 text-[11px] text-text-3 flex items-center">
                <span className="uppercase tracking-[0.05em] text-[10px] py-px px-1.5 border border-border-soft rounded-sm text-text-2">
                  {provider.scope}
                </span>
                <span className="ml-2">{provider.description}</span>
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="w-7 h-7 bg-transparent border-0 text-text-2 text-[20px] cursor-pointer rounded-md hover:bg-bg-2 hover:text-text-0"
          >
            ×
          </button>
        </div>

        <div className="py-4 px-[18px]">
          {err && (
            <div className="mb-2.5 py-2 px-2.5 rounded-md border border-danger text-danger text-[12px] bg-[color-mix(in_oklch,var(--danger)_12%,transparent)]">
              {err}
            </div>
          )}

          {provider.status === "not_connected" && (
            <>
              <p className="text-[13px] text-text-1 leading-[1.55] m-0 mb-3.5">
                Connect your {provider.display_name} account to surface
                relevant context in chat and let Donna act on your behalf.
              </p>
              <button
                type="button"
                onClick={handleConnect}
                disabled={busy}
                className={PRIMARY_BTN}
              >
                {busy ? "Opening…" : "Connect"}
              </button>
            </>
          )}

          {isConnected && (
            <>
              <div className="flex items-center gap-2 mb-2">
                <span className="text-[11px] uppercase tracking-[0.06em] py-0.5 px-2 rounded-sm text-ok border border-ok bg-transparent">
                  {provider.status === "live" ? "Live" : "Read-only"}
                </span>
                {conn?.last_synced_at && (
                  <span className="text-[11px] text-text-3">
                    Last synced {humanizeTime(conn.last_synced_at)}
                  </span>
                )}
              </div>

              {conn?.last_error_msg && (
                <div className="mt-2 mb-1 py-1.5 px-2 rounded-md border border-dashed border-danger text-danger text-[11px] leading-[1.4] bg-[color-mix(in_oklch,var(--danger)_8%,transparent)]">
                  {conn.last_error_msg}
                </div>
              )}

              {conn && (
                <>
                  <div className="mt-3 text-[11px] uppercase tracking-[0.06em] text-text-3 font-semibold">
                    Configuration
                  </div>
                  <pre className="mt-1.5 py-2.5 px-3 bg-bg-2 border border-border-soft rounded-lg font-mono text-[11px] text-text-1 whitespace-pre-wrap break-all max-h-[180px] overflow-auto">
                    {JSON.stringify(conn.config, null, 2)}
                  </pre>
                </>
              )}

              <div className="flex gap-2 mt-3.5">
                <button
                  type="button"
                  onClick={() => {
                    /* v2: open JSON-schema config editor */
                  }}
                  className={CONFIGURE_BTN}
                  disabled
                  title="JSON schema config coming soon"
                  aria-disabled="true"
                >
                  Configure
                </button>
                <button
                  type="button"
                  onClick={handleDisconnect}
                  disabled={busy}
                  className={DANGER_BTN}
                >
                  {busy ? "Disconnecting…" : "Disconnect"}
                </button>
              </div>
            </>
          )}

          {provider.status === "error" && (
            <>
              <p className="text-[13px] text-text-1 leading-[1.55] m-0 mb-3.5">
                Connection exists but the OAuth app is missing or disabled.
                Reconnect to re-issue tokens.
              </p>
              <button
                type="button"
                onClick={handleConnect}
                disabled={busy}
                className={PRIMARY_BTN}
              >
                {busy ? "Opening…" : "Reconnect"}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
