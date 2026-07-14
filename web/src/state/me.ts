// Current-user profile store. Populates the WsRail avatar pill + the
// ProfilePanel. Loaded once on AppShell mount; refreshed after profile edits.

import { create } from "zustand";

import { getMe, type Me } from "../api/users";

interface MeState {
  me: Me | null;
  loading: boolean;
  loaded: boolean;
  load(): Promise<void>;
  /** Bypass the load-once guard (after a profile update). */
  refresh(): Promise<void>;
  /** Replace the cached profile (e.g. from a PATCH/upload response). */
  setMe(me: Me): void;
  /** Clear on sign-out so the next account doesn't inherit this profile. */
  reset(): void;
}

async function fetchInto(set: (p: Partial<MeState>) => void): Promise<void> {
  set({ loading: true });
  try {
    const me = await getMe();
    set({ me, loaded: true });
  } catch {
    // Swallow — the pill falls back to whatever it can render.
  } finally {
    set({ loading: false });
  }
}

export const useMe = create<MeState>((set, get) => ({
  me: null,
  loading: false,
  loaded: false,
  load: async () => {
    if (get().loading || get().loaded) return;
    await fetchInto(set);
  },
  refresh: async () => {
    if (get().loading) return;
    await fetchInto(set);
  },
  setMe: (me) => set({ me, loaded: true }),
  reset: () => set({ me: null, loading: false, loaded: false }),
}));
