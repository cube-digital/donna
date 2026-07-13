import { apiFetch } from "./client";

export interface CortexFile {
  id: string;
  type: string;
  title: string;
  source: string;
  author: string;
  occurred_at: string | null;
  /** True when a raw source (bronze) blob exists — signed lazily on open. */
  has_bronze: boolean;
  relationship: string | null;
  client_id: string | null;
  project_id: string | null;
}

export interface CortexFilesPage {
  data: CortexFile[];
  next_cursor: string | null;
}

export async function listCortexFiles(opts: {
  q?: string;
  type?: string;
  relationship?: string;
  cursor?: string;
  limit?: number;
} = {}): Promise<CortexFilesPage> {
  const params = new URLSearchParams();
  if (opts.q) params.set("q", opts.q);
  if (opts.type) params.set("type", opts.type);
  if (opts.relationship) params.set("relationship", opts.relationship);
  if (opts.cursor) params.set("cursor", opts.cursor);
  if (opts.limit) params.set("limit", String(opts.limit));
  return apiFetch<CortexFilesPage>(
    `/api/v1/cortex/entities/files/?${params}`,
  );
}

export interface CortexEntityCard {
  id: string;
  type: string;
  title: string;
  /** Markdown body, served inline (authed) — no cross-origin S3 fetch. */
  body_md?: string;
  /** Presigned raw-source URL, signed lazily on detail open. */
  bronze_url?: string | null;
  occurred_at: string;
  client_id?: string | null;
  project_id?: string | null;
  source?: string;
}

export interface CortexContext {
  neighbors: CortexEntityCard[];
}

export async function getCortexEntity(id: string, includeBody = true) {
  return apiFetch<CortexEntityCard>(
    `/api/v1/cortex/entities/${id}/?include_body=${includeBody}`,
  );
}

export async function getCortexContext(id: string, depth = 1) {
  return apiFetch<CortexContext>(
    `/api/v1/cortex/entities/${id}/context/?depth=${depth}`,
  );
}

export interface CortexCounts {
  by_type: Record<string, number>;
  by_relationship: Record<string, number>;
}

/** Per-type + per-org-relationship counts in one aggregate call (sidebar). */
export async function getCortexCounts() {
  return apiFetch<CortexCounts>("/api/v1/cortex/entities/counts/");
}
