// Cortex memory browser. Hierarchical left tree (People / Clients /
// Vendors / Peers / Projects + content categories), main browser pane
// with folder tiles + recent items. Click an entity → opens preview
// drawer; deeper navigation goes through scope state.

import { useEffect, useMemo, useState } from "react";

import {
  getCortexCounts,
  getCortexEntity,
  listCortexFiles,
  type CortexFile,
} from "../api/cortex";
import { GlyphSlot, type IconName } from "../components/Goofy";

type Scope = {
  kind: "all" | "type" | "org" | "project";
  /** Type filter for "type" scope, sub-kind for "org" (client/vendor/peer). */
  value?: string;
};

interface TypeNode {
  value: string;
  label: string;
  icon: IconName;
  tint: string;
}

const CONTENT_TYPES: TypeNode[] = [
  { value: "meeting", label: "Meetings", icon: "doc", tint: "bg-pop-blue/20 text-pop-blue" },
  { value: "email", label: "Emails", icon: "at", tint: "bg-pop-coral/20 text-pop-coral" },
  { value: "doc", label: "Docs", icon: "doc", tint: "bg-pop-sun/30 text-on-bright" },
  { value: "chat", label: "Chats", icon: "msg", tint: "bg-pop-mint/30 text-ok" },
  { value: "ticket", label: "Tickets", icon: "folder", tint: "bg-bg-2 text-text-3" },
  { value: "note", label: "Notes", icon: "doc", tint: "bg-bg-2 text-text-3" },
  { value: "decision", label: "Decisions", icon: "edit", tint: "bg-bg-2 text-text-3" },
  { value: "concept", label: "Concepts", icon: "brain", tint: "bg-bg-2 text-text-3" },
];

const ENTITY_GROUPS: { key: string; label: string; type: string; relationship?: string; icon: IconName }[] = [
  { key: "people", label: "People", type: "person", icon: "at" },
  { key: "clients", label: "Clients", type: "org", relationship: "client", icon: "folder" },
  { key: "vendors", label: "Vendors", type: "org", relationship: "vendor", icon: "folder" },
  { key: "peers", label: "Peers", type: "org", relationship: "peer", icon: "folder" },
  { key: "projects", label: "Projects", type: "project", icon: "folder" },
];

function FileIcon({ type }: { type: string }) {
  const entry = CONTENT_TYPES.find((g) => g.value === type) ?? CONTENT_TYPES[0];
  return (
    <span className={`w-9 h-9 rounded-[9px] grid place-items-center shrink-0 ${entry.tint}`}>
      <GlyphSlot name={entry.icon} size={18} />
    </span>
  );
}

interface ExpandableSectionProps {
  label: string;
  icon: IconName;
  type: string;
  relationship?: string;
  /** Count from the aggregate counts endpoint — no per-section probe call. */
  count?: number;
  scope: Scope;
  setScope: (s: Scope) => void;
}

function ExpandableSection({
  label,
  icon,
  type,
  relationship,
  count,
  scope,
  setScope,
}: ExpandableSectionProps) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<CortexFile[] | null>(null);

  // Fetch entity list once on expand (lazy, user-initiated — no mount fetch).
  useEffect(() => {
    if (!open || items !== null) return;
    let cancelled = false;
    void listCortexFiles({ type, relationship, limit: 200 })
      .then((p) => {
        if (cancelled) return;
        setItems(p.data);
      })
      .catch(() => {
        if (cancelled) return;
        setItems([]);
      });
    return () => {
      cancelled = true;
    };
  }, [open, items, type, relationship]);

  const isScopeRoot =
    (type === "org" && scope.kind === "org" && scope.value === relationship) ||
    (type !== "org" && scope.kind === "type" && scope.value === type);

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-2 py-1.5 rounded-[8px] text-[13px] text-text-2 hover:bg-bg-3"
      >
        <GlyphSlot
          name="caret"
          size={11}
          className={"transition-transform " + (open ? "" : "-rotate-90")}
        />
        <GlyphSlot name={icon} size={16} />
        <span className="flex-1 text-left font-semibold">{label}</span>
        {count ? (
          <span className="text-[10.5px] text-text-4 font-mono">{count}</span>
        ) : null}
      </button>
      {open ? (
        <div className="pl-5">
          <button
            type="button"
            onClick={() =>
              setScope(
                type === "org"
                  ? { kind: "org", value: relationship }
                  : { kind: "type", value: type },
              )
            }
            className={
              "w-full text-left px-2 py-1 rounded text-[12.5px] " +
              (isScopeRoot
                ? "bg-[var(--ai-bg)] text-[color:var(--ai-deep)] font-semibold"
                : "text-text-3 hover:text-text-1")
            }
          >
            All {label.toLowerCase()}
          </button>
          {items === null ? (
            <div className="px-2 py-1 text-[11.5px] text-text-4">Loading…</div>
          ) : items.length === 0 ? (
            <div className="px-2 py-1 text-[11.5px] text-text-4">None yet</div>
          ) : (
            items.slice(0, 30).map((it) => {
              const active =
                (type === "project" && scope.kind === "project" && scope.value === it.id);
              return (
                <button
                  key={it.id}
                  type="button"
                  onClick={() => {
                    if (type === "project") {
                      setScope({ kind: "project", value: it.id });
                    }
                  }}
                  title={it.title}
                  className={
                    "w-full text-left px-2 py-1 rounded text-[12.5px] truncate " +
                    (active
                      ? "bg-[var(--ai-bg)] text-[color:var(--ai-deep)] font-semibold"
                      : "text-text-2 hover:text-text-0 hover:bg-bg-3")
                  }
                >
                  {it.title || "(untitled)"}
                </button>
              );
            })
          )}
          {items && items.length > 30 ? (
            <div className="px-2 py-1 text-[11px] text-text-4">
              … +{items.length - 30} more
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export default function Files() {
  const [scope, setScope] = useState<Scope>({ kind: "all" });
  const [q, setQ] = useState<string>("");
  const [files, setFiles] = useState<CortexFile[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<CortexFile | null>(null);

  // Resolve scope → API filter args.
  const apiArgs = useMemo<{ type?: string; relationship?: string }>(() => {
    if (scope.kind === "type") return { type: scope.value };
    if (scope.kind === "org") return { type: "org", relationship: scope.value };
    if (scope.kind === "project") return {};
    return {};
  }, [scope]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void listCortexFiles({ q, ...apiArgs, limit: 200 })
      .then((page) => {
        if (cancelled) return;
        let data = page.data;
        if (scope.kind === "project" && scope.value) {
          data = data.filter((d) => d.project_id === scope.value);
        }
        setFiles(data);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(String(e?.message ?? e));
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [scope, q, apiArgs]);

  // Per-content-type counts for the sidebar — one aggregate call instead of a
  // full 200-item list fetch per type (each of which also signed an S3 URL per
  // row). Merges the org relationship breakdown (client/vendor/peer) into the
  // same map the type groups read from.
  useEffect(() => {
    let cancelled = false;
    void getCortexCounts()
      .then((c) => {
        if (cancelled) return;
        setCounts({ ...c.by_type, ...c.by_relationship });
      })
      .catch(() => {
        if (!cancelled) setCounts({});
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const headerLabel = useMemo(() => {
    if (scope.kind === "all") return "All memory";
    if (scope.kind === "type") {
      return CONTENT_TYPES.find((g) => g.value === scope.value)?.label ?? "All memory";
    }
    if (scope.kind === "org") {
      return ENTITY_GROUPS.find((g) => g.relationship === scope.value)?.label ?? "Organizations";
    }
    if (scope.kind === "project") return "Project";
    return "All memory";
  }, [scope]);

  return (
    <div className="h-full flex overflow-hidden">
      {/* Left tree. */}
      <aside className="w-[240px] shrink-0 border-r border-border-soft bg-bg-2 overflow-y-auto py-3 px-3">
        <div className="flex items-center gap-2 px-1 mb-3">
          <span className="w-7 h-7 rounded-[8px] bg-[var(--ai-bg)] text-[color:var(--ai-deep)] grid place-items-center">
            <GlyphSlot name="brain" size={16} />
          </span>
          <div>
            <div className="font-semibold text-text-0 text-[14px] leading-tight">Cortex</div>
            <div className="text-[11px] text-text-4">workspace memory</div>
          </div>
        </div>

        <button
          type="button"
          onClick={() => setScope({ kind: "all" })}
          className={
            "w-full flex items-center gap-2 px-2 py-1.5 rounded-[8px] text-[13px] " +
            (scope.kind === "all"
              ? "bg-[var(--ai-bg)] text-[color:var(--ai-deep)] font-semibold"
              : "text-text-2 hover:bg-bg-3")
          }
        >
          <GlyphSlot name="folder" size={16} />
          <span className="flex-1 text-left">All memory</span>
        </button>

        <div className="text-[10.5px] font-semibold uppercase tracking-[0.05em] text-text-4 px-2 pt-4 pb-1">
          People & relations
        </div>
        {ENTITY_GROUPS.map((g) => (
          <ExpandableSection
            key={g.key}
            label={g.label}
            icon={g.icon}
            type={g.type}
            relationship={g.relationship}
            count={counts[g.relationship ?? g.type]}
            scope={scope}
            setScope={setScope}
          />
        ))}

        <div className="text-[10.5px] font-semibold uppercase tracking-[0.05em] text-text-4 px-2 pt-4 pb-1">
          Content
        </div>
        {CONTENT_TYPES.map((g) => {
          const active = scope.kind === "type" && scope.value === g.value;
          return (
            <button
              key={g.value}
              type="button"
              onClick={() => setScope({ kind: "type", value: g.value })}
              className={
                "w-full flex items-center gap-2 px-2 py-1.5 rounded-[8px] text-[13px] " +
                (active
                  ? "bg-[var(--ai-bg)] text-[color:var(--ai-deep)] font-semibold"
                  : "text-text-2 hover:bg-bg-3")
              }
            >
              <GlyphSlot name={g.icon} size={16} />
              <span className="flex-1 text-left">{g.label}</span>
              {counts[g.value] ? (
                <span className="text-[10.5px] text-text-4 font-mono">{counts[g.value]}</span>
              ) : null}
            </button>
          );
        })}
      </aside>

      {/* Main browser. */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="px-6 pt-5 pb-3 flex items-center gap-3 border-b border-border-soft">
          <h1 className="font-semibold text-[20px] text-text-0">{headerLabel}</h1>
          <span className="text-[12px] text-text-3">{files.length} items</span>
          <span className="flex-1" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search Cortex memory…"
            className="w-[320px] h-9 px-3 rounded-full border border-border-soft bg-bg-1 text-[13px] text-text-0 placeholder:text-text-3 outline-none focus:border-ai"
          />
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-5">
          {scope.kind === "all" ? (
            <section>
              <div className="text-[11px] font-semibold uppercase tracking-[0.05em] text-text-4 mb-2">
                Folders
              </div>
              <div className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-3">
                {CONTENT_TYPES.map((g) => (
                  <button
                    key={g.value}
                    type="button"
                    onClick={() => setScope({ kind: "type", value: g.value })}
                    className="text-left p-3 rounded-[12px] border border-border-soft bg-bg-1 hover:border-ai transition-colors flex flex-col gap-2"
                  >
                    <span className={`w-9 h-9 rounded-[9px] grid place-items-center ${g.tint}`}>
                      <GlyphSlot name={g.icon} size={18} />
                    </span>
                    <span className="font-semibold text-[14px] text-text-0">{g.label}</span>
                    <span className="text-[11px] text-text-3">{counts[g.value] ?? 0} items</span>
                  </button>
                ))}
              </div>
            </section>
          ) : null}

          <section>
            <div className="text-[11px] font-semibold uppercase tracking-[0.05em] text-text-4 mb-2">
              {scope.kind === "all" ? "Recent" : "Items"}
            </div>
            {loading && files.length === 0 ? (
              <div className="text-text-3 text-[13px]">Loading…</div>
            ) : error ? (
              <div className="text-danger text-[13px]">{error}</div>
            ) : files.length === 0 ? (
              <div className="text-text-3 text-[13px]">Nothing here yet.</div>
            ) : (
              <div className="grid grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-3">
                {files.map((f) => (
                  <button
                    key={f.id}
                    type="button"
                    onClick={() => setSelected(f)}
                    className="text-left flex items-start gap-3 p-3 rounded-[12px] border border-border-soft bg-bg-1 hover:border-ai transition-colors"
                  >
                    <FileIcon type={f.type} />
                    <div className="min-w-0 flex-1">
                      <div className="font-semibold text-[13px] text-text-0 truncate">
                        {f.title || "(untitled)"}
                      </div>
                      <div className="text-[11px] text-text-3 truncate">
                        {f.type}
                        {f.relationship ? ` · ${f.relationship}` : ""}
                        {f.occurred_at ? ` · ${f.occurred_at.slice(0, 10)}` : ""}
                      </div>
                      <div className="text-[10.5px] text-text-4 font-mono truncate">
                        {f.source}
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </section>
        </div>

        {selected ? (
          <PreviewDrawer file={selected} onClose={() => setSelected(null)} />
        ) : null}
      </div>
    </div>
  );
}

function PreviewDrawer({ file, onClose }: { file: CortexFile; onClose: () => void }) {
  const [body, setBody] = useState<string | null>(null);
  const [bronzeUrl, setBronzeUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  // Body served inline by the authed backend (body_md) — no cross-origin S3
  // fetch (no CORS / SigV4 / KMS fragility). Bronze URL signed lazily here too.
  useEffect(() => {
    setBusy(true);
    setErr(null);
    let cancelled = false;
    getCortexEntity(file.id, true)
      .then((card) => {
        if (cancelled) return;
        setBody(card.body_md ?? null);
        setBronzeUrl(card.bronze_url ?? null);
        setBusy(false);
      })
      .catch((e) => {
        if (cancelled) return;
        setErr(String(e?.message ?? e));
        setBusy(false);
      });
    return () => {
      cancelled = true;
    };
  }, [file.id]);

  return (
    <div className="absolute inset-0 z-40 flex" role="dialog" aria-modal="true">
      <div
        className="flex-1 bg-[oklch(0.26_0.03_285/0.30)]"
        onClick={onClose}
      />
      <aside className="w-[520px] max-w-[80vw] h-full bg-bg-1 border-l border-border-soft flex flex-col">
        <header className="px-4 py-3 flex items-center gap-2 border-b border-border-soft">
          <FileIcon type={file.type} />
          <div className="min-w-0 flex-1">
            <div className="font-semibold text-[14px] text-text-0 truncate">
              {file.title || "(untitled)"}
            </div>
            <div className="text-[11px] text-text-3 truncate">{file.source}</div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="text-text-3 hover:text-text-0"
          >
            <GlyphSlot name="x" />
          </button>
        </header>
        <div className="flex-1 overflow-y-auto px-4 py-3 text-[13px] text-text-1">
          {busy ? (
            "Loading…"
          ) : err ? (
            <span className="text-danger">{err}</span>
          ) : body ? (
            <pre className="whitespace-pre-wrap font-sans">{body}</pre>
          ) : (
            <span className="text-text-3">No preview available.</span>
          )}
        </div>
        {file.has_bronze && bronzeUrl ? (
          <footer className="px-4 py-3 border-t border-border-soft text-[12px]">
            <a
              href={bronzeUrl}
              target="_blank"
              rel="noreferrer"
              className="text-ai hover:underline font-semibold"
            >
              Open raw source ↗
            </a>
          </footer>
        ) : null}
      </aside>
    </div>
  );
}
