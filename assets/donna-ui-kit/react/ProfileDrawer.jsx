import { useState } from "react";
import Icon from "./Icon";

const PRESETS = ["🎯 Focusing", "📅 In a meeting", "🌴 OOO"];

/**
 * FINAL profile style (chosen):
 *   - first two cards: OUTLINED (dn-row--outline) so the dotted paper shows through
 *   - text fields:     WARM fill + bold ink border (dn-input--profile)
 *   - presence toggle: GREEN when on (dn-toggle--presence)
 */
export default function ProfileDrawer({ user, onSave, onSignOut, onClose }) {
  const [active, setActive] = useState(user.active ?? true);
  const [name, setName] = useState(user.name ?? "");
  const [status, setStatus] = useState(user.status ?? "");

  return (
    <aside className="dn-root dn-drawer dn-paper">
      <div className="dn-drawer-head">
        Profile
        <Icon name="x" className="dn-spacer" style={{ color: "var(--dn-t4)", cursor: "pointer" }} onClick={onClose} />
      </div>

      <div className="dn-drawer-body">
        <div className="dn-row dn-row--outline">
          <span className="dn-avatar dn-avatar--lg" style={{ background: user.color ?? "var(--dn-coral)" }}>
            {user.initials}
            {active && <span className="dn-presence" />}
          </span>
          <div>
            <div className="dn-name">{user.name}</div>
            <div className="dn-meta">{user.email}</div>
            <div className="dn-link" style={{ marginTop: 4 }}>Add picture</div>
          </div>
        </div>

        <div className="dn-row dn-row--outline">
          <span style={{ width: 9, height: 9, borderRadius: "50%", flex: "none",
                         background: active ? "var(--dn-ok)" : "var(--dn-t4)" }} />
          <div>
            <div className="dn-name">{active ? "Active" : "Away"}</div>
            <div className="dn-meta">{active ? "Shown as active" : "Shown as away"}</div>
          </div>
          <div
            className={`dn-toggle dn-toggle--presence dn-spacer ${active ? "is-on" : ""}`}
            role="switch" aria-checked={active}
            onClick={() => setActive((v) => !v)}
          />
        </div>

        <div className="dn-label" style={{ marginTop: 16 }}>Display name</div>
        <input className="dn-input dn-input--profile" value={name} onChange={(e) => setName(e.target.value)} />

        <div className="dn-label" style={{ marginTop: 14 }}>Status</div>
        <input className="dn-input dn-input--profile" placeholder="What are you up to?"
               value={status} onChange={(e) => setStatus(e.target.value)} />

        <div className="dn-pill-row" style={{ marginTop: 11 }}>
          {PRESETS.map((p) => (
            <span key={p} className={`dn-pill ${status === p ? "is-on" : ""}`} onClick={() => setStatus(p)}>{p}</span>
          ))}
        </div>

        <button className="dn-btn dn-btn--primary dn-btn--profile" style={{ marginTop: 16 }}
                onClick={() => onSave?.({ name, status, active })}>
          Save profile
        </button>
      </div>

      <div className="dn-drawer-foot">
        <button className="dn-btn dn-btn--ghost dn-btn--profile dn-btn--block" onClick={onSignOut}>Sign out</button>
      </div>
    </aside>
  );
}
