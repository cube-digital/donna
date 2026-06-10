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
import type { Paginated, Workspace, WorkspaceMembership } from "../types";

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

/** Active workspace's memberships (people + roles), header-tenanted.
 *  Used by the channel member picker + group DM peer selector. */
export async function listWorkspaceMembers(): Promise<WorkspaceMembership[]> {
  const data = await apiFetch<WorkspaceMembership[] | Paginated<WorkspaceMembership>>(
    "/api/v1/members/",
  );
  return Array.isArray(data) ? data : data.results;
}
