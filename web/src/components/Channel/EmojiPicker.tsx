// EmojiPicker — shared between reactions + Composer inline insertion.
//
// Dataset: web/src/lib/emojis.ts (auto-generated from
// server/donna/chat/emojis.py via scripts/sync_emojis.py).
//
// Two consumers:
//   - <ReactionBar/> picks emoji codes → POST reaction
//   - <Composer/> picks unicode chars → insert at cursor
//
// Caller decides what to do with the pick via `onPick`. Component
// stays UI-only.

import { useEffect, useMemo, useRef, useState } from "react";

import { CURATED_EMOJIS, type EmojiEntry } from "../../lib/emojis";

interface EmojiPickerProps {
  open: boolean;
  onPick: (entry: EmojiEntry) => void;
  onClose: () => void;
  /** Anchor point for absolute-positioned popover. */
  anchorRect?: DOMRect | null;
}

const GROUPS: { label: string; group: string }[] = [
  { label: "People", group: "people" },
  { label: "Nature", group: "nature" },
  { label: "Food", group: "food" },
  { label: "Activity", group: "activity" },
  { label: "Travel", group: "travel" },
  { label: "Objects", group: "objects" },
  { label: "Symbols", group: "symbols" },
  { label: "Flags", group: "flags" },
];

const RECENTS_KEY = "donna.emoji.recents";
const RECENTS_MAX = 20;

function loadRecents(): string[] {
  try {
    const raw = localStorage.getItem(RECENTS_KEY);
    if (!raw) return [];
    return (JSON.parse(raw) as string[]).slice(0, RECENTS_MAX);
  } catch {
    return [];
  }
}

function pushRecent(code: string): string[] {
  const cur = loadRecents().filter((c) => c !== code);
  const next = [code, ...cur].slice(0, RECENTS_MAX);
  try {
    localStorage.setItem(RECENTS_KEY, JSON.stringify(next));
  } catch {
    /* quota exceeded — ignore */
  }
  return next;
}

export function EmojiPicker({ open, onPick, onClose, anchorRect }: EmojiPickerProps) {
  const [query, setQuery] = useState("");
  const [activeGroup, setActiveGroup] = useState<string>("people");
  const [recents, setRecents] = useState<string[]>(loadRecents());
  const popoverRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setQuery("");
      window.setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    function onClick(e: MouseEvent) {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        onClose();
      }
    }
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onClick);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onClick);
    };
  }, [open, onClose]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) {
      return CURATED_EMOJIS.filter((e) => e.group === activeGroup);
    }
    return CURATED_EMOJIS.filter(
      (e) =>
        e.code.includes(q) ||
        e.keywords.some((k) => k.includes(q)),
    );
  }, [query, activeGroup]);

  if (!open) return null;

  const recentEntries = recents
    .map((code) => CURATED_EMOJIS.find((e) => e.code === code))
    .filter((e): e is EmojiEntry => !!e);

  const pick = (entry: EmojiEntry) => {
    setRecents(pushRecent(entry.code));
    onPick(entry);
  };

  const positionStyle: React.CSSProperties = anchorRect
    ? {
        position: "fixed",
        top: anchorRect.top - 360,
        left: anchorRect.left,
        zIndex: 60,
      }
    : { position: "absolute", bottom: "100%", right: 0, zIndex: 60 };

  return (
    <div
      ref={popoverRef}
      role="dialog"
      aria-label="Emoji picker"
      style={positionStyle}
      className="bg-bg-1 border-2 border-ink rounded-[14px] shadow-ink-2 w-[340px] max-h-[360px] flex flex-col overflow-hidden"
    >
      {/* Search */}
      <div className="p-2 border-b-2 border-dashed border-ink/40">
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search emoji…"
          className="w-full px-2 py-1.5 text-[13px] border-2 border-ink rounded-[8px] bg-bg-0 outline-none focus:ring-2 focus:ring-ai/30"
          autoComplete="off"
        />
      </div>

      {/* Recents row */}
      {!query && recentEntries.length > 0 && (
        <div className="px-2 pt-2">
          <div className="text-[10px] uppercase tracking-wide text-text-2 mb-1">
            Recent
          </div>
          <div className="flex flex-wrap gap-1 mb-2">
            {recentEntries.map((e) => (
              <button
                key={`r-${e.code}`}
                type="button"
                onClick={() => pick(e)}
                className="text-[20px] leading-none px-1.5 py-1 rounded hover:bg-bg-2"
                title={e.code}
              >
                {e.unicode}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Group tabs */}
      {!query && (
        <div className="flex border-b border-ink/20 px-2 overflow-x-auto">
          {GROUPS.map((g) => (
            <button
              key={g.group}
              type="button"
              onClick={() => setActiveGroup(g.group)}
              className={
                "px-2 py-1 text-[11px] whitespace-nowrap " +
                (activeGroup === g.group
                  ? "border-b-2 border-ai font-semibold text-text-0"
                  : "text-text-2 hover:text-text-1")
              }
            >
              {g.label}
            </button>
          ))}
        </div>
      )}

      {/* Grid */}
      <div className="flex-1 overflow-y-auto p-2">
        <div className="grid grid-cols-8 gap-1">
          {filtered.map((e) => (
            <button
              key={e.code}
              type="button"
              onClick={() => pick(e)}
              className="text-[20px] leading-none px-1.5 py-1 rounded hover:bg-bg-2"
              title={`:${e.code}:`}
            >
              {e.unicode}
            </button>
          ))}
        </div>
        {filtered.length === 0 && (
          <div className="text-center text-[12px] text-text-2 py-6">
            No emoji match "{query}"
          </div>
        )}
      </div>
    </div>
  );
}
