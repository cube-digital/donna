export default function GeneralPage({ workspace, role = "owner", onSave, onDelete }) {
  const canEdit = role === "owner" || role === "admin";
  return (
    <>
      <div className="dn-grid-2">
        <div>
          <div className="dn-field">
            <div className="dn-label">Workspace name</div>
            <input className="dn-input" defaultValue={workspace.name} disabled={!canEdit} />
          </div>
          <div className="dn-field">
            <div className="dn-label">Workspace URL</div>
            <input className="dn-input" defaultValue={`donna.app/${workspace.slug}`} disabled={!canEdit} />
            <div className="dn-hint">Changing this breaks existing links.</div>
          </div>
          <div className="dn-field">
            <div className="dn-label">Primary domain</div>
            <input className="dn-input" defaultValue={workspace.primary_domain} disabled={!canEdit} />
            <div className="dn-hint">
              People with this email domain are treated as internal — Donna files their meetings
              and emails under your workspace, not under a client org.
            </div>
          </div>
        </div>
        <div style={{ width: 200 }}>
          <div className="dn-section">Icon</div>
          <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
            <div className="dn-square">{workspace.name?.[0]}</div>
            {canEdit && <button className="dn-mini">Change</button>}
          </div>
          <div className="dn-section">Your role</div>
          <span className="dn-chip dn-chip--grape">{role}</span>
        </div>
      </div>

      {canEdit && (
        <div style={{ display: "flex", gap: 9, margin: "6px 0 20px" }}>
          <button className="dn-btn dn-btn--primary" onClick={onSave}>Save changes</button>
          <button className="dn-btn dn-btn--ghost">Cancel</button>
        </div>
      )}

      {role === "owner" && (
        <>
          <div className="dn-section" style={{ color: "var(--dn-danger)" }}>Danger zone</div>
          <div className="dn-danger-zone">
            <div>
              <div className="dn-name" style={{ color: "var(--dn-danger)" }}>Delete this workspace</div>
              <div className="dn-meta">Permanently removes all channels, documents and cortex memory.</div>
            </div>
            <button className="dn-btn dn-btn--danger dn-spacer" onClick={onDelete}>Delete</button>
          </div>
        </>
      )}
    </>
  );
}
