import Icon from "./Icon";

/**
 * THE differentiator. Your backend supports `is_channel_resident` +
 * `resident_handle`, so an agent can live inside a channel and be called
 * by its own @handle (e.g. @contracts in #legal). No other chat app does this.
 *
 * `cortexScope` links the channel to a cortex folder — agents here then answer
 * from that client/project's meetings, emails and docs first.
 */
export default function ChannelAgentsTab({
  agents = [], cortexScope, isChannelAdmin,
  onInstallAgent, onUninstallAgent, onConfigureAgent, onLinkScope,
}) {
  return (
    <>
      <div className="dn-section">Agents in this channel · {agents.length}</div>

      {agents.map((a) => (
        <div className="dn-row" key={a.id}>
          <span className="dn-avatar dn-avatar--round" style={{ background: a.color ?? "var(--dn-grape)" }}>
            {a.name[0]}
          </span>
          <div>
            <div className="dn-name">
              {a.name} <span className="dn-handle">@{a.handle}</span>
            </div>
            <div className="dn-meta">
              {a.resident
                ? <>Channel-resident{a.scope ? <> · scoped to <span className="dn-mono">{a.scope}</span></> : null}</>
                : "Workspace teammate · reads cortex, drafts docs, answers in channels"}
            </div>
          </div>
          <div className="dn-actions">
            <span className={`dn-chip ${a.active ? "dn-chip--ok" : "dn-chip--neutral"}`}>
              {a.active ? "active" : "disabled"}
            </span>
            <button className="dn-mini" onClick={() => onConfigureAgent?.(a.id)}>Configure</button>
            {a.resident && isChannelAdmin && (
              <button className="dn-mini dn-mini--danger" onClick={() => onUninstallAgent?.(a.handle)}>
                Uninstall
              </button>
            )}
          </div>
        </div>
      ))}

      {isChannelAdmin && (
        <div className="dn-row dn-row--dashed">
          <span className="dn-avatar dn-avatar--empty"><Icon name="sparkles" size={18} /></span>
          <div>
            <div className="dn-name">Install an agent</div>
            <div className="dn-meta">
              Pick an agent and give it a <span className="dn-handle">@handle</span> so people can call it here
            </div>
          </div>
          <button className="dn-btn dn-btn--ghost dn-spacer" onClick={onInstallAgent}>Install</button>
        </div>
      )}

      <div className="dn-section" style={{ marginTop: 18 }}>Channel context</div>
      <div className="dn-row">
        <span className="dn-avatar dn-avatar--empty"><Icon name="brain" size={18} /></span>
        <div>
          <div className="dn-name">
            {cortexScope
              ? <>Linked to <span className="dn-mono">{cortexScope}</span></>
              : "Not linked to a client or project"}
          </div>
          <div className="dn-meta">
            {cortexScope
              ? "Agents here answer from this client's meetings, emails and docs first"
              : "Link this channel to a cortex scope so agents prioritise the right memory"}
          </div>
        </div>
        <div className={`dn-toggle dn-spacer ${cortexScope ? "is-on" : ""}`}
             role="switch" aria-checked={!!cortexScope}
             onClick={() => onLinkScope?.(!cortexScope)} />
      </div>
    </>
  );
}
