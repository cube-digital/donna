// Typed fetch wrapper.
//
// Attaches:
//   - Authorization: Bearer <access JWT>  (when present)
//   - X-Workspace-Id                       (when an active workspace is set)
//
// Unwraps the StandardJSONRenderer envelope `{data, meta, message, code}` so
// callers see the raw payload. On a 401 with a refresh token available,
// transparently refresh once and retry.
//
// Public endpoints under /api/auth/* skip the workspace header — they're
// covered by WorkspaceMiddleware.IGNORED_PATHS on the backend, but we also
// just don't send the header for those paths.

import {
  clearTokens,
  getAccess,
  getActiveWorkspace,
  getRefresh,
  setTokens,
} from "../lib/auth-storage";
import type { ApiEnvelope } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string | null,
    message: string,
    public readonly body?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface RequestInitX extends Omit<RequestInit, "body"> {
  body?: unknown;
  skipAuth?: boolean;
  skipWorkspace?: boolean;
  raw?: boolean; // skip envelope unwrap (used for non-DRF endpoints like SSE)
}

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: (() => void) | null): void {
  onUnauthorized = fn;
}

export async function tryRefresh(): Promise<boolean> {
  const refresh = getRefresh();
  if (!refresh) return false;
  try {
    const res = await fetch(`${API_BASE}/api/auth/token/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh }),
    });
    if (!res.ok) return false;
    const json = (await res.json()) as unknown;
    // simplejwt's response goes through StandardJSONRenderer, so it's
    // wrapped as `{data: {access, refresh?}, meta, message, code}`. Tolerate
    // both shapes — useful if the backend ever stops wrapping these.
    const payload =
      json !== null &&
      typeof json === "object" &&
      "data" in (json as Record<string, unknown>) &&
      (json as { data: unknown }).data !== null &&
      typeof (json as { data: unknown }).data === "object"
        ? ((json as { data: { access: string; refresh?: string } }).data)
        : (json as { access: string; refresh?: string });
    if (!payload?.access) return false;
    setTokens(payload.access, payload.refresh ?? refresh);
    return true;
  } catch {
    return false;
  }
}

export async function apiFetch<T = unknown>(
  path: string,
  init: RequestInitX = {},
): Promise<T> {
  const url = path.startsWith("http") ? path : `${API_BASE}${path}`;
  const headers = new Headers(init.headers);

  if (!init.skipAuth) {
    const access = getAccess();
    if (access) headers.set("Authorization", `Bearer ${access}`);
  }
  if (!init.skipWorkspace) {
    const wsId = getActiveWorkspace();
    if (wsId) headers.set("X-Workspace-Id", wsId);
  }
  if (init.body !== undefined && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetch(url, {
    ...init,
    headers,
    body:
      init.body === undefined
        ? undefined
        : init.body instanceof FormData
          ? init.body
          : JSON.stringify(init.body),
  });

  if (res.status === 401 && !init.skipAuth) {
    const refreshed = await tryRefresh();
    if (refreshed) {
      return apiFetch<T>(path, init);
    }
    clearTokens();
    onUnauthorized?.();
    throw new ApiError(401, "unauthenticated", "Sign in required");
  }

  const text = await res.text();
  const json = text ? (JSON.parse(text) as unknown) : null;

  if (!res.ok) {
    const env = (json ?? {}) as Partial<ApiEnvelope<unknown>> & {
      detail?: string;
    };
    throw new ApiError(
      res.status,
      env.code ?? null,
      env.message ?? env.detail ?? `HTTP ${res.status}`,
      json,
    );
  }

  if (init.raw) return json as T;

  // StandardJSONRenderer envelope. Some endpoints (simplejwt's signin /
  // token refresh) are NOT wrapped — they return the payload directly.
  if (json !== null && typeof json === "object" && "data" in (json as object)) {
    return (json as ApiEnvelope<T>).data;
  }
  return json as T;
}
