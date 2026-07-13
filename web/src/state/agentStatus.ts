// Per-channel ambient agent status.
//
// The backend's `broadcast_agent_status` emits a `chat.agent.status`
// frame on the channel group whenever an agent turn changes state
// (drafting / running_tool / waiting_on_user / scheduled_for / idle).
//
// We keep a tiny Zustand store keyed by channel id so multiple UI
// surfaces can read the same state — the header pill at the top of the
// channel + the Slack-style "Donna is …" indicator above the composer.
//
// `idle` clears the entry. Anything else replaces it.

import { create } from "zustand";

export type AgentState =
  | "typing"
  | "drafting"
  | "waiting_on_user"
  | "running_tool"
  | "scheduled_for"
  | "idle";

export interface AgentStatus {
  state: Exclude<AgentState, "idle">;
  detail: string;
  eta: string;
  sessionId: string;
}

interface AgentStatusState {
  byChannel: Record<string, AgentStatus>;
  setStatus(
    channelId: string,
    next: { state: AgentState; detail?: string; eta?: string; sessionId: string },
  ): void;
  clear(channelId: string): void;
}

export const useAgentStatus = create<AgentStatusState>((set) => ({
  byChannel: {},
  setStatus: (channelId, next) =>
    set((s) => {
      if (next.state === "idle") {
        if (!(channelId in s.byChannel)) return s;
        const copy = { ...s.byChannel };
        delete copy[channelId];
        return { byChannel: copy };
      }
      return {
        byChannel: {
          ...s.byChannel,
          [channelId]: {
            state: next.state,
            detail: next.detail ?? "",
            eta: next.eta ?? "",
            sessionId: next.sessionId,
          },
        },
      };
    }),
  clear: (channelId) =>
    set((s) => {
      if (!(channelId in s.byChannel)) return s;
      const copy = { ...s.byChannel };
      delete copy[channelId];
      return { byChannel: copy };
    }),
}));

export function useAgentStatusFor(channelId: string | undefined): AgentStatus | null {
  return useAgentStatus((s) => (channelId ? s.byChannel[channelId] ?? null : null));
}
