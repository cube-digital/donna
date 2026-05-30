// /integrations/:slug — single-source configuration page.
//
// Three states gate the body:
//   not_connected → big primary "Connect" CTA.
//   live          → structured IntegrationForm.
//   error         → red banner, then form (account may still be usable).

import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  disconnectIntegration,
  getIntegration,
  getSubscription,
} from "../api/integrations";
import { IntegrationForm } from "../components/Integrations/IntegrationForm";
import { useOAuthConnect } from "../components/Integrations/useOAuthConnect";
import { Button } from "../components/Ui/Button";
import { ConnectorIcon } from "../components/Ui/BrandIc";
import { Ic } from "../components/Ui/Ic";
import { useIntegrations } from "../state/integrations";
import type { Connection, IntegrationProvider } from "../types";

function relative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const sec = Math.round((Date.now() - d.getTime()) / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.round(hr / 24);
  if (day < 7) return `${day}d ago`;
  return d.toLocaleString();
}

export default function IntegrationDetail() {
  const { slug } = useParams<{ slug: string }>();
  const navigate = useNavigate();
  const reloadList = useIntegrations((s) => s.reload);

  const [provider, setProvider] = useState<IntegrationProvider | null>(null);
  const [conn, setConn] = useState<Connection | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function refresh() {
    if (!slug) return;
    setLoading(true);
    setErr(null);
    try {
      const p = await getIntegration(slug);
      setProvider(p);
      if (p.status === "live" || p.status === "error" || p.status === "read-only") {
        try {
          setConn(await getSubscription(slug));
        } catch {
          setConn(null);
        }
      } else {
        setConn(null);
      }
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug]);

  const { connect, busy: connecting, error: connectErr } = useOAuthConnect(
    slug ?? "",
    async () => {
      await Promise.all([reloadList(), refresh()]);
    },
  );

  async function handleDisconnect() {
    if (!slug || !provider) return;
    const ok = window.confirm(
      `Disconnect ${provider.display_name}? Donna will stop receiving updates from this account.`,
    );
    if (!ok) return;
    setBusy(true);
    try {
      await disconnectIntegration(slug);
      await reloadList();
      await refresh();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (loading && !provider) {
    return (
      <div className="px-8 py-6 text-text-3 text-[12.5px]">Loading…</div>
    );
  }

  if (!provider) {
    return (
      <div className="px-8 py-6 text-text-3 text-[12.5px]">
        Integration not found.{" "}
        <Link to="/integrations" className="text-text-0 underline">
          Back to catalog
        </Link>
      </div>
    );
  }

  const status = provider.status;
  const dotClass =
    status === "live"
      ? "bg-ok shadow-[0_0_6px_var(--ok)]"
      : status === "error"
      ? "bg-danger"
      : status === "read-only"
      ? "bg-warn"
      : "bg-bg-3";
  const statusLabel =
    status === "live" ? "Connected" : status === "error" ? "Error" : status === "read-only" ? "Read-only" : "Not connected";

  return (
    <div className="overflow-y-auto h-full px-8 py-6">
      <div className="max-w-[720px] mx-auto flex flex-col gap-5">
        {/* Breadcrumb back */}
        <button
          type="button"
          onClick={() => navigate("/integrations")}
          className="flex items-center gap-1 text-[12px] text-text-3 hover:text-text-0 w-fit"
        >
          <Ic.caret className="rotate-90" />
          Integrations
        </button>

        {/* Header */}
        <header className="flex items-center gap-3">
          <span className="w-10 h-10 grid place-items-center rounded-lg bg-bg-2 border border-border-soft">
            <ConnectorIcon slug={provider.slug} label={provider.display_name} />
          </span>
          <div className="flex-1 flex flex-col gap-0.5">
            <div className="flex items-center gap-2">
              <h1 className="text-[16px] font-semibold text-text-0">
                {provider.display_name}
              </h1>
              <span
                className={`w-1.5 h-1.5 rounded-full ${dotClass}`}
                aria-label={statusLabel}
              />
              <span className="text-[11px] uppercase tracking-[0.04em] text-text-3">
                {statusLabel}
              </span>
            </div>
            <div className="text-[12px] text-text-3 font-mono">
              {provider.slug} · {provider.description ?? "—"} · {provider.scope}-scoped
            </div>
          </div>
          {(status === "live" || status === "error" || status === "read-only") && (
            <Button variant="danger" onClick={handleDisconnect} disabled={busy}>
              Disconnect
            </Button>
          )}
        </header>

        {(err || connectErr) && (
          <div className="py-1.5 px-2 rounded-md border border-danger text-danger text-[12px] bg-[color-mix(in_oklch,var(--danger)_8%,transparent)]">
            {err || connectErr}
          </div>
        )}

        {/* Body */}
        {status === "not_connected" ? (
          <section className="flex flex-col gap-3 p-6 bg-bg-1 border border-border-soft rounded-lg items-start">
            <h2 className="text-[14px] font-medium text-text-0">
              Connect {provider.display_name}
            </h2>
            <p className="text-[12.5px] text-text-3 max-w-[440px]">
              You'll be sent to {provider.display_name}'s authorization screen. After
              approving, Donna will start ingesting data into this workspace.
            </p>
            <Button variant="primary" onClick={connect} disabled={connecting}>
              {connecting ? "Opening OAuth…" : `Connect ${provider.display_name}`}
            </Button>
          </section>
        ) : conn ? (
          <>
            <section className="flex flex-col gap-2">
              <h2 className="text-[11px] uppercase tracking-[0.04em] text-text-3 font-medium">
                Configuration
              </h2>
              <IntegrationForm
                provider={provider}
                connection={conn}
                onSaved={(next) => setConn(next)}
              />
            </section>

            <section className="flex flex-col gap-1.5 pt-4 border-t border-border-soft">
              <h2 className="text-[11px] uppercase tracking-[0.04em] text-text-3 font-medium">
                Status
              </h2>
              <dl className="grid grid-cols-[160px_1fr] gap-y-1 text-[12.5px]">
                <dt className="text-text-3">Last synced</dt>
                <dd className="text-text-1">{relative(conn.last_synced_at)}</dd>
                <dt className="text-text-3">Last error</dt>
                <dd className="text-text-1">{conn.last_error_msg || "—"}</dd>
                <dt className="text-text-3">Connection id</dt>
                <dd className="text-text-2 font-mono text-[12px]">{conn.id}</dd>
              </dl>
            </section>
          </>
        ) : (
          <div className="text-[12.5px] text-text-3">
            Loading subscription…
          </div>
        )}
      </div>
    </div>
  );
}
