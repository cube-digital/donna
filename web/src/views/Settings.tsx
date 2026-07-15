// Workspace Settings container — owns data + handlers, renders the ported
// donna-ui-kit settings pages. Mounted at /settings and /settings/:tab inside
// the authenticated AppShell.

import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import "../styles/donna-kit.css";
import {
  deleteWorkspace,
  getWorkspace,
  listInvitations,
  listMembers,
  updateMemberRole,
  removeMember,
  createInvitation,
  resendInvitation,
  revokeInvitation,
  updateWorkspace,
  type WorkspaceMemberRow,
} from "../api/workspaces";
import { connectIntegration, disconnectIntegration } from "../api/integrations";
import { colorFrom, initialsFrom } from "../lib/kitAvatar";
import { useIntegrations } from "../state/integrations";
import { useMe } from "../state/me";
import { useWorkspace } from "../state/workspace";
import type {
  IntegrationProvider,
  Workspace,
  WorkspaceInvitation,
  WorkspaceRole,
} from "../types";
import SettingsLayout from "./settings/SettingsLayout";
import GeneralPage from "./settings/GeneralPage";
import MembersPage from "./settings/MembersPage";
import InvitationsPage from "./settings/InvitationsPage";
import ConnectionsPage from "./settings/ConnectionsPage";
import AgentsPage from "./settings/AgentsPage";
import ComingSoon from "./ComingSoon";
import type {
  KitConnector,
  KitInvitation,
  KitMember,
  SettingsTab,
} from "./settings/types";

const KNOWN_TABS: SettingsTab[] = [
  "general",
  "members",
  "invitations",
  "connections",
  "agents",
  "security",
  "danger",
];

const CONNECTOR_ICON: Record<string, string> = {
  fathom: "broadcast",
  gmail: "mail",
  mail: "mail",
  drive: "cloud",
  "google-drive": "cloud",
};

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function relativeFuture(iso: string | null | undefined): string {
  if (!iso) return "soon";
  const ms = new Date(iso).getTime() - Date.now();
  if (Number.isNaN(ms)) return "soon";
  const days = Math.round(ms / 86_400_000);
  if (days <= 0) return "soon";
  if (days === 1) return "in 1 day";
  return `in ${days} days`;
}

function toKitMember(row: WorkspaceMemberRow, meId: string | null): KitMember {
  const name = row.user.full_name || row.user.email;
  return {
    id: row.user.id,
    name,
    email: row.user.email,
    initials: initialsFrom(name),
    color: colorFrom(row.user.id),
    role: row.role,
    is_you: !!meId && row.user.id === meId,
    joined: fmtDate(row.created_at),
  };
}

function toKitInvitation(inv: WorkspaceInvitation): KitInvitation {
  const by = inv.invited_by?.full_name || inv.invited_by?.email || "someone";
  let when = "";
  if (inv.status === "accepted")
    when = `accepted ${fmtDate(inv.accepted_at ?? inv.updated_at)}`;
  else if (inv.status === "expired") when = `expired ${fmtDate(inv.expires_at)}`;
  else if (inv.status === "revoked") when = `revoked ${fmtDate(inv.updated_at)}`;
  else when = `expires ${fmtDate(inv.expires_at)}`;
  return {
    id: inv.id,
    email: inv.email,
    role: inv.role,
    status: inv.status,
    invited_by: by,
    expires_in: relativeFuture(inv.expires_at),
    when,
  };
}

function toKitConnector(p: IntegrationProvider): KitConnector {
  return {
    slug: p.slug,
    name: p.display_name,
    icon: CONNECTOR_ICON[p.slug] ?? "plug",
    status: p.status === "live" ? "live" : "available",
    description: p.description || "Integration",
  };
}

export default function Settings() {
  const navigate = useNavigate();
  const { tab: tabParam } = useParams<{ tab?: string }>();
  const activeId = useWorkspace((s) => s.activeId);
  const me = useMe((s) => s.me);
  const loadMe = useMe((s) => s.load);
  const providers = useIntegrations((s) => s.providers);
  const loadIntegrations = useIntegrations((s) => s.load);
  const reloadIntegrations = useIntegrations((s) => s.reload);

  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [members, setMembers] = useState<WorkspaceMemberRow[]>([]);
  const [invitations, setInvitations] = useState<WorkspaceInvitation[]>([]);

  const tab: SettingsTab =
    tabParam && (KNOWN_TABS as string[]).includes(tabParam)
      ? (tabParam as SettingsTab)
      : "members";

  const refetchMembers = async () => setMembers(await listMembers());
  const refetchInvitations = async () =>
    setInvitations(await listInvitations());

  useEffect(() => {
    void loadMe();
    void loadIntegrations();
  }, [loadMe, loadIntegrations]);

  useEffect(() => {
    if (!activeId) return;
    let cancelled = false;
    void (async () => {
      try {
        const [ws, mem, inv] = await Promise.all([
          getWorkspace(activeId),
          listMembers(),
          listInvitations(),
        ]);
        if (!cancelled) {
          setWorkspace(ws);
          setMembers(mem);
          setInvitations(inv);
        }
      } catch {
        /* leave empty; header falls back to defaults */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activeId]);

  const role: WorkspaceRole = workspace?.my_role ?? "member";
  const canAdmin = role === "owner" || role === "admin";

  const kitWorkspace = useMemo(
    () => ({
      name: workspace?.name ?? "Workspace",
      slug: workspace?.slug ?? "",
      primary_domain: workspace?.primary_domain,
      member_count: workspace?.member_count ?? members.length,
    }),
    [workspace, members.length],
  );

  const kitMembers = useMemo(
    () => members.map((m) => toKitMember(m, me?.id ?? null)),
    [members, me?.id],
  );
  const kitInvitations = useMemo(
    () => invitations.map(toKitInvitation),
    [invitations],
  );
  const kitConnectors = useMemo(
    () => providers.map(toKitConnector),
    [providers],
  );

  // ── handlers ──────────────────────────────────────────────────────────
  const onSelect = (t: SettingsTab) => navigate(`/settings/${t}`);
  const onBack = () => navigate("/channels");

  const onInvite = async (fd: FormData) => {
    const email = String(fd.get("email") ?? "").trim();
    const inviteRole = (String(fd.get("role") ?? "member") ||
      "member") as WorkspaceRole;
    if (!email) return;
    await createInvitation(email, inviteRole);
    await refetchInvitations();
  };
  const onRoleChange = async (userId: string, r: WorkspaceRole) => {
    await updateMemberRole(userId, r);
    await refetchMembers();
  };
  const onRemove = async (userId: string) => {
    await removeMember(userId);
    await refetchMembers();
  };
  const onResend = async (id: string) => {
    await resendInvitation(id);
    await refetchInvitations();
  };
  const onRevoke = async (id: string) => {
    await revokeInvitation(id);
    await refetchInvitations();
  };
  const onCopyLink = (id: string) => {
    const inv = invitations.find((i) => i.id === id);
    if (inv?.accept_url) void navigator.clipboard.writeText(inv.accept_url);
  };

  const onSaveGeneral = async (patch: {
    name: string;
    slug: string;
    primary_domain: string;
  }) => {
    if (!activeId) return;
    const updated = await updateWorkspace(activeId, {
      name: patch.name,
      slug: patch.slug,
      primary_domain: patch.primary_domain,
    });
    setWorkspace(updated);
  };
  const onDeleteWorkspace = async () => {
    if (!activeId) return;
    await deleteWorkspace(activeId);
    navigate("/workspaces");
  };

  const onConnect = async (slug: string) => {
    const { authorize_url } = await connectIntegration(slug);
    window.location.assign(authorize_url);
  };
  const onDisconnect = async (slug: string) => {
    await disconnectIntegration(slug);
    await reloadIntegrations();
  };
  const onConfigure = (slug: string) => navigate(`/integrations/${slug}`);

  return (
    <div className="h-full overflow-y-auto">
      <SettingsLayout
        workspace={kitWorkspace}
        role={role}
        active={tab}
        onSelect={onSelect}
        onBack={onBack}
      >
        {tab === "general" && (
          <GeneralPage
            workspace={kitWorkspace}
            role={role}
            onSave={onSaveGeneral}
            onDelete={onDeleteWorkspace}
          />
        )}
        {tab === "members" && (
          <MembersPage
            members={kitMembers}
            invitations={kitInvitations}
            canAdmin={canAdmin}
            onInvite={onInvite}
            onRoleChange={onRoleChange}
            onRemove={onRemove}
            onResend={onResend}
            onRevoke={onRevoke}
          />
        )}
        {tab === "invitations" && (
          <InvitationsPage
            invitations={kitInvitations}
            onInvite={onInvite}
            onResend={onResend}
            onRevoke={onRevoke}
            onCopyLink={onCopyLink}
          />
        )}
        {tab === "connections" && (
          <ConnectionsPage
            connectors={kitConnectors}
            onConnect={onConnect}
            onConfigure={onConfigure}
            onDisconnect={onDisconnect}
          />
        )}
        {tab === "agents" && <AgentsPage />}
        {tab === "security" && <ComingSoon title="Security" />}
        {tab === "danger" && (
          <GeneralPage
            workspace={kitWorkspace}
            role={role}
            onSave={onSaveGeneral}
            onDelete={onDeleteWorkspace}
          />
        )}
      </SettingsLayout>
    </div>
  );
}
