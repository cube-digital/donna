// Auth store — JWT-aware session state.
// Tokens themselves live in localStorage (lib/auth-storage); this store
// tracks whether we believe we're signed in so the route gate
// re-renders, plus a lightweight `user` ({id, email}) decoded from the
// JWT payload for client-side checks (mention "me", DM filter, invite
// email match).

import { create } from "zustand";
import { clearTokens, getAccess, setTokens } from "../lib/auth-storage";
import { useIntegrations } from "./integrations";
import { useMe } from "./me";
import { useWorkspace } from "./workspace";

interface DecodedUser {
  id: string;
  email: string;
}

interface AuthState {
  isAuthenticated: boolean;
  user: DecodedUser | null;
  setSignedIn: (access: string, refresh: string) => void;
  signOut: () => void;
}

function decodeUser(token: string | null): DecodedUser | null {
  if (!token) return null;
  try {
    const payload = token.split(".")[1];
    const json = JSON.parse(
      decodeURIComponent(
        atob(payload.replace(/-/g, "+").replace(/_/g, "/"))
          .split("")
          .map((c) => "%" + c.charCodeAt(0).toString(16).padStart(2, "0"))
          .join(""),
      ),
    );
    const id = payload && (json.user_id || json.sub || json.id);
    const email = (json.email as string | undefined) ?? "";
    if (!id) return null;
    return { id: String(id), email };
  } catch {
    return null;
  }
}

export const useAuth = create<AuthState>((set) => ({
  isAuthenticated: !!getAccess(),
  user: decodeUser(getAccess()),
  setSignedIn: (access, refresh) => {
    setTokens(access, refresh);
    set({ isAuthenticated: true, user: decodeUser(access) });
  },
  signOut: () => {
    clearTokens();
    set({ isAuthenticated: false, user: null });
    // Per-user state must not leak to the next account signing in on the same
    // SPA session (no full reload happens). Integration status + the active
    // workspace are both per-user.
    useWorkspace.getState().reset();
    useIntegrations.getState().reset();
    useMe.getState().reset();
  },
}));
