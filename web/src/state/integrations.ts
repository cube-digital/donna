// Integrations store — populates the Context section of the right rail.
//
// One-shot load on AppShell mount; re-run after an OAuth popup completes
// (driven by the IntegrationModal's `window.message` listener).

import { create } from "zustand";

import { listIntegrations } from "../api/integrations";
import type { IntegrationProvider } from "../types";

interface IntegrationsState {
  providers: IntegrationProvider[];
  loading: boolean;
  loaded: boolean;
  load(): Promise<void>;
}

export const useIntegrations = create<IntegrationsState>((set, get) => ({
  providers: [],
  loading: false,
  loaded: false,
  load: async () => {
    if (get().loading) return;
    set({ loading: true });
    try {
      const providers = await listIntegrations();
      set({ providers, loaded: true });
    } catch {
      // Swallow — context section renders empty.
    } finally {
      set({ loading: false });
    }
  },
}));
