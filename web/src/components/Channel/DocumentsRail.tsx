// DocumentsRail — Cowork-style panel listing channel's drafts +
// finalized docs. Mounts inside the Channel view (right rail when not
// taken by ThreadPanel).
//
// Data: REST load on channel switch; live updates via the WS
// `document.updated` event routed to documents store.

import { useEffect, useState } from "react";

import { useDocuments } from "../../state/documents";
import type { ChannelDocument } from "../../types";

interface DocumentsRailProps {
  channelId: string;
}

export function DocumentsRail({ channelId }: DocumentsRailProps) {
  const docs = useDocuments((s) => s.byChannel[channelId] ?? []);
  const load = useDocuments((s) => s.load);
  const loading = useDocuments((s) => s.loading[channelId]);
  const [selected, setSelected] = useState<ChannelDocument | null>(null);

  useEffect(() => {
    load(channelId);
  }, [channelId, load]);

  const drafts = docs.filter((d) => d.status === "drafting");
  const finalized = docs.filter((d) => d.status === "finalized").slice(0, 5);

  return (
    <aside className="flex flex-col h-full border-l-2 border-ink bg-bg-0 w-[320px] max-w-[30vw]">
      <header className="px-3 py-2 border-b-2 border-dashed border-ink/40">
        <div className="font-display font-semibold text-[14px]">Documents</div>
        <div className="text-[11px] text-text-2 mt-0.5">
          Drafts and finalized docs in this channel
        </div>
      </header>

      <div className="flex-1 overflow-y-auto p-2.5 flex flex-col gap-3">
        {loading && (
          <div className="text-[12px] text-text-2 px-1">Loading…</div>
        )}

        {drafts.length > 0 && (
          <section>
            <div className="text-[10px] uppercase tracking-wide text-text-2 mb-1 px-1">
              Drafting
            </div>
            <ul className="flex flex-col gap-1">
              {drafts.map((d) => (
                <DocRow key={d.id} doc={d} onOpen={() => setSelected(d)} />
              ))}
            </ul>
          </section>
        )}

        {finalized.length > 0 && (
          <section>
            <div className="text-[10px] uppercase tracking-wide text-text-2 mb-1 px-1">
              Finalized
            </div>
            <ul className="flex flex-col gap-1">
              {finalized.map((d) => (
                <DocRow key={d.id} doc={d} onOpen={() => setSelected(d)} />
              ))}
            </ul>
          </section>
        )}

        {!loading && docs.length === 0 && (
          <div className="text-[12px] text-text-2 px-1">
            No documents yet. Ask Donna to draft one.
          </div>
        )}
      </div>

      {selected && (
        <DocumentPreview doc={selected} onClose={() => setSelected(null)} />
      )}
    </aside>
  );
}

function DocRow({
  doc,
  onOpen,
}: {
  doc: ChannelDocument;
  onOpen: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        className="w-full text-left px-2 py-1.5 rounded-[8px] border border-ink/20 hover:bg-bg-2 flex items-center gap-2"
      >
        <span className="flex-1 truncate text-[13px]">{doc.title}</span>
        <span className="text-[10px] tabular-nums px-1.5 py-0.5 rounded bg-bg-2 border border-ink/20">
          v{doc.version}
        </span>
      </button>
    </li>
  );
}

function DocumentPreview({
  doc,
  onClose,
}: {
  doc: ChannelDocument;
  onClose: () => void;
}) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      className="fixed inset-0 z-50 grid place-items-center bg-ink/40"
    >
      <div className="bg-bg-1 border-2 border-ink rounded-[14px] shadow-ink-2 w-[680px] max-w-[90vw] max-h-[80vh] flex flex-col">
        <header className="flex items-center justify-between px-4 py-2.5 border-b-2 border-dashed border-ink/40">
          <div>
            <div className="font-display font-semibold text-[15px]">
              {doc.title}
            </div>
            <div className="text-[11px] text-text-2">
              v{doc.version} · {doc.status}
              {doc.target_doc_type ? ` · ${doc.target_doc_type}` : ""}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-text-2 hover:text-text-0 text-[20px] leading-none"
            aria-label="Close preview"
          >
            ×
          </button>
        </header>
        <div className="flex-1 overflow-y-auto p-4 prose prose-sm max-w-none whitespace-pre-wrap text-[13.5px] leading-relaxed">
          {doc.body || <em className="text-text-2">(empty)</em>}
        </div>
      </div>
    </div>
  );
}
