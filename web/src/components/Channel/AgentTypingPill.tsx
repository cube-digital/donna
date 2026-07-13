// Slack-style "Donna is …" indicator above the composer.
//
// Reads the same per-channel `chat.agent.status` feed the header chip
// uses (via `useAgentStatusFor`), but renders inline with the typing
// row so the user gets a familiar IRC-shaped cue while waiting for the
// next agent message.
//
// Visual contract:
//   • dot-pulse on the left (three dots, staggered animation)
//   • "Donna is drafting…" / "thinking…" / "waiting on you…"
//   • Auto-hides when state becomes "idle".

import { useAgentStatusFor, type AgentStatus } from "../../state/agentStatus";

interface Props {
  channelId: string;
  /** Optional override; defaults to "Donna". */
  agentName?: string;
}

const VERB: Record<AgentStatus["state"], string> = {
  typing: "is typing",
  drafting: "is drafting",
  waiting_on_user: "is waiting on you",
  running_tool: "is thinking",
  scheduled_for: "is scheduled",
};

export function AgentTypingPill({ channelId, agentName = "Donna" }: Props) {
  const status = useAgentStatusFor(channelId);
  if (!status) return null;

  const verb = VERB[status.state];

  return (
    <div
      role="status"
      aria-live="polite"
      className="px-[22px] pt-1 pb-1.5 min-h-[24px] flex items-center gap-2 text-[12px] text-text-2"
      data-state={status.state}
    >
      {/* Discord-style dots pill */}
      <span
        aria-hidden
        className="inline-flex items-center gap-1 rounded-full bg-bg-2 px-2 py-1"
      >
        <span
          className="size-1.5 rounded-full bg-text-3 animate-bounce"
          style={{ animationDelay: "0ms", animationDuration: "1200ms" }}
        />
        <span
          className="size-1.5 rounded-full bg-text-3 animate-bounce"
          style={{ animationDelay: "200ms", animationDuration: "1200ms" }}
        />
        <span
          className="size-1.5 rounded-full bg-text-3 animate-bounce"
          style={{ animationDelay: "400ms", animationDuration: "1200ms" }}
        />
      </span>
      <span>
        <span className="font-semibold text-text-1">{agentName}</span>{" "}
        <span className="text-text-3">{verb}…</span>
      </span>
    </div>
  );
}
