// Shared types — mirror the backend serializers under server/donna/*/api/v1/serializers.py.
// Backend responses are wrapped by donna.core.renderers.StandardJSONRenderer as
// { data, meta, message, code } — see api/client.ts for the unwrap.

export type UUID = string;
export type ISODateTime = string;

export interface User {
  id: UUID;
  email: string;
  full_name: string;
  email_verified: boolean;
}

export interface Workspace {
  id: UUID;
  name: string;
  slug: string;
}

export type WorkspaceRole = "owner" | "admin" | "member" | "guest";

export interface WorkspaceMembership {
  id: UUID;
  workspace: UUID;
  user: User;
  role: WorkspaceRole;
}

export type ChannelKind = "channel" | "direct";
export type ChannelVisibility = "public" | "private";
export type ChannelMemberRole = "admin" | "member";

export interface Channel {
  id: UUID;
  kind: ChannelKind;
  name: string;
  slug: string;
  topic: string;
  visibility: ChannelVisibility;
  workspace: UUID;
  /** Channel-scoped feature flags. See backend Channel.DEFAULT_SETTINGS. */
  settings?: Record<string, unknown>;
  created_at: ISODateTime;
  updated_at: ISODateTime;
}

export interface ChannelMembership {
  id: UUID;
  channel: UUID;
  user: UUID;
  role: ChannelMemberRole;
  created_at: ISODateTime;
}

export interface AgentRef {
  id: UUID;
  name: string;
}

export interface MessageAttachment {
  name: string;
  size?: string;
}

export interface AgentRunStep {
  kind: "read" | "write" | "think" | "tool";
  label: string;
  meta?: string;
  state?: "done" | "running";
}

// The agent-run UI shape is stored on Message.metadata for v1 (no schema change).
// When the AgentRun model lands, lift this onto a real serializer.
export interface AgentRunMetadata {
  summary?: string;
  status?: "running" | "done";
  streaming?: boolean;
  currentThought?: string;
  steps?: AgentRunStep[];
  output?: string;
  memoryTouched?: string[];
  attachments?: MessageAttachment[];
}

export type MessageKind = "msg" | "system" | "agent-run";

export interface Message {
  id: UUID;
  channel: UUID;
  body: string;
  author_user: User | null;
  author_agent: AgentRef | null;
  created_at: ISODateTime;
  updated_at: ISODateTime;
  client_msg_id?: string | null;
  // UI-derived; computed in state/messages.ts, not from the wire:
  kind?: MessageKind;
  metadata?: AgentRunMetadata;
}

export interface Notification {
  id: UUID;
  title: string;
  message: string;
  status: "info" | "warning" | "error" | "success";
  type: string;
  seen: boolean;
  context: Record<string, unknown>;
  created_at: ISODateTime;
}

/**
 * JSON Schema subset shipped from the backend connector `config_schema`.
 * Loose `Record<string, unknown>` because the only consumer is the
 * IntegrationForm engine which walks it at runtime.
 */
export type ConfigSchema = Record<string, unknown>;

export interface IntegrationProvider {
  slug: string;
  display_name: string;
  status: "live" | "read-only" | "not_connected" | "error";
  scope: "user" | "workspace";
  description?: string;
  /** Populated on the retrieve endpoint only (omitted from list). */
  config_schema?: ConfigSchema | null;
  default_config?: Record<string, unknown> | null;
}

export interface Connection {
  id: UUID;
  provider_slug: string;
  config: Record<string, unknown>;
  state: Record<string, unknown>;
  enabled: boolean;
  last_synced_at: ISODateTime | null;
  last_error_msg: string | null;
}

// API envelope from donna.core.renderers.StandardJSONRenderer
export interface ApiEnvelope<T> {
  data: T;
  meta?: Record<string, unknown> | null;
  message?: string | null;
  code?: string | null;
}

// Pagination from drf default pagination_class
export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface AuthTokens {
  access: string;
  refresh: string;
}
