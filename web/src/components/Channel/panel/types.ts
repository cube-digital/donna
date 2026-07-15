// Kit-facing view models for the ported ChannelPanel surfaces.

export type ChannelRole = "admin" | "member";

export interface KitChannel {
  id: string;
  name: string;
  topic: string;
  visibility: "public" | "private";
  created_by: string;
  created_at: string;
}

export interface KitChannelMember {
  id: string;
  name: string;
  email: string;
  initials: string;
  color: string;
  role: ChannelRole;
  is_you?: boolean;
}

export interface KitCandidate {
  id: string;
  name: string;
  email: string;
  initials: string;
  color: string;
}

export interface KitChannelAgent {
  id: string;
  name: string;
  handle: string;
  resident?: boolean;
  scope?: string;
  active?: boolean;
  color?: string;
}

export interface KitArtifacts {
  drafts: number;
  finalized: number;
}
