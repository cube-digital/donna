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
