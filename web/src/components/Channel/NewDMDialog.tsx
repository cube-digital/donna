// New direct message picker — single or multi-peer.
//
// Behavior:
//   * One selected peer → POST /chat/dms/      (1:1 DM, idempotent)
//   * 2+ selected peers → POST /chat/dms/group (exact-set-match group DM)
//
// On success the resulting Channel is upserted into the channels store
// and the dialog navigates the caller into it. Workspace members come
// from /api/v1/members/.

import { useEffect, useId, useMemo, useRef, useState } from "react";

import { openDM, openGroupDM } from "../../api/chat";
import { listWorkspaceMembers } from "../../api/workspaces";
import { getCurrentUserId } from "../../lib/auth-storage";
import { useChannels } from "../../state/channels";
import type { Channel, WorkspaceMembership } from "../../types";
import { GButton, GChip, GIconButton } from "../Goofy";

interface NewDMDialogProps {
  open: boolean;
  onClose: () => void;
  onOpened?: (channel: Channel) => void;
}

const FOCUSABLE_SELECTOR =
  'a[href],area[href],input:not([disabled]):not([type="hidden"]),select:not([disabled]),textarea:not([disabled]),button:not([disabled]),iframe,object,embed,[contenteditable="true"],[tabindex]:not([tabindex="-1"])';

export function NewDMDialog({ open, onClose, onOpened }: NewDMDialogProps) {
  const titleId = useId();
  const currentUserId = getCurrentUserId();
  const upsertChannel = useChannels((s) => s.upsertFromEvent);

  const [workspaceMembers, setWorkspaceMembers] = useState<WorkspaceMembership[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  const containerRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) {
      previousFocusRef.current?.focus?.();
      return;
    }
    previousFocusRef.current = document.activeElement as HTMLElement | null;
    setErr(null);
    setSelected(new Set());
    setFilter("");
    setLoading(true);
    let cancelled = false;
    void listWorkspaceMembers()
      .then((list) => {
        if (!cancelled) setWorkspaceMembers(list);
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setErr(e instanceof Error ? e.message : "Failed to load members.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key !== "Tab") return;
      const root = containerRef.current;
      if (!root) return;
      const targets = Array.from(
        root.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
      ).filter((el) => !el.hasAttribute("aria-hidden"));
      if (targets.length === 0) return;
      const first = targets[0];
      const last = targets[targets.length - 1];
      const active = document.activeElement as HTMLElement | null;
      if (e.shiftKey && active === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // Candidates = workspace members minus current user, filtered by `filter`.
  const candidates = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return workspaceMembers
      .filter((wm) => wm.user.id !== currentUserId)
      .filter((wm) => {
        if (!needle) return true;
        const haystack = `${wm.user.full_name} ${wm.user.email}`.toLowerCase();
        return haystack.includes(needle);
      })
      .sort((a, b) =>
        (a.user.full_name || a.user.email).localeCompare(
          b.user.full_name || b.user.email,
        ),
      );
  }, [workspaceMembers, currentUserId, filter]);

  if (!open) return null;

  function toggleSelected(userId: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(userId)) next.delete(userId);
      else next.add(userId);
      return next;
    });
  }

  async function submit() {
    if (selected.size === 0) return;
    setBusy(true);
    setErr(null);
    try {
      const ids = Array.from(selected);
      const channel =
        ids.length === 1
          ? await openDM(ids[0])
          : await openGroupDM(ids);
      upsertChannel(channel);
      onOpened?.(channel);
      onClose();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Failed to open DM.");
    } finally {
      setBusy(false);
    }
  }

  const ctaLabel =
    selected.size <= 1 ? "Open conversation" : "Open group conversation";

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      className="fixed inset-0 z-50 grid place-items-center bg-ink/40 overscroll-contain"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={containerRef}
        className="bg-bg-1 border-2 border-ink rounded-[14px] shadow-ink-2 w-[480px] max-w-[92vw] max-h-[80vh] flex flex-col"
      >
        <div className="flex items-center justify-between py-3 px-4 border-b-2 border-dashed border-ink/40">
          <div
            id={titleId}
            className="font-display font-semibold text-text-0 text-[15px]"
          >
            New conversation
          </div>
          <GIconButton icon="x" size="sm" onClick={onClose} aria-label="Close dialog" />
        </div>

        <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-2">
          {err && (
            <div
              role="alert"
              aria-live="assertive"
              className="py-1.5 px-2.5 rounded-[9px] border-2 border-danger text-danger text-[12.5px] bg-[color-mix(in_oklch,var(--danger)_8%,transparent)]"
            >
              {err}
            </div>
          )}

          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Search teammates…"
            className="w-full px-3 py-1.5 rounded-[9px] border-2 border-ink bg-bg-0 text-[13.5px] outline-none focus-visible:ring-2 focus-visible:ring-ai"
            autoFocus
          />

          {selected.size > 0 && (
            <div className="flex flex-wrap gap-1.5 px-1 pt-1">
              {Array.from(selected).map((id) => {
                const wm = workspaceMembers.find((m) => m.user.id === id);
                if (!wm) return null;
                return (
                  <GChip
                    key={id}
                    size="sm"
                    variant="ai"
                    onClick={() => toggleSelected(id)}
                    title="Remove"
                  >
                    {wm.user.full_name || wm.user.email}
                  </GChip>
                );
              })}
            </div>
          )}

          {loading ? (
            <div className="text-text-3 italic text-[13px] px-2 py-3">Loading…</div>
          ) : candidates.length === 0 ? (
            <div className="text-text-3 italic text-[13px] px-2 py-3">
              No matching teammates.
            </div>
          ) : (
            <ul className="flex flex-col gap-1">
              {candidates.map((wm) => {
                const checked = selected.has(wm.user.id);
                return (
                  <li key={wm.user.id}>
                    <button
                      type="button"
                      aria-pressed={checked}
                      onClick={() => toggleSelected(wm.user.id)}
                      className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-[9px] text-left transition-colors ${
                        checked
                          ? "bg-bg-2 outline-2 outline outline-ai"
                          : "hover:bg-bg-2"
                      }`}
                    >
                      <div className="flex-1 min-w-0">
                        <div className="text-[13.5px] text-text-0 truncate">
                          {wm.user.full_name || wm.user.email}
                        </div>
                        <div className="text-[12px] text-text-3 truncate">
                          {wm.user.email}
                        </div>
                      </div>
                      <GChip size="sm" variant="default">
                        {wm.role}
                      </GChip>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 py-3 px-4 border-t-2 border-dashed border-ink/40">
          <GButton type="button" variant="default" onClick={onClose} disabled={busy}>
            Cancel
          </GButton>
          <GButton
            type="button"
            variant="ai"
            onClick={() => void submit()}
            disabled={busy || selected.size === 0}
          >
            {busy ? "Opening…" : ctaLabel}
          </GButton>
        </div>
      </div>
    </div>
  );
}
