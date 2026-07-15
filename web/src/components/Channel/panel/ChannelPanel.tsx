// Ported from assets/donna-ui-kit/react/ChannelPanel.jsx — tabbed channel
// details (About · Members · Agents · Settings). Presentational only; every
// action is a prop. Agents tab is deferred to ComingSoon.
import { useState } from "react";

import Icon from "../../kit/Icon";
import ChannelAboutTab from "./ChannelAboutTab";
import ChannelMembersTab from "./ChannelMembersTab";
import ChannelAgentsTab from "./ChannelAgentsTab";
import ChannelSettingsTab, {
  type ChannelSettingsPatch,
} from "./ChannelSettingsTab";
import type {
  ChannelRole,
  KitArtifacts,
  KitCandidate,
  KitChannel,
  KitChannelAgent,
  KitChannelMember,
} from "./types";

type Tab = "about" | "members" | "agents" | "settings";

export interface ChannelPanelProps {
  channel: KitChannel;
  members?: KitChannelMember[];
  candidates?: KitCandidate[];
  agents?: KitChannelAgent[];
  artifacts?: KitArtifacts;
  isChannelAdmin?: boolean;
  onAddMember?: (userId: string) => void;
  onInviteByEmail?: (fd: FormData) => void;
  onRoleChange?: (userId: string, role: ChannelRole) => void;
  onRemoveMember?: (userId: string) => void;
  onSave?: (patch: ChannelSettingsPatch) => void;
  onDelete?: () => void;
  onOpenFiles?: () => void;
  onNotifications?: () => void;
}

export default function ChannelPanel({
  channel,
  members = [],
  candidates = [],
  agents = [],
  artifacts = { drafts: 0, finalized: 0 },
  isChannelAdmin = false,
  onAddMember,
  onInviteByEmail,
  onRoleChange,
  onRemoveMember,
  onSave,
  onDelete,
  onOpenFiles,
  onNotifications,
}: ChannelPanelProps) {
  const [tab, setTab] = useState<Tab>("members");
  const isPrivate = channel.visibility === "private";

  const TABS: [Tab, string][] = [
    ["about", "About"],
    ["members", `Members · ${members.length}`],
    ["agents", `Agents · ${agents.length}`],
    ["settings", "Settings"],
  ];

  return (
    <div className="dn-root dn-panel dn-paper">
      <header className="dn-panel-head">
        <div className="dn-panel-title">
          <span className="dn-hash">#</span>
          {channel.name}
          <span className="dn-chip dn-chip--neutral">
            {isPrivate && <Icon name="lock" size={11} />}
            {channel.visibility}
          </span>
          <div className="dn-actions">
            <button className="dn-btn dn-btn--ghost" onClick={onNotifications}>
              <Icon name="bell" size={14} />
              Notifications
            </button>
            {isChannelAdmin && (
              <button
                className="dn-btn dn-btn--primary"
                onClick={() => setTab("members")}
              >
                <Icon name="user-plus" size={14} />
                Add people
              </button>
            )}
          </div>
        </div>

        <div className="dn-topic">
          {channel.topic || "No topic yet"} · created by {channel.created_by} ·{" "}
          {channel.created_at}
        </div>

        <nav className="dn-tabs">
          {TABS.map(([key, label]) => (
            <span
              key={key}
              className={`dn-tab ${tab === key ? "is-active" : ""}`}
              onClick={() => setTab(key)}
            >
              {label}
            </span>
          ))}
        </nav>
      </header>

      <div className="dn-body">
        {tab === "about" && (
          <ChannelAboutTab
            channel={channel}
            artifacts={artifacts}
            onOpenFiles={onOpenFiles}
          />
        )}
        {tab === "members" && (
          <ChannelMembersTab
            members={members}
            candidates={candidates}
            isChannelAdmin={isChannelAdmin}
            onAddMember={onAddMember}
            onInviteByEmail={onInviteByEmail}
            onRoleChange={onRoleChange}
            onRemoveMember={onRemoveMember}
          />
        )}
        {tab === "agents" && <ChannelAgentsTab />}
        {tab === "settings" && (
          <ChannelSettingsTab
            channel={channel}
            isChannelAdmin={isChannelAdmin}
            onSave={onSave}
            onDelete={onDelete}
          />
        )}
      </div>
    </div>
  );
}
