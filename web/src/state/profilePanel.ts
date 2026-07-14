// Tiny toggle store for the global profile panel (opened from the WsRail
// avatar pill, rendered once by AppShell).

import { create } from "zustand";

interface ProfilePanelState {
  open: boolean;
  openPanel(): void;
  closePanel(): void;
  toggle(): void;
}

export const useProfilePanel = create<ProfilePanelState>((set, get) => ({
  open: false,
  openPanel: () => set({ open: true }),
  closePanel: () => set({ open: false }),
  toggle: () => set({ open: !get().open }),
}));
