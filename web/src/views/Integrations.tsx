// /integrations — catalog of every registered connector.
//
// Tabs (All / Connected / Available) + search filter; renders a card grid.
// Each card routes to `/integrations/<slug>` for connect + configure.

import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { useIntegrations } from "../state/integrations";
import type { IntegrationProvider } from "../types";
import { ConnectorIcon } from "../components/Ui/BrandIc";
import { Ic } from "../components/Ui/Ic";
import { Input } from "../components/Ui/Input";

type Tab = "all" | "connected" | "available";

const TABS: { key: Tab; label: string }[] = [
  { key: "all", label: "All" },
  { key: "connected", label: "Connected" },
  { key: "available", label: "Available" },
];

function statusDot(status: IntegrationProvider["status"]): {
  className: string;
  label: string;
} {
  switch (status) {
    case "live":
      return { className: "bg-ok shadow-[0_0_6px_var(--ok)]", label: "Connected" };
    case "error":
      return { className: "bg-danger", label: "Error" };
    case "read-only":
      return { className: "bg-warn", label: "Read-only" };
    default:
      return { className: "bg-bg-3", label: "Not connected" };
  }
}

export default function Integrations() {
  const providers = useIntegrations((s) => s.providers);
  const loaded = useIntegrations((s) => s.loaded);
  const load = useIntegrations((s) => s.load);
  const [tab, setTab] = useState<Tab>("all");
  const [query, setQuery] = useState("");

  if (!loaded) void load();

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return providers.filter((p) => {
      if (tab === "connected" && p.status !== "live" && p.status !== "error") return false;
      if (tab === "available" && (p.status === "live" || p.status === "error")) return false;
      if (q && !`${p.display_name} ${p.description ?? ""}`.toLowerCase().includes(q)) {
        return false;
      }
      return true;
    });
  }, [providers, tab, query]);

  return (
    <div className="overflow-y-auto h-full px-8 py-6">
      <div className="max-w-[920px] mx-auto flex flex-col gap-5">
        {/* Page header */}
        <header className="flex flex-col gap-1">
          <h1 className="text-[18px] font-semibold text-text-0">Connections</h1>
          <p className="text-[13px] text-text-3">
            Tools that pull data into Donna. Connect once; configure per workspace.
          </p>
        </header>

        {/* Tabs + search */}
        <div className="flex items-center gap-3 border-b border-border-soft">
          <div className="flex gap-0.5">
            {TABS.map((t) => (
              <button
                key={t.key}
                type="button"
                onClick={() => setTab(t.key)}
                className={
                  "h-8 px-2.5 text-[12.5px] font-medium border-b -mb-px transition-colors " +
                  (tab === t.key
                    ? "text-text-0 border-text-0"
                    : "text-text-2 border-transparent hover:text-text-0")
                }
              >
                {t.label}
              </button>
            ))}
          </div>
          <div className="ml-auto pb-1.5">
            <div className="flex items-center gap-1.5 h-7 px-2.5 bg-bg-2 border border-border-soft rounded-md text-text-2 text-[12.5px] w-[280px]">
              <Ic.search />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search integrations…"
                className="flex-1 bg-transparent border-0 px-0 h-5 focus:border-transparent"
              />
            </div>
          </div>
        </div>

        {/* Grid */}
        {filtered.length === 0 ? (
          <div className="text-[12.5px] text-text-3 py-12 text-center">
            {loaded ? "No integrations match your filters." : "Loading…"}
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {filtered.map((p) => {
              const dot = statusDot(p.status);
              return (
                <Link
                  key={p.slug}
                  to={`/integrations/${p.slug}`}
                  className="flex flex-col gap-2 p-3 bg-bg-1 border border-border-soft rounded-lg hover:bg-bg-2 hover:border-border-strong group"
                >
                  <div className="flex items-center gap-2">
                    <span className="w-6 h-6 grid place-items-center">
                      <ConnectorIcon slug={p.slug} label={p.display_name} />
                    </span>
                    <span className="flex-1 text-[13px] font-medium text-text-0 truncate">
                      {p.display_name}
                    </span>
                    <span
                      className={`w-1.5 h-1.5 rounded-full ${dot.className}`}
                      aria-label={dot.label}
                      title={dot.label}
                    />
                  </div>
                  <div className="text-[11.5px] text-text-3">
                    {p.description ?? "—"}
                  </div>
                  <div className="text-[11px] text-text-3 font-medium uppercase tracking-[0.04em] mt-auto">
                    {dot.label}
                  </div>
                </Link>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
