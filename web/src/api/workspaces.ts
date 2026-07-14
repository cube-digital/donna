// Workspace endpoints — backed by server/donna/workspaces/api/v1/views.py.
//
// Pagination shape note
// ─────────────────────
// Donna's StandardJSONRenderer puts pagination metadata in `meta` and the
// rows directly in `data`. After apiFetch strips the envelope, the value
// we receive IS the array. (No DRF-default `{results, next, ...}`.) For
// safety against a future refactor we also tolerate the DRF shape.
//
// `createWorkspace` POSTs `{name, slug}`; the backend wires the calling
// user as the owner membership inside the same transaction.

import { apiFetch } from "./client";
import type {
  Paginated,
  Workspace,
  WorkspaceInvitation,
  WorkspaceInvitationPreview,
  WorkspaceRole,
} from "../types";

export async function listWorkspaces(): Promise<Workspace[]> {
  const data = await apiFetch<Workspace[] | Paginated<Workspace>>(
    "/api/v1/workspaces/",
    { skipWorkspace: true },
  );
  return Array.isArray(data) ? data : data.results;
}

export async function createWorkspace(input: {
  name: string;
  slug: string;
}): Promise<Workspace> {
  return apiFetch<Workspace>("/api/v1/workspaces/", {
    method: "POST",
    body: input,
    skipWorkspace: true,
  });
}

// ── Members ─────────────────────────────────────────────────────────────

export interface WorkspaceMemberRow {
  id: string;
  user: { id: string; email: string; full_name: string };
  role: WorkspaceRole;
  created_at: string;
}

export async function listMembers(): Promise<WorkspaceMemberRow[]> {
  const data = await apiFetch<
    WorkspaceMemberRow[] | Paginated<WorkspaceMemberRow>
  >("/api/v1/members/");
  return Array.isArray(data) ? data : data.results;
}

// ── Invitations ─────────────────────────────────────────────────────────

export async function listInvitations(): Promise<WorkspaceInvitation[]> {
  const data = await apiFetch<
    WorkspaceInvitation[] | Paginated<WorkspaceInvitation>
  >("/api/v1/workspaces/invitations/");
  return Array.isArray(data) ? data : data.results;
}

export async function createInvitation(
  email: string,
  role: WorkspaceRole = "member",
): Promise<WorkspaceInvitation> {
  return apiFetch<WorkspaceInvitation>(
    "/api/v1/workspaces/invitations/",
    { method: "POST", body: { email, role } },
  );
}

export async function revokeInvitation(id: string): Promise<void> {
  await apiFetch(`/api/v1/workspaces/invitations/${id}/`, { method: "DELETE" });
}

/** Public preview — no auth, no workspace header. */
export async function inspectInvitation(
  token: string,
): Promise<WorkspaceInvitationPreview> {
  return apiFetch<WorkspaceInvitationPreview>(
    `/api/v1/invitations/${token}/`,
    { skipWorkspace: true, skipAuth: true },
  );
}

export interface MyInvitation {
  workspace_name: string;
  email: string;
  invited_by: string;
  expires_at: string;
  token: string;
}

/** Pending invitations addressed to the signed-in user (across workspaces). */
export async function listMyInvitations(): Promise<MyInvitation[]> {
  const data = await apiFetch<MyInvitation[] | Paginated<MyInvitation>>(
    "/api/v1/invitations/mine/",
    { skipWorkspace: true },
  );
  return Array.isArray(data) ? data : (data.results ?? []);
}

/** Accept invitation — requires logged-in user whose email matches. */
export async function acceptInvitation(
  token: string,
): Promise<{ workspace_id: string; role: WorkspaceRole }> {
  return apiFetch(`/api/v1/invitations/${token}/accept/`, {
    method: "POST",
    body: {},
    skipWorkspace: true,
  });
}
