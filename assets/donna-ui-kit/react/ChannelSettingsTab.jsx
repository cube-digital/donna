import Icon from "./Icon";

/**
 * Archive is deliberately separate from Delete — archive is the one people
 * actually want (hide it, keep the history + cortex memory).
 */
export default function ChannelSettingsTab({ channel, isChannelAdmin, onSave, onArchive, onDelete }) {
  const isPrivate = channel.visibility === "private";
  return (
    <>
      <div className="dn-field">
        <div className="dn-label">Channel name</div>
        <input className="dn-input" defaultValue={channel.name} disabled={!isChannelAdmin} />
      </div>
      <div className="dn-field">
        <div className="dn-label">Topic</div>
        <input className="dn-input" defaultValue={channel.topic} disabled={!isChannelAdmin}
               placeholder="What's this channel about?" />
      </div>

      <div className="dn-section" style={{ marginTop: 18 }}>Visibility</div>
      <div className="dn-row">
        <Icon name="lock" size={16} />
        <div>
          <div className="dn-name">Private channel</div>
          <div className="dn-meta">
            Only invited people can find or join. Public is visible to the whole workspace.
          </div>
        </div>
        <div className={`dn-toggle dn-spacer ${isPrivate ? "is-on" : ""}`}
             role="switch" aria-checked={isPrivate}
             onClick={() => isChannelAdmin && onSave?.({ visibility: isPrivate ? "public" : "private" })} />
      </div>

      {isChannelAdmin && (
        <div style={{ display: "flex", gap: 9, margin: "16px 0 20px" }}>
          <button className="dn-btn dn-btn--primary" onClick={() => onSave?.({})}>Save changes</button>
        </div>
      )}

      {isChannelAdmin && (
        <>
          <div className="dn-section" style={{ color: "var(--dn-danger)" }}>Danger zone</div>
          <div className="dn-danger-zone" style={{ marginBottom: 8 }}>
            <Icon name="archive" size={18} style={{ color: "var(--dn-danger)" }} />
            <div>
              <div className="dn-name" style={{ color: "var(--dn-danger)" }}>Archive channel</div>
              <div className="dn-meta">Hides it from the sidebar. History and cortex memory are kept.</div>
            </div>
            <button className="dn-btn dn-btn--danger dn-spacer" onClick={onArchive}>Archive</button>
          </div>
          <div className="dn-danger-zone">
            <Icon name="alert" size={18} style={{ color: "var(--dn-danger)" }} />
            <div>
              <div className="dn-name" style={{ color: "var(--dn-danger)" }}>Delete channel</div>
              <div className="dn-meta">Removes all messages. Cortex keeps what it already ingested.</div>
            </div>
            <button className="dn-btn dn-btn--danger dn-spacer" onClick={onDelete}>Delete</button>
          </div>
        </>
      )}
    </>
  );
}
