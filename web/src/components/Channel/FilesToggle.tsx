// Cowork-style "Files" toggle pinned in the channel header.
//
// Shown whenever this channel has any artifacts. Clicking opens a
// dropdown of every artifact (newest first); picking one opens it in
// the right-rail file panel and clears the per-channel dismiss flag
// (so it stays open until the user X's it again).

import { useEffect, useRef, useState } from "react";

import { useArtifacts } from "../../state/artifacts";
import { useArtifactPreview } from "../../state/artifactPreview";

interface Props {
  channelId: string;
}

export function FilesToggle({ channelId }: Props) {
  const artifacts = useArtifacts((s) => s.byChannel[channelId]);
  const openPreview = useArtifactPreview((s) => s.open);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current) return;
      if (rootRef.current.contains(e.target as Node)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const list = (artifacts ?? [])
    .slice()
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  // Hide entirely when there's nothing to surface — the channel hasn't
  // produced any drafts yet, so the affordance would be a noop.
  if (list.length === 0) return null;

  const pick = (id: string) => {
    openPreview(id, channelId);
    setOpen(false);
  };

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label="Open files"
        title="Files"
        className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md bg-bg-1 border border-border-soft text-text-2 text-[11.5px] font-semibold hover:bg-bg-2"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <line x1="3" y1="6" x2="21" y2="6" />
          <line x1="3" y1="12" x2="21" y2="12" />
          <line x1="3" y1="18" x2="21" y2="18" />
        </svg>
        Files
        <span className="text-text-3 text-[10.5px]">{list.length}</span>
      </button>

      {open ? (
        <div
          role="menu"
          className="absolute top-full right-0 mt-1 w-[280px] max-h-[320px] overflow-y-auto bg-bg-1 border border-border-soft rounded-[10px] shadow-lg z-30 py-1"
        >
          {list.map((a) => (
            <button
              key={a.id}
              type="button"
              role="menuitem"
              onClick={() => pick(a.id)}
              className="w-full flex items-center gap-2 px-2.5 py-1.5 text-left text-[12.5px] text-text-1 hover:bg-bg-2"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
              </svg>
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
          ))}
        </div>
      ) : null}
    </div>
  );
}
