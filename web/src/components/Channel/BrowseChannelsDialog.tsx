// Modal listing every public channel in the active workspace, with a
// per-row "Join" button when the caller isn't already a member.
//
// Wire flow on click:
//   1. POST /chat/channels/{id}/members/ with empty body (self-join).
//   2. Server adds the row, broadcasts `channel.added.to_you` on
//      `presence-user-{uid}` — AppShell's WS handler upserts the
//      channel into the store, so the sidebar gains the row even if
//      this dialog is closed before the request completes.
//   3. Locally drop the row from the "browsable" list immediately for
//      optimistic UX; the server-side broadcast covers correctness.
//
// We deliberately do NOT route to the newly-joined channel. Slack +
// Discord both leave the user inside the browse surface so they can
// scan and join several at once.
//
// Accessibility / focus management mirrors CreateChannelDialog.

import { useEffect, useId, useMemo, useRef, useState } from "react";

import { joinChannel, listChannels } from "../../api/chat";
import { useChannels } from "../../state/channels";
import type { Channel } from "../../types";
import { GButton, GChip, GIconButton } from "../Goofy";

interface BrowseChannelsDialogProps {
  open: boolean;
  onClose: () => void;
}

const FOCUSABLE_SELECTOR =
  'a[href],area[href],input:not([disabled]):not([type="hidden"]),select:not([disabled]),textarea:not([disabled]),button:not([disabled]),iframe,object,embed,[contenteditable="true"],[tabindex]:not([tabindex="-1"])';

export function BrowseChannelsDialog({
  open,
  onClose,
}: BrowseChannelsDialogProps) {
  const titleId = useId();
  const memberIds = useChannels((s) => new Set(s.channels.map((c) => c.id)));
  const upsertChannel = useChannels((s) => s.upsertFromEvent);

  const [allChannels, setAllChannels] = useState<Channel[]>([]);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const containerRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) {
      previousFocusRef.current?.focus?.();
      return;
    }
    previousFocusRef.current = document.activeElement as HTMLElement | null;
    setErr(null);
    setLoading(true);
    let cancelled = false;
    void listChannels({ includePublic: true })
      .then((data) => {
        if (!cancelled) {
          // Browse is for named channels only. DMs are private + opened
          // via DMOpen / GroupDMOpen, never browsable.
          setAllChannels(data.filter((c) => c.kind === "channel"));
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setErr(e instanceof Error ? e.message : "Failed to load channels.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  // Escape + tab trap.
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

  const browsable = useMemo(
    () =>
      allChannels
        .filter((c) => c.visibility === "public")
        .sort((a, b) => a.name.localeCompare(b.name)),
    [allChannels],
  );

  if (!open) return null;

  async function handleJoin(channel: Channel) {
    setBusyId(channel.id);
    setErr(null);
    try {
      await joinChannel(channel.id);
      // Optimistic: also upsert immediately. The server's WS broadcast
      // (channel.added.to_you on the caller's presence group) will
      // arrive shortly and re-upsert idempotently.
      upsertChannel(channel);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Failed to join channel.");
    } finally {
      setBusyId(null);
    }
  }

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
        className="bg-bg-1 border-2 border-ink rounded-[14px] shadow-ink-2 w-[520px] max-w-[92vw] max-h-[80vh] flex flex-col"
      >
        <div className="flex items-center justify-between py-3 px-4 border-b-2 border-dashed border-ink/40">
          <div
            id={titleId}
            className="font-display font-semibold text-text-0 text-[15px]"
          >
            Browse channels
          </div>
          <GIconButton icon="x" size="sm" onClick={onClose} aria-label="Close dialog" />
        </div>

        <div className="flex-1 overflow-y-auto p-3">
          {err && (
            <div
              role="alert"
              aria-live="assertive"
              className="mb-2 py-1.5 px-2.5 rounded-[9px] border-2 border-danger text-danger text-[12.5px] bg-[color-mix(in_oklch,var(--danger)_8%,transparent)]"
            >
              {err}
            </div>
          )}

          {loading ? (
            <div className="text-text-3 italic text-[13px] px-2 py-3">Loading…</div>
          ) : browsable.length === 0 ? (
            <div className="text-text-3 italic text-[13px] px-2 py-3">
              No public channels in this workspace yet.
            </div>
          ) : (
            <ul className="flex flex-col gap-1">
              {browsable.map((c) => {
                const joined = memberIds.has(c.id);
                return (
                  <li
                    key={c.id}
                    className="flex items-center gap-2 px-2 py-1.5 rounded-[9px] hover:bg-bg-2"
                  >
                    <span className="font-mono text-text-3">#</span>
                    <div className="flex-1 min-w-0">
                      <div className="text-[13.5px] text-text-0 font-medium truncate">
                        {c.name}
                      </div>
                      {c.topic ? (
                        <div className="text-[12px] text-text-3 truncate">{c.topic}</div>
                      ) : null}
                    </div>
                    {joined ? (
                      <GChip variant="default" size="sm">
                        Joined
                      </GChip>
                    ) : (
                      <GButton
                        size="sm"
                        variant="ai"
                        disabled={busyId === c.id}
                        onClick={() => void handleJoin(c)}
                      >
                        {busyId === c.id ? "Joining…" : "Join"}
                      </GButton>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 py-3 px-4 border-t-2 border-dashed border-ink/40">
          <GButton type="button" variant="default" onClick={onClose}>
            Done
          </GButton>
        </div>
      </div>
    </div>
  );
}
