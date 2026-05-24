// Authentication API.
//
// Endpoints (server/donna/authentication/api/v1/urls.py):
//   POST /api/auth/signup          → 201 enveloped { message }
//   POST /api/auth/signin          → 200 enveloped { access, refresh, redirect_uri? }
//   POST /api/auth/token/refresh   → 200 enveloped { access, refresh? }
//   POST /api/auth/logout          → 200 enveloped {}
//   GET  /api/auth/google/login    → 200 enveloped { authorization_url }
//
// IMPORTANT: every endpoint goes through `StandardJSONRenderer`, so the
// payload is always wrapped as `{data, meta, message, code}`. `apiFetch`
// unwraps the envelope by default — DO NOT pass `raw: true` here, or the
// SDK consumers get `undefined` access tokens (verified the hard way).
//
// All auth calls pass `skipAuth: true` + `skipWorkspace: true` so we don't
// send a stale Bearer token / workspace header that could cause a 401 →
// refresh loop on the very endpoints used to acquire tokens.

import { apiFetch } from "./client";
import { clearTokens, getRefresh } from "../lib/auth-storage";

export interface SignupInput {
  email: string;
  full_name: string;
  password: string;
}

export interface SigninInput {
  email: string;
  password: string;
}

export interface TokenPair {
  access: string;
  refresh: string;
}

export async function signup(input: SignupInput): Promise<{ message: string }> {
  // Signup goes through a DRF generic so it IS wrapped in the envelope.
  return apiFetch<{ message: string }>("/api/auth/signup", {
    method: "POST",
    body: input,
    skipAuth: true,
    skipWorkspace: true,
  });
}

export async function signin(input: SigninInput): Promise<TokenPair> {
  return apiFetch<TokenPair>("/api/auth/signin", {
    method: "POST",
    body: input,
    skipAuth: true,
    skipWorkspace: true,
  });
}

export async function logout(): Promise<void> {
  const refresh = getRefresh();
  try {
    if (refresh) {
      await apiFetch<unknown>("/api/auth/logout", {
        method: "POST",
        body: { refresh },
        skipWorkspace: true,
      });
    }
  } finally {
    // Always drop local tokens even if the server call failed — the user
    // pressed "sign out" and we should respect that intent.
    clearTokens();
  }
}

export async function googleStartUrl(): Promise<string> {
  const data = await apiFetch<{ authorization_url: string }>(
    "/api/auth/google/login",
    { method: "GET", skipAuth: true, skipWorkspace: true },
  );
  return data.authorization_url;
}
