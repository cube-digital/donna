// Channel members admin dialog — opened from the channel actions menu.
//
// Two columns of the same page:
//   - Members: current ChannelMembership rows, each with a "Remove"
//     action. Self-row shows "Leave" instead.
//   - Add: workspace members not yet in the channel, each with an "Add"
//     action.
//
// Server enforces:
//   * GET   /chat/channels/{id}/members/                 requires channel membership
//   * POST  /chat/channels/{id}/members/ {user_id, role} requires channel ADMIN
//                                                         (or member when channel.settings.allow_member_invites)
//   * DELETE /chat/channels/{id}/members/{user_id}/      self-leave OR admin-kick
//
// We surface backend errors through the local error banner; the dialog
// stays open after each row mutation so the admin can batch-edit.

import { useEffect, useId, useMemo, useRef, useState } from "react";

import { addMember, listMembers, removeMember } from "../../api/chat";
import { listWorkspaceMembers } from "../../api/workspaces";
import type {
  Channel,
  ChannelMembership,
  User,
  WorkspaceMembership,
} from "../../types";
import { GButton, GChip, GIconButton } from "../Goofy";

interface ManageMembersDialogProps {
  channel: Channel;
  open: boolean;
  onClose: () => void;
}

const FOCUSABLE_SELECTOR =
  'a[href],area[href],input:not([disabled]):not([type="hidden"]),select:not([disabled]),textarea:not([disabled]),button:not([disabled]),iframe,object,embed,[contenteditable="true"],[tabindex]:not([tabindex="-1"])';

export function ManageMembersDialog({
  channel,
  open,
  onClose,
}: ManageMembersDialogProps) {
  const titleId = useId();

  const [memberships, setMemberships] = useState<ChannelMembership[]>([]);
  const [workspaceMembers, setWorkspaceMembers] = useState<WorkspaceMembership[]>([]);
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
    void Promise.all([
      listMembers(channel.id).catch(() => [] as ChannelMembership[]),
      listWorkspaceMembers().catch(() => [] as WorkspaceMembership[]),
    ])
      .then(([chm, wsm]) => {
        if (cancelled) return;
        setMemberships(chm);
        setWorkspaceMembers(wsm);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, channel.id]);

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

  // Map of user_id → User for fast lookup when rendering memberships
  // (the ChannelMembership rows only carry the UUID; the user objects
  // live on the workspace membership rows).
  const userById = useMemo(() => {
    const out = new Map<string, User>();
    for (const wm of workspaceMembers) out.set(wm.user.id, wm.user);
    return out;
  }, [workspaceMembers]);

  // Workspace members not yet in this channel — candidates for "Add".
  const addable = useMemo(() => {
    const inChannel = new Set(memberships.map((m) => m.user));
    return workspaceMembers
      .filter((wm) => !inChannel.has(wm.user.id))
      .sort((a, b) =>
        (a.user.full_name || a.user.email).localeCompare(
          b.user.full_name || b.user.email,
        ),
      );
  }, [memberships, workspaceMembers]);

  if (!open) return null;

  async function handleAdd(userId: string) {
    setBusyId(userId);
    setErr(null);
    try {
      const row = await addMember(channel.id, userId);
      setMemberships((prev) => [...prev, row]);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Failed to add member.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleRemove(userId: string) {
    setBusyId(userId);
    setErr(null);
    try {
      await removeMember(channel.id, userId);
      setMemberships((prev) => prev.filter((m) => m.user !== userId));
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Failed to remove member.");
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
        className="bg-bg-1 border-2 border-ink rounded-[14px] shadow-ink-2 w-[560px] max-w-[92vw] max-h-[80vh] flex flex-col"
      >
        <div className="flex items-center justify-between py-3 px-4 border-b-2 border-dashed border-ink/40">
          <div
            id={titleId}
            className="font-display font-semibold text-text-0 text-[15px]"
          >
            Members of #{channel.name || "this channel"}
          </div>
          <GIconButton icon="x" size="sm" onClick={onClose} aria-label="Close dialog" />
        </div>

        <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-3">
          {err && (
            <div
              role="alert"
              aria-live="assertive"
              className="py-1.5 px-2.5 rounded-[9px] border-2 border-danger text-danger text-[12.5px] bg-[color-mix(in_oklch,var(--danger)_8%,transparent)]"
            >
              {err}
            </div>
          )}

          {loading ? (
            <div className="text-text-3 italic text-[13px] px-2 py-3">Loading…</div>
          ) : (
            <>
              <section>
                <h3 className="font-display font-semibold text-[12.5px] text-text-2 px-1 pb-1">
                  In this channel ({memberships.length})
                </h3>
                <ul className="flex flex-col gap-1">
                  {memberships.length === 0 ? (
                    <li className="text-text-3 italic text-[13px] px-2 py-2">
                      No members yet.
                    </li>
                  ) : (
                    memberships.map((m) => {
                      const u = userById.get(m.user);
                      const label = u
                        ? u.full_name || u.email
                        : `user ${m.user.slice(0, 8)}…`;
                      return (
                        <li
                          key={m.id}
                          className="flex items-center gap-2 px-2 py-1.5 rounded-[9px] hover:bg-bg-2"
                        >
                          <div className="flex-1 min-w-0">
                            <div className="text-[13.5px] text-text-0 truncate">
                              {label}
                            </div>
                            {u?.email && u.email !== label ? (
                              <div className="text-[12px] text-text-3 truncate">
                                {u.email}
                              </div>
                            ) : null}
                          </div>
                          <GChip size="sm" variant={m.role === "admin" ? "ai" : "default"}>
                            {m.role}
                          </GChip>
                          <GButton
                            size="sm"
                            variant="default"
                            disabled={busyId === m.user}
                            onClick={() => void handleRemove(m.user)}
                          >
                            {busyId === m.user ? "…" : "Remove"}
                          </GButton>
                        </li>
                      );
                    })
                  )}
                </ul>
              </section>

              <section>
                <h3 className="font-display font-semibold text-[12.5px] text-text-2 px-1 pb-1 pt-1">
                  Add from workspace ({addable.length})
                </h3>
                <ul className="flex flex-col gap-1">
                  {addable.length === 0 ? (
                    <li className="text-text-3 italic text-[13px] px-2 py-2">
                      Everyone in the workspace is already in this channel.
                    </li>
                  ) : (
                    addable.map((wm) => (
                      <li
                        key={wm.user.id}
                        className="flex items-center gap-2 px-2 py-1.5 rounded-[9px] hover:bg-bg-2"
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
                        <GButton
                          size="sm"
                          variant="ai"
                          disabled={busyId === wm.user.id}
                          onClick={() => void handleAdd(wm.user.id)}
                        >
                          {busyId === wm.user.id ? "Adding…" : "Add"}
                        </GButton>
                      </li>
                    ))
                  )}
                </ul>
              </section>
            </>
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
