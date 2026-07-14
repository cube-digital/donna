// Workspace store.
// activeId is the value sent as `X-Workspace-Id` on every request —
// see api/client.ts. Persists in localStorage so the active workspace
// survives reloads.

import { create } from "zustand";
import {
  getActiveWorkspace,
  setActiveWorkspace as persistActive,
} from "../lib/auth-storage";
import type { Workspace } from "../types";

interface WorkspaceState {
  workspaces: Workspace[];
  activeId: string | null;
  loading: boolean;
  setWorkspaces: (ws: Workspace[]) => void;
  setActive: (id: string | null) => void;
  setLoading: (v: boolean) => void;
  /** Clear on sign-out so a different user doesn't inherit the workspace. */
  reset: () => void;
}

export const useWorkspace = create<WorkspaceState>((set) => ({
  workspaces: [],
  activeId: getActiveWorkspace(),
  loading: false,
  setWorkspaces: (workspaces) => set({ workspaces }),
  setActive: (id) => {
    persistActive(id);
    set({ activeId: id });
  },
  setLoading: (loading) => set({ loading }),
  reset: () => {
    persistActive(null);
    set({ workspaces: [], activeId: null, loading: false });
  },
}));
