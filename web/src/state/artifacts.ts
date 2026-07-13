// Channel-documents store — populates the Cowork left/right rail with
// drafts and finalized documents per channel. Fed by REST (load + filter)
// plus the WS `artifact.updated` event which arrives whenever the agent
// edits a draft via UpdateDraftSectionTool.

import { create } from "zustand";

import { listChannelArtifacts } from "../api/chat";
import type { ChannelArtifact } from "../types";

interface DocumentsState {
  byChannel: Record<string, ChannelArtifact[]>;
  loading: Record<string, boolean>;
  load(channelId: string): Promise<void>;
  /** Idempotent upsert from a WS payload. */
  upsertFromEvent(channelId: string, doc: ChannelArtifact): void;
}

function upsert(list: ChannelArtifact[], doc: ChannelArtifact): ChannelArtifact[] {
  const idx = list.findIndex((d) => d.id === doc.id);
  if (idx < 0) return [doc, ...list];
  const copy = list.slice();
  copy[idx] = doc;
  // Resort by updated_at desc for stable rendering.
  return copy.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
}

export const useArtifacts = create<DocumentsState>((set) => ({
  byChannel: {},
  loading: {},

  load: async (channelId) => {
    set((s) => ({ loading: { ...s.loading, [channelId]: true } }));
    try {
      const docs = await listChannelArtifacts(channelId);
      set((s) => ({
        byChannel: { ...s.byChannel, [channelId]: docs },
        loading: { ...s.loading, [channelId]: false },
      }));
    } catch {
      set((s) => ({ loading: { ...s.loading, [channelId]: false } }));
    }
  },

  upsertFromEvent: (channelId, doc) => {
    set((s) => {
      const list = s.byChannel[channelId] ?? [];
      return {
        byChannel: { ...s.byChannel, [channelId]: upsert(list, doc) },
      };
    });
  },
}));
