// Auth store — JWT-aware session state.
// Tokens themselves live in localStorage (lib/auth-storage); this store
// just tracks whether we believe we're signed in so the route gate
// re-renders.

import { create } from "zustand";
import { clearTokens, getAccess, setTokens } from "../lib/auth-storage";

interface AuthState {
  isAuthenticated: boolean;
  setSignedIn: (access: string, refresh: string) => void;
  signOut: () => void;
}

export const useAuth = create<AuthState>((set) => ({
  isAuthenticated: !!getAccess(),
  setSignedIn: (access, refresh) => {
    setTokens(access, refresh);
    set({ isAuthenticated: true });
  },
  signOut: () => {
    clearTokens();
    set({ isAuthenticated: false });
  },
}));
