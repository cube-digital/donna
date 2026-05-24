// Integrations HTTP endpoints — backed by
// server/donna/integrations/api/v1/views.py.
//
// Endpoints (mounted under /api/v1/integrations/):
//   GET    /api/v1/integrations/                              list (envelope-wrapped)
//   GET    /api/v1/integrations/{slug}/                       retrieve
//   POST   /api/v1/integrations/{slug}/connect/               { authorize_url }
//   POST   /api/v1/integrations/{slug}/disconnect/            204
//   GET    /api/v1/integrations/{slug}/subscription/          Connection row
//   PATCH  /api/v1/integrations/{slug}/subscription/          { config } → Connection
//
// Backend serializer returns
//   { slug, display_name, category, is_configured, is_connected }
// We project that onto the frontend type
//   { slug, display_name, status, scope, description? }
// at the API boundary so views don't repeat the mapping.
//
// `scope` isn't surfaced by the backend list endpoint — we default to
// "user" until the serializer exposes `token_scope` on the DTO. The
// `status` collapses the two booleans:
//   not configured + not connected → "not_connected"
//   configured     + not connected → "not_connected"
//   configured     + connected     → "live"
//   not configured + connected     → "error"   (drift; row exists but creds gone)

import { apiFetch } from "./client";
import type { Connection, IntegrationProvider } from "../types";

interface RawIntegrationStatus {
  slug: string;
  display_name: string;
  category: string;
  is_configured: boolean;
  is_connected: boolean;
}

function toProvider(raw: RawIntegrationStatus): IntegrationProvider {
  let status: IntegrationProvider["status"];
  if (raw.is_connected && raw.is_configured) status = "live";
  else if (raw.is_connected && !raw.is_configured) status = "error";
  else status = "not_connected";
  return {
    slug: raw.slug,
    display_name: raw.display_name,
    status,
    scope: "user", // default; backend list DTO doesn't surface token_scope.
    description: raw.category || undefined,
  };
}

export async function listIntegrations(): Promise<IntegrationProvider[]> {
  const data = await apiFetch<RawIntegrationStatus[]>("/api/v1/integrations/");
  return data.map(toProvider);
}

export async function getIntegration(slug: string): Promise<IntegrationProvider> {
  const data = await apiFetch<RawIntegrationStatus>(
    `/api/v1/integrations/${slug}/`,
  );
  return toProvider(data);
}

export async function connectIntegration(
  slug: string,
): Promise<{ authorize_url: string }> {
  return apiFetch<{ authorize_url: string }>(
    `/api/v1/integrations/${slug}/connect/`,
    {
      method: "POST",
      body: {},
    },
  );
}

export async function disconnectIntegration(slug: string): Promise<void> {
  await apiFetch<void>(`/api/v1/integrations/${slug}/disconnect/`, {
    method: "POST",
    body: {},
  });
}

export async function getSubscription(slug: string): Promise<Connection> {
  return apiFetch<Connection>(`/api/v1/integrations/${slug}/subscription/`);
}

export async function updateSubscription(
  slug: string,
  config: Record<string, unknown>,
): Promise<Connection> {
  return apiFetch<Connection>(`/api/v1/integrations/${slug}/subscription/`, {
    method: "PATCH",
    body: { config },
  });
}
