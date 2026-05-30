// Modal for creating a new channel.
//
// Slack/Discord vibe — one field, a `#` glyph baked into the input, name
// auto-normalized to lowercase + dashes as the user types. Visibility is
// public unless the toggle says otherwise. No slug / topic — those can be
// edited from the channel header menu after creation.
//
// On success calls `onCreated(channel)` so the caller can route to it.

import { useEffect, useRef, useState } from "react";

import { useChannels } from "../../state/channels";
import type { Channel } from "../../types";
import { Button } from "../Ui/Button";
import { Field } from "../Ui/Field";
import { Toggle } from "../Ui/Toggle";

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

export function CreateChannelDialog({
  open,
  onClose,
  onCreated,
}: CreateChannelDialogProps) {
  const create = useChannels((s) => s.createChannel);

  const [name, setName] = useState("");
  const [isPrivate, setIsPrivate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const nameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setName("");
      setIsPrivate(false);
      setBusy(false);
      setErr(null);
      setTimeout(() => nameRef.current?.focus(), 0);
    }
  }, [open]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const finalName = name.replace(/-+$/, ""); // trim trailing hyphen for submit

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!finalName) {
      setErr("Channel name is required");
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
      setErr(e instanceof Error ? e.message : "Failed to create channel");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Create a channel"
      className="fixed inset-0 z-50 grid place-items-center bg-black/40"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <form
        onSubmit={submit}
        className="bg-bg-1 border border-border-strong rounded-xl shadow-elevated w-[420px] max-w-[90vw] flex flex-col"
      >
        {/* Header */}
        <div className="flex items-center justify-between py-3 px-4 border-b border-border-soft">
          <div className="text-[13px] font-semibold text-text-0">
            Create a channel
          </div>
          <button
            type="button"
            onClick={onClose}
            className="w-6 h-6 grid place-items-center rounded-sm text-text-3 hover:bg-bg-2 hover:text-text-0"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        {/* Body */}
        <div className="flex flex-col gap-3 px-4 py-3">
          {err && (
            <div className="py-1.5 px-2 rounded-md border border-danger text-danger text-[12px] bg-[color-mix(in_oklch,var(--danger)_8%,transparent)]">
              {err}
            </div>
          )}

          <Field
            label="Channel name"
            htmlFor="channel-name"
            required
            hint="Lowercase. Use dashes for spaces."
          >
            <div className="flex items-center h-7 px-2.5 text-[13px] bg-bg-2 border border-border-soft rounded-md focus-within:border-border-strong">
              <span className="text-text-3 mr-1 select-none">#</span>
              <input
                ref={nameRef}
                id="channel-name"
                value={name}
                onChange={(e) => setName(normalizeName(e.target.value))}
                placeholder="design-reviews"
                maxLength={80}
                className="flex-1 bg-transparent outline-none text-text-0 placeholder:text-text-3"
              />
            </div>
          </Field>

          <Field
            label="Private channel"
            hint="Invite-only. Public channels are visible to anyone in the workspace."
          >
            <div className="flex items-center gap-2">
              <Toggle
                checked={isPrivate}
                onChange={setIsPrivate}
                aria-label="Make channel private"
              />
              <span className="text-[13px] text-text-1">
                {isPrivate ? "Private" : "Public"}
              </span>
            </div>
          </Field>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 py-3 px-4 border-t border-border-soft">
          <Button type="button" variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            type="submit"
            variant="primary"
            disabled={busy || !finalName}
          >
            {busy ? "Creating…" : "Create"}
          </Button>
        </div>
      </form>
    </div>
  );
}
