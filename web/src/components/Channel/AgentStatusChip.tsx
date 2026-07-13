// Plan 13 §8.2 — ambient agent status chip.
//
// Subscribes to `chat.agent.status` WS events for the channel and
// renders the agent's current state ("drafting…", "waiting on you")
// inline. Auto-clears on `idle`.
//
// Mounted once per channel view; no props beyond the channel id.

import { useAgentStatusFor, type AgentStatus } from "../../state/agentStatus";

interface Props {
  channelId: string;
}

const LABEL: Record<AgentStatus["state"], string> = {
  typing: "typing…",
  drafting: "drafting…",
  waiting_on_user: "waiting on you",
  running_tool: "working on it…",
  scheduled_for: "scheduled",
};

export function AgentStatusChip({ channelId }: Props) {
  const status = useAgentStatusFor(channelId);
  if (!status) return null;

  const label = LABEL[status.state];
  const detail = status.detail
    ? ` — ${status.detail.slice(0, 80)}`
    : status.eta
      ? ` (${new Date(status.eta).toLocaleString()})`
      : "";

  return (
    <div
      role="status"
      aria-live="polite"
      className="inline-flex items-center gap-1 rounded-full bg-[var(--ai-bg)] px-2 py-0.5 text-[10px] font-semibold tracking-wide text-[color:var(--ai-deep)]"
      data-state={status.state}
    >
      <span className="size-1.5 rounded-full bg-[color:var(--ai)] animate-pulse" />
      <span>{label}{detail}</span>
    </div>
  );
}
