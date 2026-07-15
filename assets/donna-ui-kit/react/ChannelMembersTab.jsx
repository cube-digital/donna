import { useState } from "react";
import Icon from "./Icon";

const ROLES = ["admin", "member"];   // ChannelMembership.Role

/**
 * Two distinct invite paths — this is the bit most apps muddle:
 *   1. Add from workspace  → person already exists, one click (uses mention-candidates)
 *   2. Invite by email     → creates the workspace invite AND queues them into
 *                            this channel, so they land where they were invited.
 */
export default function ChannelMembersTab({
  members = [], candidates = [], isChannelAdmin,
  onAddMember, onInviteByEmail, onRoleChange, onRemoveMember,
}) {
  const [q, setQ] = useState("");
  const matches = candidates.filter(
    (c) => !q || `${c.name} ${c.email}`.toLowerCase().includes(q.toLowerCase())
  );

  return (
    <>
      {isChannelAdmin && (
        <>
          <div className="dn-section">Add people</div>
          <div style={{ display: "flex", gap: 8, marginBottom: 13 }}>
            <input className="dn-input" placeholder="Search teammates…" style={{ flex: 1 }}
                   value={q} onChange={(e) => setQ(e.target.value)} />
          </div>

          {matches.map((c) => (
            <div className="dn-row dn-row--dashed" key={c.id}>
              <span className="dn-avatar" style={{ background: c.color }}>{c.initials}</span>
              <div>
                <div className="dn-name">{c.name}</div>
                <div className="dn-meta">{c.email} · in workspace, not in this channel</div>
              </div>
              <button className="dn-mini dn-mini--grape dn-spacer" onClick={() => onAddMember?.(c.id)}>
                + Add to channel
              </button>
            </div>
          ))}

          <form className="dn-row dn-row--dashed"
                onSubmit={(e) => { e.preventDefault(); onInviteByEmail?.(new FormData(e.currentTarget)); }}>
            <span className="dn-avatar dn-avatar--empty"><Icon name="mail" /></span>
            <div style={{ flex: 1 }}>
              <div className="dn-name">Invite by email</div>
              <div className="dn-meta">Adds them to the workspace <b>and</b> drops them into this channel</div>
            </div>
            <input className="dn-input" name="email" placeholder="name@company.com" style={{ maxWidth: 200 }} />
            <button className="dn-mini dn-mini--grape" type="submit">Invite</button>
          </form>
        </>
      )}

      <div className="dn-section" style={{ marginTop: 18 }}>In this channel · {members.length}</div>
      {members.map((m) => (
        <div className="dn-row" key={m.id}>
          <span className="dn-avatar" style={{ background: m.color ?? "var(--dn-grape)" }}>{m.initials}</span>
          <div>
            <div className="dn-name">
              {m.name}{m.is_you && <span style={{ color: "var(--dn-t4)", fontWeight: 500 }}> (you)</span>}
            </div>
            <div className="dn-meta">{m.email}</div>
          </div>
          <div className="dn-actions">
            {isChannelAdmin && !m.is_you ? (
              <>
                <select className="dn-mini" value={m.role}
                        onChange={(e) => onRoleChange?.(m.id, e.target.value)}>
                  {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
                <button className="dn-mini dn-mini--danger" onClick={() => onRemoveMember?.(m.id)}>Remove</button>
              </>
            ) : (
              <span className="dn-chip dn-chip--grape">{m.role}</span>
            )}
          </div>
        </div>
      ))}
    </>
  );
}
