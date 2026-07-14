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
  /** Bypass the loaded-once guard. Used after connect/disconnect. */
  reload(): Promise<void>;
  /** Clear on sign-out so the next user re-fetches (status is per-user). */
  reset(): void;
  /** Selector helper — undefined if slug unknown. */
  bySlug(slug: string): IntegrationProvider | undefined;
}

async function fetchAndSet(set: (p: Partial<IntegrationsState>) => void): Promise<void> {
  set({ loading: true });
  try {
    const providers = await listIntegrations();
    set({ providers, loaded: true });
  } catch {
    // Swallow — section renders empty.
  } finally {
    set({ loading: false });
  }
}

export const useIntegrations = create<IntegrationsState>((set, get) => ({
  providers: [],
  loading: false,
  loaded: false,
  load: async () => {
    if (get().loading || get().loaded) return;
    await fetchAndSet(set);
  },
  reload: async () => {
    if (get().loading) return;
    await fetchAndSet(set);
  },
  reset: () => set({ providers: [], loading: false, loaded: false }),
  bySlug: (slug: string) => get().providers.find((p) => p.slug === slug),
}));
