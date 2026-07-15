import Icon from "./Icon";

const NAV = [
  { group: "workspace" },
  { key: "general",     label: "General",     icon: "settings" },
  { key: "members",     label: "Members",     icon: "users" },
  { key: "invitations", label: "Invitations", icon: "mail" },
  { group: "integrations" },
  { key: "connections", label: "Connections", icon: "plug" },
  { key: "agents",      label: "Agents",      icon: "sparkles" },
  { group: "advanced" },
  { key: "security",    label: "Security",    icon: "shield" },
  { key: "danger",      label: "Danger zone", icon: "alert", danger: true },
];

/**
 * Role-gate the nav + actions:
 *   role === "member" -> read-only (hide invite bar, role dropdowns)
 *   role === "admin"  -> can invite + change roles
 *   role === "owner"  -> everything, incl. Danger zone
 */
export default function SettingsLayout({ workspace, role = "owner", active, onSelect, onBack, children }) {
  const canAdmin = role === "owner" || role === "admin";
  return (
    <div className="dn-root dn-settings dn-paper">
      <nav className="dn-nav">
        <div className="dn-nav-back" onClick={onBack}>
          <Icon name="arrow-left" size={15} /> Back to chat
        </div>
        {NAV.map((item, i) =>
          item.group ? (
            <div className="dn-nav-group" key={`g${i}`}>{item.group}</div>
          ) : item.key === "danger" && role !== "owner" ? null : (
            <div
              key={item.key}
              className={`dn-nav-row ${active === item.key ? "is-active" : ""} ${item.danger ? "is-danger" : ""}`}
              onClick={() => onSelect(item.key)}
            >
              <Icon name={item.icon} /> {item.label}
            </div>
          )
        )}
      </nav>

      <div className="dn-main">
        <header className="dn-header">
          <div className="dn-square">{workspace.name?.[0] ?? "W"}</div>
          <div>
            <div className="dn-title">{workspace.name}</div>
            <div className="dn-meta">
              {workspace.slug} · {workspace.primary_domain} · {workspace.member_count} members
            </div>
          </div>
          <span className="dn-chip dn-chip--grape">{role}</span>
          {canAdmin && (
            <div className="dn-actions">
              <button className="dn-btn dn-btn--ghost"><Icon name="pencil" size={14} />Edit</button>
              <button className="dn-btn dn-btn--primary"><Icon name="user-plus" size={14} />Invite people</button>
            </div>
          )}
        </header>
        <div className="dn-body">{children}</div>
      </div>
    </div>
  );
}
