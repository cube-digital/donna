// ChannelPanel — tabbed channel details: About · Members · Agents · Settings.
// Opens from the channel name, the member chip, or the ⋯ menu.
//
//   <ChannelPanel channel={ch} members={m} agents={a} isChannelAdmin ... />
//
// Presentational only — every action is a prop.
import { useState } from "react";
import Icon from "./Icon";
import ChannelAboutTab from "./ChannelAboutTab";
import ChannelMembersTab from "./ChannelMembersTab";
import ChannelAgentsTab from "./ChannelAgentsTab";
import ChannelSettingsTab from "./ChannelSettingsTab";

export default function ChannelPanel({
  channel,                 // { id, name, topic, visibility, created_by, created_at }
  members = [],            // [{ id, name, email, initials, color, role }]
  candidates = [],         // workspace members NOT in this channel
  agents = [],             // [{ id, name, handle, resident, scope, active }]
  artifacts = { drafts: 0, finalized: 0 },
  cortexScope = null,      // e.g. "clients/cube-digital" | null
  isChannelAdmin = false,
  onAddMember, onInviteByEmail, onRoleChange, onRemoveMember,
  onInstallAgent, onUninstallAgent, onConfigureAgent,
  onLinkScope, onSave, onArchive, onDelete, onOpenFiles, onNotifications,
}) {
  const [tab, setTab] = useState("members");
  const isPrivate = channel.visibility === "private";

  return (
    <div className="dn-root dn-panel dn-paper">
      <header className="dn-panel-head">
        <div className="dn-panel-title">
          <span className="dn-hash">#</span>{channel.name}
          <span className="dn-chip dn-chip--neutral">
            {isPrivate && <Icon name="lock" size={11} />}
            {channel.visibility}
          </span>
          <div className="dn-actions">
            <button className="dn-btn dn-btn--ghost" onClick={onNotifications}>
              <Icon name="bell" size={14} />Notifications
            </button>
            {isChannelAdmin && (
              <button className="dn-btn dn-btn--primary" onClick={() => setTab("members")}>
                <Icon name="user-plus" size={14} />Add people
              </button>
            )}
          </div>
        </div>

        <div className="dn-topic">
          {channel.topic || "No topic yet"} · created by {channel.created_by} · {channel.created_at}
        </div>

        <nav className="dn-tabs">
          {[
            ["about", "About"],
            ["members", `Members · ${members.length}`],
            ["agents", `Agents · ${agents.length}`],
            ["settings", "Settings"],
          ].map(([key, label]) => (
            <span key={key}
                  className={`dn-tab ${tab === key ? "is-active" : ""}`}
                  onClick={() => setTab(key)}>
              {label}
            </span>
          ))}
        </nav>
      </header>

      <div className="dn-body">
        {tab === "about" && (
          <ChannelAboutTab channel={channel} artifacts={artifacts} onOpenFiles={onOpenFiles} />
        )}
        {tab === "members" && (
          <ChannelMembersTab
            members={members} candidates={candidates} isChannelAdmin={isChannelAdmin}
            onAddMember={onAddMember} onInviteByEmail={onInviteByEmail}
            onRoleChange={onRoleChange} onRemoveMember={onRemoveMember}
          />
        )}
        {tab === "agents" && (
          <ChannelAgentsTab
            agents={agents} cortexScope={cortexScope} isChannelAdmin={isChannelAdmin}
            onInstallAgent={onInstallAgent} onUninstallAgent={onUninstallAgent}
            onConfigureAgent={onConfigureAgent} onLinkScope={onLinkScope}
          />
        )}
        {tab === "settings" && (
          <ChannelSettingsTab
            channel={channel} isChannelAdmin={isChannelAdmin}
            onSave={onSave} onArchive={onArchive} onDelete={onDelete}
          />
        )}
      </div>
    </div>
  );
}
