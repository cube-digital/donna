// InviteToChannelDialog — add existing workspace members to a channel.

import { useEffect, useMemo, useState } from "react";

import { addChannelMember } from "../../api/chat";
import { listMembers, type WorkspaceMemberRow } from "../../api/workspaces";

interface InviteToChannelDialogProps {
  open: boolean;
  channelId: string;
  existingMemberIds: string[];
  onClose: () => void;
  onAdded?: (userId: string) => void;
}

export function InviteToChannelDialog({
  open,
  channelId,
  existingMemberIds,
  onClose,
  onAdded,
}: InviteToChannelDialogProps) {
  const [members, setMembers] = useState<WorkspaceMemberRow[]>([]);
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setFilter("");
    setErr(null);
    listMembers()
      .then(setMembers)
      .catch((e: unknown) =>
        setErr(e instanceof Error ? e.message : "Failed to load members."),
      );
  }, [open]);

  const filtered = useMemo(() => {
    const have = new Set(existingMemberIds);
    const q = filter.trim().toLowerCase();
    return members
      .filter((m) => !have.has(m.user.id))
      .filter(
        (m) =>
          !q ||
          m.user.email.toLowerCase().includes(q) ||
          (m.user.full_name || "").toLowerCase().includes(q),
      );
  }, [members, filter, existingMemberIds]);

  const add = async (m: WorkspaceMemberRow) => {
    setBusy(m.user.id);
    try {
      await addChannelMember(channelId, m.user.id);
      onAdded?.(m.user.id);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Failed to add member.");
    } finally {
      setBusy(null);
    }
  };

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={(e) => e.target === e.currentTarget && onClose()}
      className="fixed inset-0 z-50 grid place-items-center bg-ink/40"
    >
      <div className="bg-bg-1 border-2 border-ink rounded-[14px] shadow-ink-2 w-[460px] max-w-[90vw] max-h-[80vh] flex flex-col">
        <header className="flex items-center justify-between px-4 py-3 border-b-2 border-dashed border-ink/40">
          <div className="font-display font-semibold text-[15px]">
            Add members to channel
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-text-2 hover:text-text-0 text-[20px] leading-none"
            aria-label="Close"
          >
            ×
          </button>
        </header>
        <div className="p-3">
          <input
            type="text"
            autoFocus
            placeholder="Search workspace members…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="w-full px-2 py-1.5 text-[13px] border-2 border-ink rounded-[8px] bg-bg-0 outline-none focus:ring-2 focus:ring-ai/30"
          />
          {err && <div className="mt-2 text-[12px] text-danger">{err}</div>}
        </div>
        <ul className="flex-1 overflow-y-auto px-2 pb-2">
          {filtered.map((m) => (
            <li key={m.user.id}>
              <button
                type="button"
                disabled={busy === m.user.id}
                onClick={() => add(m)}
                className="w-full text-left px-2 py-1.5 rounded hover:bg-bg-2 disabled:opacity-50 flex items-center justify-between"
              >
                <span className="truncate text-[13px]">
                  {m.user.full_name || m.user.email}
                </span>
                <span className="text-[11px] text-ai font-semibold">+ Add</span>
              </button>
            </li>
          ))}
          {filtered.length === 0 && (
            <li className="text-center text-[12px] text-text-2 py-3">
              No more workspace members to add.
            </li>
          )}
        </ul>
      </div>
    </div>
  );
}
