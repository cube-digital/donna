// One message row — port of `design-source/project/channel.jsx:75-130`.
//
// Three render branches keyed by `msg.kind`:
//   - "system"     → light divider with text only
//   - "agent-run"  → standard header + a Goofy `<GRun/>` sticker card
//   - "msg"        → default human / agent prose row with avatar +
//                    head (author + agent chip + time) + body bubble
//
// `kind` is computed client-side by the messages store; the wire
// shape doesn't include it. See state/messages.ts.
//
// Goofy rendering
// ───────────────
// Messages now render as sticker bubbles via `<GBubble/>`. The head
// row (author name + agent chip + time) sits ABOVE the bubble, not
// inside it. For agent messages the avatar lives inside `<GBubble/>`
// (its `avatar` slot); for user messages the bubble is right-aligned
// with no inline avatar. For agent-runs we pass the metadata directly
// into `<GRun/>` and drop the old `AgentRunCard`.
//
// Avatar pulsing
// ──────────────
// For agent-run messages whose metadata.status is "running", the
// avatar pulses (via the `av-pulse-ring` helper class) — the "agent
// is actively working" affordance from the design.
//
// Hover actions
// ─────────────
// The hover-actions row is positioned absolutely above the message.
// In Tailwind we put `group` on the row and `hidden group-hover:flex`
// on the actions so they appear on row hover. All but the "thread" and
// "ai" buttons are no-ops in v1; we keep them in markup for design
// fidelity. The toolbar wears the sticker chrome (border-ink + shadow).

import {
  GAvatar,
  GBubble,
  GIconButton,
  GRoleChip,
  GRun,
  type GRunStepData,
  type IconName,
} from "../Goofy";
import { comingSoonToast } from "../../state/toasts";
import type { AgentRunStep, Message as MessageT } from "../../types";

interface MessageProps {
  msg: MessageT;
}

function formatTime(iso: string): string {
  // 24h HH:MM — matches design's time glyph style.
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

function hueForAgent(id: string | undefined): number {
  // Stable hue per agent id so re-renders don't flicker the avatar
  // colour. The design clamps avatars to the AI violet family, but
  // we vary slightly so adjacent agent rows are distinguishable.
  if (!id) return 282;
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return 260 + (h % 60); // 260..319 — purple → indigo
}

// Map an AgentRunStep kind to a Goofy icon name. The Goofy `GRun`
// step shape takes an icon by name — same set of icons as the old
// AgentRunCard, just funneled through the central glyph slot.
function stepIconName(kind: AgentRunStep["kind"]): IconName {
  switch (kind) {
    case "read":
      return "doc";
    case "write":
      return "edit";
    case "think":
      return "brain";
    case "tool":
    default:
      return "bolt";
  }
}

export default function Message({ msg }: MessageProps) {
  if (msg.kind === "system") {
    return (
      <div className="px-[18px] pl-[60px] py-1 text-text-3 text-[12px]">
        {msg.body}
      </div>
    );
  }

  const isAgent = !!msg.author_agent && !msg.author_user;
  const time = formatTime(msg.updated_at || msg.created_at);
  const displayName = isAgent
    ? msg.author_agent?.name || "Agent"
    : msg.author_user?.full_name ||
      msg.author_user?.email ||
      "You";

  // Pulsing avatar when this is a running agent-run — see module doc.
  const isRunningAgentRun =
    msg.kind === "agent-run" && (msg.metadata?.status ?? "done") === "running";

  // Agent-run shape mapping. We pull all the metadata onto the
  // GRun props — when a real AgentRun model lands server-side, lift
  // this off `msg.metadata` and onto a typed serializer field.
  const meta = msg.metadata ?? {};
  const agentName = msg.author_agent?.name ?? "agent";
  const runSteps: GRunStepData[] = (meta.steps ?? []).map((s) => ({
    icon: stepIconName(s.kind),
    label: s.label,
    meta: s.meta,
    state: s.state,
  }));
  // GRun takes a single memory chip; join multiple touched-memory
  // strings into one comma-separated chip so we don't drop data.
  const memoryChip =
    meta.memoryTouched && meta.memoryTouched.length
      ? meta.memoryTouched.join(", ")
      : undefined;

  // For agent rows we hand the avatar into `<GBubble/>` as the slot;
  // for user rows the bubble is right-aligned with no inline avatar,
  // and the head row sits above the bubble in the same direction.
  const agentAvatar = isAgent ? (
    <GAvatar
      kind="agent"
      pulsing={isRunningAgentRun}
      name={msg.author_agent?.name ?? "A"}
      hue={hueForAgent(msg.author_agent?.id)}
    />
  ) : null;

  return (
    <div className="group relative px-[18px] py-1 hover:bg-bg-2">
      {/* For agent-run we render the sticker card directly, prefixed
          by the standard head row with name + agent chip + time. */}
      {msg.kind === "agent-run" ? (
        <div className="flex flex-col gap-1.5">
          <div className="flex items-baseline gap-2 pl-[42px]">
            <span className="font-semibold text-text-0 text-[13px] tracking-[-0.005em]">
              {displayName}
            </span>
            {isAgent ? <GRoleChip>Agent</GRoleChip> : null}
            <span className="text-[11px] text-text-3">{time}</span>
          </div>
          <div className="pl-[42px]">
            <GRun
              label="Agent run"
              summary={meta.summary}
              status={isRunningAgentRun ? "thinking" : "done"}
              running={isRunningAgentRun}
              thought={meta.streaming ? meta.currentThought : undefined}
              steps={runSteps}
              output={meta.output}
              memory={memoryChip}
              footer={{ approveLabel: `Continue with ${agentName}` }}
              onDismiss={() => comingSoonToast("Add to context")}
              onApprove={() => comingSoonToast(`Continue with ${agentName}`)}
            />
          </div>
        </div>
      ) : (
        <div
          className={
            isAgent
              ? "flex flex-col gap-1 items-start"
              : "flex flex-col gap-1 items-end"
          }
        >
          <div
            className={
              isAgent
                ? "flex items-baseline gap-2 pl-[42px]"
                : "flex items-baseline gap-2"
            }
          >
            <span className="font-semibold text-text-0 text-[13px] tracking-[-0.005em]">
              {displayName}
            </span>
            {isAgent ? <GRoleChip>Agent</GRoleChip> : null}
            <span className="text-[11px] text-text-3">{time}</span>
          </div>
          <GBubble
            from={isAgent ? "agent" : "user"}
            avatar={agentAvatar ?? undefined}
          >
            {msg.body.split("\n").map((line, i) => (
              <p key={i} className="m-0 mb-1 last:mb-0">
                {line}
              </p>
            ))}
          </GBubble>
        </div>
      )}

      <div className="absolute -top-2.5 right-6 hidden group-hover:flex gap-0.5 p-0.5 border-2 border-ink rounded-[10px] shadow-ink-1 bg-bg-1">
        <GIconButton
          icon="smile"
          title="React"
          aria-label="React"
          size="sm"
          onClick={() => {
            /* v1: reactions not wired */
          }}
        />
        <GIconButton
          icon="thread"
          title="Reply in thread"
          aria-label="Reply in thread"
          size="sm"
          onClick={() => comingSoonToast("Threads")}
        />
        <GIconButton
          icon="share"
          title="Share"
          aria-label="Share"
          size="sm"
          onClick={() => {
            /* v1: no-op */
          }}
        />
        <GIconButton
          icon="sparkle"
          size="sm"
          title="Ask an agent"
          aria-label="Ask an agent"
          // State-driven AI-tinted hover — this is the only icon button
          // that flips to grape on hover, so we keep the colour mutation
          // inline rather than baking another variant into GIconButton.
          className="hover:text-ai hover:bg-ai-bg"
          onClick={() => comingSoonToast("Ask an agent")}
        />
        <GIconButton
          icon="more"
          title="More"
          aria-label="More actions"
          size="sm"
          onClick={() => {
            /* v1: no-op */
          }}
        />
      </div>
    </div>
  );
}
