// Modal for creating a new channel.
//
// Slack/Discord vibe — one field, a `#` glyph baked into the input, name
// auto-normalized to lowercase + dashes as the user types. Visibility is
// public unless the toggle says otherwise. No slug / topic — those can be
// edited from the channel header menu after creation.
//
// On success calls `onCreated(channel)` so the caller can route to it.
//
// Accessibility / UX checklist
// ─────────────────────────────
//   * role="dialog" + aria-modal="true" + aria-labelledby on the title
//   * Esc closes; click-outside closes
//   * Focus is trapped inside the dialog while open (Tab cycles within)
//   * On close, focus is restored to whatever owned it before open
//   * `overscroll-behavior: contain` on the body so rubber-band scroll
//     doesn't bleed past the modal on touch devices
//   * Error region has role="alert" / aria-live so failures get
//     announced to screen readers
//   * The name input uses the Goofy `<GInput/>` pill (chunky ink
//     border, AI focus ring) instead of a bare element, with a `#`
//     prefix slot rendered inside the input via `icon={null}` + a
//     custom leading span.

import { useEffect, useId, useRef, useState } from "react";

import { useChannels } from "../../state/channels";
import type { Channel } from "../../types";
import { GButton, GFormField, GIconButton, GInput, GSwitch } from "../Goofy";

interface CreateChannelDialogProps {
  open: boolean;
  onClose: () => void;
  onCreated?: (channel: Channel) => void;
}

// Slack-style name normalization: lowercase, swap whitespace + punctuation
// for hyphens, strip leading/trailing hyphens, cap at 80 chars.
function normalizeName(raw: string): string {
  return raw
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/-{2,}/g, "-")
    .replace(/^-+/, "")
    .slice(0, 80);
}

// Match every focusable element inside the dialog. Excludes
// `[tabindex="-1"]` so disabled-but-present rows (e.g. Workflows stub)
// stay out of the tab tour.
const FOCUSABLE_SELECTOR =
  'a[href],area[href],input:not([disabled]):not([type="hidden"]),select:not([disabled]),textarea:not([disabled]),button:not([disabled]),iframe,object,embed,[contenteditable="true"],[tabindex]:not([tabindex="-1"])';

export function CreateChannelDialog({
  open,
  onClose,
  onCreated,
}: CreateChannelDialogProps) {
  const create = useChannels((s) => s.createChannel);
  const titleId = useId();
  const errorId = useId();

  const [name, setName] = useState("");
  const [isPrivate, setIsPrivate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const formRef = useRef<HTMLFormElement>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  // Reset state + capture pre-open focus owner each time the dialog
  // re-opens. The autofocus + focus-restore work happens in the
  // open-effect below.
  useEffect(() => {
    if (open) {
      setName("");
      setIsPrivate(false);
      setBusy(false);
      setErr(null);
      previousFocusRef.current = document.activeElement as HTMLElement | null;
      // Microtask delay so the input ref is wired by the time we focus.
      const id = window.setTimeout(() => nameRef.current?.focus(), 0);
      return () => window.clearTimeout(id);
    }
    // On close, return focus to the element that owned it before open
    // (typically the "+ add channel" trigger in the sidebar).
    previousFocusRef.current?.focus?.();
  }, [open]);

  // Close on Escape + trap Tab navigation inside the dialog while open.
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key !== "Tab") return;
      const root = formRef.current;
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

  if (!open) return null;

  const finalName = name.replace(/-+$/, ""); // trim trailing hyphen for submit

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!finalName) {
      setErr("Channel name is required.");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const channel = await create({
        name: finalName,
        visibility: isPrivate ? "private" : "public",
      });
      onCreated?.(channel);
      onClose();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Failed to create channel.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      // `overscroll-contain` blocks the rubber-band scroll-chain on
      // touch devices so swiping inside the dialog doesn't bleed past
      // it onto the page.
      className="fixed inset-0 z-50 grid place-items-center bg-ink/40 overscroll-contain"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <form
        ref={formRef}
        onSubmit={submit}
        className="bg-bg-1 border-2 border-ink rounded-[14px] shadow-ink-2 w-[440px] max-w-[90vw] flex flex-col"
      >
        {/* Header */}
        <div className="flex items-center justify-between py-3 px-4 border-b-2 border-dashed border-ink/40">
          <div
            id={titleId}
            className="font-display font-semibold text-text-0 text-[15px]"
          >
            Create a channel
          </div>
          <GIconButton
            icon="x"
            size="sm"
            onClick={onClose}
            aria-label="Close dialog"
          />
        </div>

        {/* Body */}
        <div className="flex flex-col gap-3 px-4 py-3.5">
          {err && (
            <div
              id={errorId}
              role="alert"
              aria-live="assertive"
              className="py-1.5 px-2.5 rounded-[9px] border-2 border-danger text-danger text-[12.5px] bg-[color-mix(in_oklch,var(--danger)_8%,transparent)]"
            >
              {err}
            </div>
          )}

          <GFormField
            label="Channel name"
            required
            hint="Lowercase. Use dashes for spaces."
          >
            <GInput
              ref={nameRef}
              value={name}
              onChange={(e) => setName(normalizeName(e.target.value))}
              placeholder="design-reviews…"
              maxLength={80}
              icon="hash"
              required
              autoComplete="off"
              spellCheck={false}
              aria-describedby={err ? errorId : undefined}
              aria-invalid={!!err}
            />
          </GFormField>

          <GFormField
            label="Private channel"
            hint="Invite-only. Public channels are visible to anyone in the workspace."
          >
            <div className="flex items-center gap-2">
              <GSwitch
                on={isPrivate}
                onChange={setIsPrivate}
                aria-label="Make channel private"
              />
              <span className="text-[13px] text-text-1">
                {isPrivate ? "Private" : "Public"}
              </span>
            </div>
          </GFormField>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 py-3 px-4 border-t-2 border-dashed border-ink/40">
          <GButton type="button" variant="default" onClick={onClose} disabled={busy}>
            Cancel
          </GButton>
          <GButton type="submit" variant="ai" disabled={busy || !finalName}>
            {busy ? "Creating…" : "Create"}
          </GButton>
        </div>
      </form>
    </div>
  );
}
