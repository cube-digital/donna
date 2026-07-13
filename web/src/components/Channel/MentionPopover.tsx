// @mention autocomplete popover. Mounted as a sibling of the composer
// textarea; anchored above. Backed by `GET /chat/channels/<id>/mention-
// candidates/?q=` debounced.

import { useEffect, useRef, useState } from "react";

import { getMentionCandidates, type MentionCandidate } from "../../api/chat";
import { GAvatar, GlyphSlot } from "../Goofy";

interface Props {
  channelId: string;
  query: string;
  open: boolean;
  onSelect: (candidate: MentionCandidate) => void;
  onClose: () => void;
  /** Bind keyboard navigation to this textarea. */
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
}

const DEBOUNCE_MS = 120;

export function MentionPopover({
  channelId,
  query,
  open,
  onSelect,
  onClose,
  inputRef,
}: Props) {
  const [items, setItems] = useState<MentionCandidate[]>([]);
  const [active, setActive] = useState(0);
  const debounceRef = useRef<number | null>(null);

  useEffect(() => {
    if (!open) return;
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      void getMentionCandidates(channelId, query)
        .then((rows) => {
          setItems(rows);
          setActive(0);
        })
        .catch(() => setItems([]));
    }, DEBOUNCE_MS);
    return () => {
      if (debounceRef.current) window.clearTimeout(debounceRef.current);
    };
  }, [channelId, query, open]);

  useEffect(() => {
    if (!open) return;
    const el = inputRef.current;
    if (!el) return;
    function onKey(ev: KeyboardEvent) {
      if (!items.length) return;
      if (ev.key === "ArrowDown") {
        ev.preventDefault();
        setActive((i) => (i + 1) % items.length);
      } else if (ev.key === "ArrowUp") {
        ev.preventDefault();
        setActive((i) => (i - 1 + items.length) % items.length);
      } else if (ev.key === "Enter" || ev.key === "Tab") {
        ev.preventDefault();
        onSelect(items[active]);
      } else if (ev.key === "Escape") {
        ev.preventDefault();
        onClose();
      }
    }
    el.addEventListener("keydown", onKey);
    return () => el.removeEventListener("keydown", onKey);
  }, [open, items, active, inputRef, onSelect, onClose]);

  if (!open || !items.length) return null;

  return (
    <div className="absolute bottom-full left-0 mb-1 w-[280px] max-h-[260px] overflow-y-auto bg-bg-1 border border-border-soft rounded-[10px] shadow-lg z-30">
      {items.map((c, i) => {
        const isActive = i === active;
        return (
          <button
            key={`${c.kind}-${c.id}`}
            type="button"
            onMouseDown={(e) => {
              e.preventDefault();
              onSelect(c);
            }}
            className={
              "w-full flex items-center gap-2 px-2.5 py-1.5 text-left text-[13px] " +
              (isActive ? "bg-ai-bg text-text-0" : "text-text-1 hover:bg-bg-2")
            }
          >
            <span className="shrink-0">
              {c.kind === "agent" ? (
                <GAvatar kind="agent" size="sm" name={c.label} />
              ) : c.kind === "user" ? (
                <GAvatar size="sm" name={c.label} />
              ) : (
                <span className="w-[26px] h-[26px] rounded-[8px] bg-ai-bg text-ai-deep grid place-items-center">
                  <GlyphSlot name="at" size={14} />
                </span>
              )}
            </span>
            <span className="flex-1 min-w-0">
              <span className="block truncate font-semibold">{c.label}</span>
              {c.email ? (
                <span className="block truncate text-[11px] text-text-3">
                  {c.email}
                </span>
              ) : (
                <span className="block truncate text-[11px] text-text-3 capitalize">
                  {c.kind}
                </span>
              )}
            </span>
            <span className="text-[10.5px] text-text-4 font-mono">@{c.handle}</span>
          </button>
        );
      })}
    </div>
  );
}
