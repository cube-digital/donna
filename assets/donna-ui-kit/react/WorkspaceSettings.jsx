// Example wiring — swap the mock data for your API calls.
import { useState } from "react";
import "../css/donna.css";
import SettingsLayout from "./SettingsLayout";
import GeneralPage from "./GeneralPage";
import MembersPage from "./MembersPage";
import InvitationsPage from "./InvitationsPage";
import ConnectionsPage from "./ConnectionsPage";
import AgentsPage from "./AgentsPage";

const workspace = { name: "Cube Digital", slug: "cube-digital", primary_domain: "cube.digital", member_count: 3 };

const members = [
  { id: "1", initials: "RI", name: "Rares Istoc", email: "istoc.rares@gmail.com", role: "owner", is_you: true, color: "var(--dn-grape)" },
  { id: "2", initials: "NK", name: "Nick", email: "nick@cube.digital", role: "admin", joined: "Jun 12", color: "var(--dn-blue)" },
  { id: "3", initials: "MA", name: "Marius", email: "marius@cube.digital", role: "member", joined: "Jun 14", color: "var(--dn-coral)" },
];

const invitations = [
  { id: "i1", email: "adi@acme.com", role: "guest", status: "pending", invited_by: "you", expires_in: "in 6 days", when: "expires in 6 days" },
  { id: "i2", email: "sofia@cube.digital", role: "member", status: "accepted", invited_by: "you", when: "accepted Jun 20" },
  { id: "i3", email: "old@vendor.com", role: "guest", status: "expired", invited_by: "Nick", when: "expired Jun 10" },
];

const connectors = [
  { slug: "fathom", name: "Fathom", icon: "broadcast", status: "live", description: "Meeting recordings", cortex_path: "meetings/", last_sync: "12m ago", tint: "oklch(0.55 0.18 262/.15)", color: "var(--dn-blue)" },
  { slug: "gmail", name: "Gmail", icon: "mail", status: "live", description: "Email", cortex_path: "emails/YYYY/MM", last_sync: "6d ago", tint: "oklch(0.66 0.20 33/.15)", color: "var(--dn-coral)" },
  { slug: "drive", name: "Google Drive", icon: "cloud", status: "available", description: "Docs & folders", cortex_path: "docs/" },
];

const agents = [
  { id: "a1", name: "Donna", active: true, description: "Your AI teammate. Reads cortex, drafts docs, answers in channels.",
    model: "claude-sonnet-4-6", tool_count: 6, channel_scope: "All channels", cortex_scope: "Cortex read + write" },
];

export default function WorkspaceSettings({ role = "owner", onBack }) {
  const [tab, setTab] = useState("members");
  const canAdmin = role === "owner" || role === "admin";

  return (
    <SettingsLayout workspace={workspace} role={role} active={tab} onSelect={setTab} onBack={onBack}>
      {tab === "general"     && <GeneralPage workspace={workspace} role={role} />}
      {tab === "members"     && <MembersPage members={members} invitations={invitations} canAdmin={canAdmin} />}
      {tab === "invitations" && <InvitationsPage invitations={invitations} />}
      {tab === "connections" && <ConnectionsPage connectors={connectors} />}
      {tab === "agents"      && <AgentsPage agents={agents} />}
    </SettingsLayout>
  );
}
