// One message row — port of `design-source/project/channel.jsx:75-130`.
//
// Three render branches keyed by `msg.kind`:
//   - "system"     → light divider with text only
//   - "agent-run"  → standard header + an `<AgentRunCard/>` instead of
//                    the body text (see AgentRunCard.tsx)
//   - "msg"        → default human / agent prose row with avatar +
//                    head (author + agent chip + time) + body text
//
// `kind` is computed client-side by the messages store; the wire
// shape doesn't include it. See state/messages.ts.
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
// fidelity.

import { GAvatar, GlyphSlot } from "../Goofy";
import type { Message as MessageT } from "../../types";

import AgentRunCard from "./AgentRunCard";

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

// Hover-action buttons (the row that fades in above a message on hover).
const HB =
  "w-6 h-6 rounded-sm grid place-items-center text-text-2 hover:bg-bg-3 hover:text-text-0";
const HB_AI =
  "w-6 h-6 rounded-sm grid place-items-center text-text-2 hover:text-ai hover:bg-ai-bg";

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

  return (
    <div className="group relative flex gap-2.5 px-[18px] py-1 hover:bg-[oklch(1_0_0_/0.018)]">
      <div className="w-8 pt-0.5">
        {isAgent ? (
          <GAvatar
            kind="agent"
            pulsing={isRunningAgentRun}
            name={msg.author_agent?.name ?? "A"}
            hue={hueForAgent(msg.author_agent?.id)}
          />
        ) : (
          <GAvatar
            name={displayName}
          />
        )}
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2">
          <span className="font-semibold text-text-0 text-[13px] tracking-[-0.005em]">
            {displayName}
          </span>
          {isAgent ? (
            <span className="text-[9.5px] tracking-[0.06em] uppercase font-semibold px-1.5 py-px rounded-sm bg-ai-bg text-ai border border-ai-glow">
              Agent
            </span>
          ) : null}
          <span className="text-[11px] text-text-3">{time}</span>
        </div>

        {msg.kind === "agent-run" ? (
          <AgentRunCard msg={msg} />
        ) : (
          <div className="text-text-1 text-[13px] leading-[1.55] mt-px [&>p]:m-0 [&>p]:mb-1">
            {msg.body.split("\n").map((line, i) => (
              <p key={i}>{line}</p>
            ))}
          </div>
        )}
      </div>

      <div className="absolute -top-2.5 right-6 hidden group-hover:flex gap-px bg-bg-2 border border-border-strong rounded-md shadow-soft p-px">
        <button
          type="button"
          className={HB}
          title="React"
          aria-label="React"
          onClick={() => {
            /* v1: reactions not wired */
          }}
        >
          <GlyphSlot name="smile" />
        </button>
        <button
          type="button"
          className={HB}
          title="Reply in thread"
          aria-label="Reply in thread"
          onClick={() => alert("Threads coming soon")}
        >
          <GlyphSlot name="thread" />
        </button>
        <button
          type="button"
          className={HB}
          title="Share"
          aria-label="Share"
          onClick={() => {
            /* v1: no-op */
          }}
        >
          <GlyphSlot name="share" />
        </button>
        <button
          type="button"
          className={HB_AI}
          title="Ask an agent"
          aria-label="Ask an agent"
          onClick={() => alert("Ask-an-agent coming soon")}
        >
          <GlyphSlot name="sparkle" />
        </button>
        <button
          type="button"
          className={HB}
          title="More"
          aria-label="More actions"
          onClick={() => {
            /* v1: no-op */
          }}
        >
          <GlyphSlot name="more" />
        </button>
      </div>
    </div>
  );
}
