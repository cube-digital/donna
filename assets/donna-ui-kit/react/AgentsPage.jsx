import Icon from "./Icon";

export default function AgentsPage({ agents = [], onConfigure, onDisable, onCreate }) {
  return (
    <>
      {agents.map((a) => (
        <div className="dn-row" style={{ alignItems: "flex-start" }} key={a.id}>
          <span className="dn-avatar dn-avatar--lg dn-avatar--round" style={{ background: "var(--dn-grape)" }}>
            {a.name[0]}
          </span>
          <div style={{ flex: 1 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span className="dn-name" style={{ fontSize: 15 }}>{a.name}</span>
              <span className="dn-chip dn-chip--grape">agent</span>
              <span className={`dn-chip ${a.active ? "dn-chip--ok" : "dn-chip--neutral"}`}>
                {a.active ? "active" : "disabled"}
              </span>
            </div>
            <div className="dn-meta">{a.description}</div>
            <div className="dn-pill-row" style={{ marginTop: 11 }}>
              <span className="dn-mini"><Icon name="cpu" size={13} />{a.model}</span>
              <span className="dn-mini"><Icon name="tool" size={13} />{a.tool_count} tools</span>
              <span className="dn-mini"><Icon name="hash" size={13} />{a.channel_scope}</span>
              <span className="dn-mini"><Icon name="brain" size={13} />{a.cortex_scope}</span>
            </div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <button className="dn-btn dn-btn--ghost" onClick={() => onConfigure?.(a.id)}>Configure</button>
            <button className="dn-mini" style={{ justifyContent: "center" }} onClick={() => onDisable?.(a.id)}>
              {a.active ? "Disable" : "Enable"}
            </button>
          </div>
        </div>
      ))}

      <div className="dn-row dn-row--dashed">
        <span className="dn-avatar dn-avatar--empty"><Icon name="plus" size={18} /></span>
        <div>
          <div className="dn-name">Add an agent</div>
          <div className="dn-meta">Give a teammate a narrower scope — e.g. a sales agent limited to one client.</div>
        </div>
        <button className="dn-btn dn-btn--ghost dn-spacer" onClick={onCreate}>New agent</button>
      </div>
    </>
  );
}
