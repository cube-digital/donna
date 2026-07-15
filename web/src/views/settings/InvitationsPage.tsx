// Ported from assets/donna-ui-kit/react/InvitationsPage.jsx — full invitation
// list with a status filter + per-row actions.
import { useState } from "react";

import Icon from "../../components/kit/Icon";
import type { KitInvitation, KitInvitationStatus } from "./types";

const CHIP: Record<KitInvitationStatus, string> = {
  pending: "dn-chip--pending",
  accepted: "dn-chip--ok",
  revoked: "dn-chip--neutral",
  expired: "dn-chip--neutral",
};
const FILTERS = ["all", "pending", "accepted", "expired"] as const;
type Filter = (typeof FILTERS)[number];

export interface InvitationsPageProps {
  invitations?: KitInvitation[];
  onInvite?: (fd: FormData) => void;
  onResend?: (id: string) => void;
  onRevoke?: (id: string) => void;
  onCopyLink?: (id: string) => void;
}

export default function InvitationsPage({
  invitations = [],
  onInvite,
  onResend,
  onRevoke,
  onCopyLink,
}: InvitationsPageProps) {
  const [filter, setFilter] = useState<Filter>("all");
  const list =
    filter === "all"
      ? invitations
      : invitations.filter((i) => i.status === filter);
  const count = (s: string) =>
    invitations.filter((i) => i.status === s).length;

  return (
    <>
      <form
        style={{ display: "flex", gap: 9, marginBottom: 16 }}
        onSubmit={(e) => {
          e.preventDefault();
          onInvite?.(new FormData(e.currentTarget));
        }}
      >
        <input
          className="dn-input"
          name="email"
          placeholder="name@company.com"
          style={{ flex: 1 }}
        />
        <select className="dn-select" name="role" defaultValue="member">
          <option value="member">member</option>
          <option value="admin">admin</option>
          <option value="guest">guest</option>
        </select>
        <button className="dn-btn dn-btn--primary" type="submit">
          Send invite
        </button>
      </form>

      <div className="dn-pill-row" style={{ marginBottom: 13 }}>
        {FILTERS.map((f) => (
          <span
            key={f}
            className={`dn-pill ${filter === f ? "is-on" : ""}`}
            onClick={() => setFilter(f)}
          >
            {f === "all" ? `All · ${invitations.length}` : `${f} ${count(f)}`}
          </span>
        ))}
      </div>

      {list.map((inv) => (
        <div
          className={`dn-row ${inv.status === "expired" ? "dn-row--muted" : ""}`}
          key={inv.id}
        >
          <span className="dn-avatar dn-avatar--empty">
            <Icon name={inv.status === "expired" ? "mail-off" : "mail"} />
          </span>
          <div>
            <div className="dn-name">{inv.email}</div>
            <div className="dn-meta">
              {inv.role} · invited by {inv.invited_by} · {inv.when}
            </div>
          </div>
          <div className="dn-actions">
            <span className={`dn-chip ${CHIP[inv.status]}`}>{inv.status}</span>
            {inv.status === "pending" && (
              <>
                <button
                  className="dn-mini"
                  onClick={() => onCopyLink?.(inv.id)}
                >
                  <Icon name="link" size={13} />
                  Copy link
                </button>
                <button
                  className="dn-mini dn-mini--grape"
                  onClick={() => onResend?.(inv.id)}
                >
                  Resend
                </button>
                <button
                  className="dn-mini dn-mini--danger"
                  onClick={() => onRevoke?.(inv.id)}
                >
                  Revoke
                </button>
              </>
            )}
            {inv.status === "expired" && (
              <button
                className="dn-mini dn-mini--grape"
                onClick={() => onResend?.(inv.id)}
              >
                Re-invite
              </button>
            )}
          </div>
        </div>
      ))}
    </>
  );
}
