// Example wiring — swap the mock data for your API calls.
import "../css/donna.css";
import ChannelPanel from "./ChannelPanel";

const channel = {
  id: "c1", name: "general", topic: "Everything Cube Digital",
  visibility: "public", created_by: "Rares Istoc", created_at: "Jun 12, 2026",
};

const members = [
  { id: "1", initials: "RI", name: "Rares Istoc", email: "istoc.rares@gmail.com", role: "admin", is_you: true, color: "var(--dn-grape)" },
  { id: "2", initials: "MA", name: "Marius", email: "marius@cube.digital", role: "member", color: "var(--dn-coral)" },
  { id: "3", initials: "NK", name: "Nick", email: "nick@cube.digital", role: "member", color: "var(--dn-blue)" },
];

// from GET /api/v1/chat/channels/<id>/mention-candidates/
const candidates = [
  { id: "4", initials: "SO", name: "Sofia", email: "sofia@cube.digital", color: "var(--dn-blue)" },
];

const agents = [
  { id: "a1", name: "Donna", handle: "donna", resident: false, active: true },
  { id: "a2", name: "ContractBot", handle: "contracts", resident: true, active: true,
    scope: "clients/cube-digital", color: "var(--dn-blue)" },
];

export default function ChannelPanelExample() {
  return (
    <ChannelPanel
      channel={channel}
      members={members}
      candidates={candidates}
      agents={agents}
      artifacts={{ drafts: 1, finalized: 0 }}
      cortexScope="clients/cube-digital"
      isChannelAdmin
      /* POST   /chat/channels/<id>/members/                */
      onAddMember={(userId) => console.log("add", userId)}
      /* DELETE /chat/channels/<id>/members/<user_id>/      */
      onRemoveMember={(userId) => console.log("remove", userId)}
      onRoleChange={(userId, role) => console.log("role", userId, role)}
      /* POST   /workspaces/invitations/  (+ auto-join channel) */
      onInviteByEmail={(fd) => console.log("invite", fd.get("email"))}
      /* POST   /chat/channels/<id>/agents/install/         */
      onInstallAgent={() => console.log("install agent")}
      /* DELETE /chat/channels/<id>/agents/<handle>/        */
      onUninstallAgent={(handle) => console.log("uninstall", handle)}
      onArchive={() => console.log("archive")}
      onDelete={() => console.log("delete")}
    />
  );
}
