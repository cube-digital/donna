// InviteToWorkspaceDialog — email-based workspace invitation.
//
// Sysadmin enters an email + role; backend creates a signed token and
// sends a Django-template SMTP email. UI shows confirmation and the
// pending list refreshes on close.

import { useEffect, useState } from "react";

import {
  createInvitation,
  listInvitations,
  revokeInvitation,
} from "../../api/workspaces";
import type { WorkspaceInvitation, WorkspaceRole } from "../../types";

interface InviteToWorkspaceDialogProps {
  open: boolean;
  onClose: () => void;
}

export function InviteToWorkspaceDialog({
  open,
  onClose,
}: InviteToWorkspaceDialogProps) {
  const [pending, setPending] = useState<WorkspaceInvitation[]>([]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<WorkspaceRole>("member");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setEmail("");
    setErr(null);
    setSuccess(null);
    listInvitations().then(setPending).catch(() => setPending([]));
  }, [open]);

  const send = async (e: React.FormEvent) => {
    e.preventDefault();
    const v = email.trim();
    if (!v) {
      setErr("Email is required.");
      return;
    }
    setBusy(true);
    setErr(null);
    setSuccess(null);
    try {
      const created = await createInvitation(v, role);
      setSuccess(`Invitation sent to ${v}`);
      setPending([created, ...pending.filter((p) => p.email !== v)]);
      setEmail("");
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Failed to send invitation.");
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (inv: WorkspaceInvitation) => {
    try {
      await revokeInvitation(inv.id);
      setPending(pending.filter((p) => p.id !== inv.id));
    } catch {
      /* ignore */
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
      <div className="bg-bg-1 border-2 border-ink rounded-[14px] shadow-ink-2 w-[520px] max-w-[90vw] max-h-[85vh] flex flex-col">
        <header className="flex items-center justify-between px-4 py-3 border-b-2 border-dashed border-ink/40">
          <div className="font-display font-semibold text-[15px]">
            Invite to workspace
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
        <form onSubmit={send} className="p-4 flex flex-col gap-2.5 border-b border-dashed border-ink/40">
          <label className="text-[12px] font-semibold">Email</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="teammate@example.com"
            autoFocus
            className="w-full px-2 py-1.5 text-[13px] border-2 border-ink rounded-[8px] bg-bg-0 outline-none focus:ring-2 focus:ring-ai/30"
          />
          <label className="text-[12px] font-semibold">Role</label>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value as WorkspaceRole)}
            className="w-full px-2 py-1.5 text-[13px] border-2 border-ink rounded-[8px] bg-bg-0"
          >
            <option value="member">Member</option>
            <option value="admin">Admin</option>
            <option value="guest">Guest</option>
          </select>
          {err && <div className="text-[12px] text-danger">{err}</div>}
          {success && <div className="text-[12px] text-ai">{success}</div>}
          <button
            type="submit"
            disabled={busy || !email}
            className="self-end px-4 py-1.5 text-[13px] border-2 border-ink rounded-[8px] bg-ai text-white disabled:opacity-50"
          >
            {busy ? "Sending…" : "Send invitation"}
          </button>
        </form>

        <div className="flex-1 overflow-y-auto p-3">
          <div className="text-[11px] uppercase tracking-wide text-text-2 mb-1.5">
            Pending invitations
          </div>
          {pending.length === 0 ? (
            <div className="text-[12px] text-text-2">No pending invitations.</div>
          ) : (
            <ul className="flex flex-col gap-1">
              {pending.map((p) => (
                <li
                  key={p.id}
                  className="flex items-center justify-between px-2 py-1.5 border border-ink/20 rounded-[8px]"
                >
                  <div className="min-w-0 flex-1">
                    <div className="text-[13px] truncate">{p.email}</div>
                    <div className="text-[10px] text-text-2">
                      {p.role} · expires {new Date(p.expires_at).toLocaleDateString()}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => revoke(p)}
                    className="text-[11px] text-danger hover:underline"
                  >
                    Revoke
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
