// JWT persistence. Plain localStorage for v1.
// Keep this module pure — no React, no fetch. It's imported by both the
// API client and the auth store.

const ACCESS_KEY = "donna.auth.access";
const REFRESH_KEY = "donna.auth.refresh";
const WORKSPACE_KEY = "donna.workspace.active";

export function getAccess(): string | null {
  return localStorage.getItem(ACCESS_KEY);
}

export function getRefresh(): string | null {
  return localStorage.getItem(REFRESH_KEY);
}

export function setTokens(access: string, refresh: string): void {
  localStorage.setItem(ACCESS_KEY, access);
  localStorage.setItem(REFRESH_KEY, refresh);
}

export function clearTokens(): void {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

export function getActiveWorkspace(): string | null {
  return localStorage.getItem(WORKSPACE_KEY);
}

export function setActiveWorkspace(id: string | null): void {
  if (id === null) localStorage.removeItem(WORKSPACE_KEY);
  else localStorage.setItem(WORKSPACE_KEY, id);
}

/** Read the signed-in user's id from the JWT access token, no fetch.
 *
 *  simplejwt encodes ``user_id`` in the access payload (see
 *  ``ACCESS_TOKEN_LIFETIME`` in server/donna/settings.py). We don't
 *  verify the signature here — the server does that on every request.
 *  Returns ``null`` if no token is stored or the payload is malformed.
 */
export function getCurrentUserId(): string | null {
  const access = getAccess();
  if (!access) return null;
  const segments = access.split(".");
  if (segments.length !== 3) return null;
  try {
    // Base64URL → standard base64 before atob.
    const b64 = segments[1].replace(/-/g, "+").replace(/_/g, "/");
    const payload = JSON.parse(
      atob(b64 + "=".repeat((4 - (b64.length % 4)) % 4)),
    ) as { user_id?: string };
    return payload.user_id ?? null;
  } catch {
    return null;
  }
}
