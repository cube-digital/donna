// Channel header bar — the row above `.chat-scroll`. Ported from the
// `ChannelHeader` block in `design-source/project/channel.jsx:152-187`.
//
// What's real
// ───────────
// - channel.name / channel.topic / channel.kind from the REST channel row.
// - The AI pill and member stack are derived from the currently-loaded
//   message list: we collect unique human authors and unique agent
//   authors from `channelMessages` and render up to 4 humans / 3 agents
//   plus an overflow count. This isn't a true "members" view (no
//   members endpoint yet) but it's the closest live data we have and it
//   matches the design's intent: "who's actually here".
//
// What's still stubbed
// ────────────────────
// - The "12 members · 3 AI teammates · Pinned: …" meta line is a stub
//   string — `channel.members_count`/`pinned_titles` don't exist on the
//   serializer yet. We render a best-effort line using the *derived*
//   counts so it stays alive.
//
// Member-stack overlap: in the old CSS the `.av` children get
// `margin-left: -6px` + a 2px `--bg-0` border, with the first child
// reset to `margin-left: 0`. We reproduce that with `[&>*]:-ml-1.5
// [&>*:first-child]:ml-0 [&>*]:border-2 [&>*]:border-bg-0` on the
// stack container so the children keep their generic `<Av/>` markup.

import { useMemo } from "react";

import Av from "../Ui/Av";
import { Ic } from "../Ui/Ic";
import type { AgentRef, Channel, Message, User } from "../../types";

interface ChannelHeaderProps {
  channel: Channel;
  /** Messages currently loaded for this channel; used to derive author chrome. */
  channelMessages?: Message[];
}

// Stable hue per agent id — same algorithm as Message.tsx so a given
// agent shows the same colour in both places.
function hueForAgent(id: string | undefined): number {
  if (!id) return 282;
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return 260 + (h % 60);
}

// Stable, deterministic colour per human author id. The design's avatar
// chrome doesn't depend on this being signal-bearing; we just want a
// rotation so adjacent rows aren't all identical.
const HUMAN_PALETTE = [
  "#7c6bff",
  "#3da9fc",
  "#f59e0b",
  "#10b981",
  "#ef4444",
  "#8b5cf6",
  "#06b6d4",
  "#84cc16",
];
function colorForUser(id: string): string {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return HUMAN_PALETTE[h % HUMAN_PALETTE.length];
}

function dedupeUsers(messages: Message[]): User[] {
  const seen = new Set<string>();
  const out: User[] = [];
  for (const m of messages) {
    const u = m.author_user;
    if (!u || seen.has(u.id)) continue;
    seen.add(u.id);
    out.push(u);
  }
  return out;
}

function dedupeAgents(messages: Message[]): AgentRef[] {
  const seen = new Set<string>();
  const out: AgentRef[] = [];
  for (const m of messages) {
    const a = m.author_agent;
    if (!a || seen.has(a.id)) continue;
    seen.add(a.id);
    out.push(a);
  }
  return out;
}

const PILL =
  "flex items-center gap-1.5 h-[26px] px-2.5 rounded-[7px] border border-border-soft text-[12px] text-text-1 bg-bg-2 hover:bg-bg-3";
const PILL_AI =
  "flex items-center gap-1.5 h-[26px] px-2.5 rounded-[7px] border border-ai-glow text-[12px] text-ai bg-ai-bg hover:bg-bg-3";

export default function ChannelHeader({
  channel,
  channelMessages = [],
}: ChannelHeaderProps) {
  const isDM = channel.kind === "direct";

  const humans = useMemo(() => dedupeUsers(channelMessages), [channelMessages]);
  const agents = useMemo(
    () => dedupeAgents(channelMessages),
    [channelMessages],
  );

  const visibleHumans = humans.slice(0, 4);
  const overflowHumans = Math.max(0, humans.length - visibleHumans.length);
  const visibleAgents = agents.slice(0, 3);

  // Pinned topics — until a `pinned_titles` field lands we use the
  // channel topic if present.
  const pinned = channel.topic ? channel.topic : "—";
  const metaParts: string[] = [];
  if (humans.length) metaParts.push(`${humans.length} member${humans.length === 1 ? "" : "s"}`);
  if (agents.length) metaParts.push(`${agents.length} AI teammate${agents.length === 1 ? "" : "s"}`);
  metaParts.push(`Pinned: ${pinned}`);

  return (
    <div className="flex items-center gap-3 px-[18px] py-2.5 border-b border-border-soft shrink-0">
      <div className="flex flex-col gap-0.5">
        <div className="flex items-center gap-1.5 text-[15px] font-semibold text-text-0 tracking-[-0.01em]">
          {isDM ? (
            <Ic.at className="text-text-3" />
          ) : (
            <span className="text-text-3">#</span>
          )}
          <span>{channel.name || (isDM ? "Direct message" : "channel")}</span>
          <button
            type="button"
            title="Star channel"
            aria-label="Star channel"
            className="text-text-3 hover:text-text-0"
            onClick={() => {
              /* v1: no star endpoint yet */
            }}
          >
            <Ic.star width={14} height={14} />
          </button>
        </div>
        <div className="text-text-3 text-[12px]">{metaParts.join(" · ")}</div>
      </div>

      <div className="flex-1" />

      {/* AI pill — agents observed in the currently loaded messages. */}
      {visibleAgents.length > 0 ? (
        <button
          type="button"
          className={PILL_AI}
          title="Agents on this channel"
        >
          <Ic.sparkle width={12} height={12} />
          <div className="flex ml-0.5 [&>*]:-ml-1.5 [&>*:first-child]:ml-0 [&>*]:border-2 [&>*]:border-bg-0">
            {visibleAgents.map((a) => (
              <Av
                key={a.id}
                kind="agent"
                size="sm"
                agent={{ name: a.name || "A", hue: hueForAgent(a.id) }}
              />
            ))}
          </div>
          <span className="ml-1">{agents.length}</span>
        </button>
      ) : (
        <button
          type="button"
          className={PILL_AI}
          title="No agents in this channel yet"
        >
          <Ic.sparkle width={12} height={12} />
          AI on standby
        </button>
      )}

      {/* Member stack — humans observed in the currently loaded messages. */}
      {visibleHumans.length > 0 ? (
        <div className="flex items-center gap-1.5">
          <div className="flex [&>*]:-ml-1.5 [&>*:first-child]:ml-0 [&>*]:border-2 [&>*]:border-bg-0">
            {visibleHumans.map((u) => (
              <Av
                key={u.id}
                kind="human"
                size="sm"
                who={{
                  name: u.full_name || u.email || "?",
                  color: colorForUser(u.id),
                }}
              />
            ))}
          </div>
          {overflowHumans > 0 ? (
            <span className="text-[12px] text-text-2 px-1">+{overflowHumans}</span>
          ) : (
            <span className="text-[12px] text-text-2 px-1">{humans.length}</span>
          )}
        </div>
      ) : null}

      <button
        type="button"
        className={PILL}
        title="Notification settings"
        aria-label="Notification settings"
      >
        <Ic.bell width={12} height={12} />
        Notifications
      </button>
      <button
        type="button"
        className={PILL}
        title="More actions"
        aria-label="More actions"
      >
        <Ic.more width={12} height={12} />
      </button>
    </div>
  );
}
