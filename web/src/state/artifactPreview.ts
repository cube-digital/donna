// Tracks the artifact currently shown in the right-rail preview pane.
// Set when the user clicks a `doc://<id>` chip in a message; cleared
// when they close the preview or navigate away.

import { create } from "zustand";

interface ArtifactPreviewState {
  artifactId: string | null;
  channelId: string | null;
  /** Per-channel "user dismissed the rail" override. Even when an
   *  active draft exists, the rail stays closed until the user explicitly
   *  re-opens it from the Files menu. Reopening clears the entry. */
  dismissedChannels: Record<string, true>;
  open: (artifactId: string, channelId: string) => void;
  close: () => void;
  dismiss: (channelId: string) => void;
  undismiss: (channelId: string) => void;
}

export const useArtifactPreview = create<ArtifactPreviewState>((set) => ({
  artifactId: null,
  channelId: null,
  dismissedChannels: {},
  open: (artifactId, channelId) =>
    set((s) => {
      const next = { ...s.dismissedChannels };
      delete next[channelId];
      return { artifactId, channelId, dismissedChannels: next };
    }),
  close: () => set({ artifactId: null, channelId: null }),
  dismiss: (channelId) =>
    set((s) => ({
      artifactId: null,
      channelId: null,
      dismissedChannels: { ...s.dismissedChannels, [channelId]: true },
    })),
  undismiss: (channelId) =>
    set((s) => {
      if (!(channelId in s.dismissedChannels)) return s;
      const next = { ...s.dismissedChannels };
      delete next[channelId];
      return { dismissedChannels: next };
    }),
}));
