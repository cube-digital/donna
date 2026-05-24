// Channel store — populated once when AppShell mounts and updated by
// the chat WS consumer when channels are created/renamed/archived.
//
// `byId` is a derived index kept in sync with `channels` on every set —
// callers reaching for a single channel by id (TopBar crumb, Channel view)
// hit O(1) here instead of scanning the list.

import { create } from "zustand";
import { listChannels } from "../api/chat";
import type { Channel } from "../types";

interface ChannelsState {
  channels: Channel[];
  byId: Record<string, Channel>;
  loading: boolean;
  loadChannels: () => Promise<void>;
  setChannels: (channels: Channel[]) => void;
}

function indexById(channels: Channel[]): Record<string, Channel> {
  const out: Record<string, Channel> = {};
  for (const c of channels) out[c.id] = c;
  return out;
}

export const useChannels = create<ChannelsState>((set) => ({
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
      // Surface in UI via empty state; details handled by ApiError consumers.
      set({ loading: false });
    }
  },
}));
