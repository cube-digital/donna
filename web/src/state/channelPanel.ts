// Toggle store for the channel details panel — opened from the channel
// header member pill, rendered once as an overlay by AppShell.

import { create } from "zustand";

interface ChannelPanelState {
  openChannelId: string | null;
  open(id: string): void;
  close(): void;
}

export const useChannelPanel = create<ChannelPanelState>((set) => ({
  openChannelId: null,
  open: (id) => set({ openChannelId: id }),
  close: () => set({ openChannelId: null }),
}));
