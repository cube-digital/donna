// Example wiring — swap mock data for your API.
import "../css/donna.css";
import NewMessageView from "./NewMessageView";

const people = [
  { id: "1", name: "Vlad Adumitracesei", handle: "vlad", initials: "VA", color: "var(--dn-blue)", presence: "active now", role: "member" },
  { id: "2", name: "Marko Pejic", handle: "marko", initials: "MP", color: "oklch(0.58 0.20 5)", presence: "away", role: "member" },
  { id: "3", name: "marius.milu", email: "marius@cube.digital", initials: "MM", color: "var(--dn-grape)", presence: "offline", role: "member" },
  { id: "4", name: "Donna", handle: "donna", initials: "D", color: "var(--dn-grape)" },  // AI teammate
];
const channels = [
  { id: "c1", name: "sales", private: true },
  { id: "c2", name: "social" },
  { id: "c3", name: "room-1" },
];

export default function NewMessageExample() {
  return (
    <NewMessageView
      people={people}
      channels={channels}
      /* one id -> POST /chat/dms/ ; many -> POST /chat/dms/group/ ; channelId -> open it */
      onStart={({ userIds, channelId }) => console.log("start", { userIds, channelId })}
      /* POST /workspaces/invitations/ then drop into a DM */
      onInvite={(email) => console.log("invite", email)}
    />
  );
}
