// Channel store — populated once when AppShell mounts and updated by
// the chat WS consumer when channels are created / renamed / deleted.
//
// `byId` is a derived index kept in sync with `channels` on every set —
// callers reaching for a single channel by id (TopBar crumb, Channel view)
// hit O(1) here instead of scanning the list.

import { create } from "zustand";

import {
  createChannel as apiCreate,
  deleteChannel as apiDelete,
  listChannels,
  updateChannel as apiUpdate,
  type CreateChannelInput,
  type UpdateChannelInput,
} from "../api/chat";
import type { Channel } from "../types";

interface ChannelsState {
  channels: Channel[];
  byId: Record<string, Channel>;
  loading: boolean;
  loadChannels: () => Promise<void>;
  setChannels: (channels: Channel[]) => void;
  // Mutators — call the HTTP API then merge the server row into the store.
  createChannel: (input: CreateChannelInput) => Promise<Channel>;
  updateChannel: (id: string, input: UpdateChannelInput) => Promise<Channel>;
  deleteChannel: (id: string) => Promise<void>;
  // WS event handlers — used by the chat WS listener for cross-tab fanout.
  upsertFromEvent: (channel: Channel) => void;
  removeFromEvent: (id: string) => void;
}

function indexById(channels: Channel[]): Record<string, Channel> {
  const out: Record<string, Channel> = {};
  for (const c of channels) out[c.id] = c;
  return out;
}

function sortByName(a: Channel, b: Channel): number {
  return a.name.localeCompare(b.name);
}

export const useChannels = create<ChannelsState>((set, get) => ({
  channels: [],
  byId: {},
  loading: false,

  setChannels: (channels) => set({ channels, byId: indexById(channels) }),

  loadChannels: async () => {
    set({ loading: true });
    try {
      const channels = await listChannels();
      set({ channels, byId: indexById(channels), loading: false });
    } catch {
      set({ loading: false });
    }
  },

  createChannel: async (input) => {
    const created = await apiCreate(input);
    get().upsertFromEvent(created);
    return created;
  },

  updateChannel: async (id, input) => {
    const updated = await apiUpdate(id, input);
    get().upsertFromEvent(updated);
    return updated;
  },

  deleteChannel: async (id) => {
    await apiDelete(id);
    get().removeFromEvent(id);
  },

  upsertFromEvent: (channel) => {
    const next = [
      ...get().channels.filter((c) => c.id !== channel.id),
      channel,
    ].sort(sortByName);
    set({ channels: next, byId: indexById(next) });
  },

  removeFromEvent: (id) => {
    if (!get().byId[id]) return;
    const next = get().channels.filter((c) => c.id !== id);
    set({ channels: next, byId: indexById(next) });
  },
}));
