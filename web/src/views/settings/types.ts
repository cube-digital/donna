// Kit-facing view models for the ported Workspace Settings surfaces.
// The container (views/Settings.tsx) maps real API rows onto these shapes.

import type { WorkspaceRole } from "../../types";

export interface KitWorkspace {
  name: string;
  slug: string;
  primary_domain?: string;
  member_count?: number;
}

export interface KitMember {
  id: string;
  name: string;
  email: string;
  initials: string;
  color: string;
  role: WorkspaceRole;
  is_you?: boolean;
  joined?: string;
}

export type KitInvitationStatus = "pending" | "accepted" | "revoked" | "expired";

export interface KitInvitation {
  id: string;
  email: string;
  role: WorkspaceRole;
  status: KitInvitationStatus;
  invited_by: string;
  /** Human phrase used by MembersPage ("in 6 days"). */
  expires_in?: string;
  /** Human phrase used by InvitationsPage ("expires in 6 days"). */
  when?: string;
}

export interface KitConnector {
  slug: string;
  name: string;
  icon: string;
  status: "live" | "available";
  description: string;
  cortex_path?: string;
  last_sync?: string;
  tint?: string;
  color?: string;
}

export type SettingsTab =
  | "general"
  | "members"
  | "invitations"
  | "connections"
  | "agents"
  | "security"
  | "danger";
