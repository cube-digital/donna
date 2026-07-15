import Icon from "./Icon";

const ROLES = ["owner", "admin", "member", "guest"];

export default function MembersPage({ members = [], invitations = [], canAdmin = true,
  onInvite, onRoleChange, onRemove, onResend, onRevoke }) {
  const pending = invitations.filter((i) => i.status === "pending");
  return (
    <>
      {canAdmin && (
        <>
          <div className="dn-section">Invite by email</div>
          <form className="dn-invite" style={{ display: "flex", gap: 9, marginBottom: 18 }}
                onSubmit={(e) => { e.preventDefault(); onInvite?.(new FormData(e.currentTarget)); }}>
            <input className="dn-input" name="email" placeholder="name@company.com" style={{ flex: 1 }} />
            <select className="dn-select" name="role" defaultValue="member">
              {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
            <button className="dn-btn dn-btn--primary" type="submit">Send invite</button>
          </form>
        </>
      )}

      <div className="dn-section">Members · {members.length}</div>
      {members.map((m) => (
        <div className="dn-row" key={m.id}>
          <span className="dn-avatar" style={{ background: m.color ?? "var(--dn-grape)" }}>{m.initials}</span>
          <div>
            <div className="dn-name">{m.name}{m.is_you && <span style={{ color: "var(--dn-t4)", fontWeight: 500 }}> (you)</span>}</div>
            <div className="dn-meta">{m.email}{m.joined ? ` · joined ${m.joined}` : ""}</div>
          </div>
          <div className="dn-actions">
            {canAdmin && m.role !== "owner" ? (
              <select className="dn-mini" value={m.role} onChange={(e) => onRoleChange?.(m.id, e.target.value)}>
                {ROLES.filter((r) => r !== "owner").map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
            ) : (
              <span className="dn-chip dn-chip--grape">{m.role}</span>
            )}
            {canAdmin && m.role !== "owner" && (
              <button className="dn-mini dn-mini--danger" onClick={() => onRemove?.(m.id)}>Remove</button>
            )}
          </div>
        </div>
      ))}

      {pending.length > 0 && (
        <>
          <div className="dn-section">Pending invitations · {pending.length}</div>
          {pending.map((inv) => (
            <div className="dn-row dn-row--dashed" key={inv.id}>
              <span className="dn-avatar dn-avatar--empty"><Icon name="mail" /></span>
              <div>
                <div className="dn-name">{inv.email}</div>
                <div className="dn-meta">{inv.role} · invited by {inv.invited_by} · expires {inv.expires_in}</div>
              </div>
              <div className="dn-actions">
                <span className="dn-chip dn-chip--pending">pending</span>
                <button className="dn-mini dn-mini--grape" onClick={() => onResend?.(inv.id)}>Resend</button>
                <button className="dn-mini dn-mini--danger" onClick={() => onRevoke?.(inv.id)}>Revoke</button>
              </div>
            </div>
          ))}
        </>
      )}
    </>
  );
}
