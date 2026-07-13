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
// Goofy rendering
// ───────────────
// Chrome is sticker pills: title in Fredoka display, meta line in
// hand-written Caveat, AI / member / notifications pills become
// `<GChip/>` and `<GButton/>`. The more-actions menu is a `<GPopover/>`
// with `<GMenuItem/>`s and a danger row at the end.

import { useMemo } from "react";

import { GIconButton, GlyphSlot } from "../Goofy";
import { useChannels } from "../../state/channels";
import type { AgentRef, Channel, Message, User } from "../../types";
import { AgentStatusChip } from "./AgentStatusChip";
import { FilesToggle } from "./FilesToggle";
import { ToolSummaryChip } from "./ToolSummaryChip";

interface ChannelHeaderProps {
  channel: Channel;
  /** Messages currently loaded for this channel; used to derive author chrome. */
  channelMessages?: Message[];
}

function dedupeUsers(messages: Message[]): User[] {
  const seen = new Set<string>();
  const out: User[] = [];
  for (const m of messages) {
    const raw = m.author_user as unknown;
    if (!raw) continue;
    // Backend can return either a nested {id,...} object or a bare UUID
    // string depending on serializer. Normalize to a minimal User stub
    // so the consumer's `.id`/`.full_name` access stays safe.
    const u: User =
      typeof raw === "string"
        ? { id: raw, email: "", full_name: "", email_verified: false }
        : (raw as User);
    if (!u.id || seen.has(u.id)) continue;
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

  const pinned = channel.topic ? channel.topic : "—";

  return (
    <div className="flex items-center gap-[9px] px-[18px] py-[11px] border-b border-border-soft shrink-0">
      <div className="flex flex-col gap-0.5">
        <div className="flex items-center gap-1.5">
          {isDM ? (
            <GlyphSlot name="at" size={15} className="text-text-3" />
          ) : (
            <GlyphSlot name="hash" size={15} className="text-text-3" />
          )}
          <span className="font-display font-semibold text-[16px] text-text-0">
            {channel.name || (isDM ? "Direct message" : "channel")}
          </span>
          {/* Plan 13 §8.2 — ambient agent state inline next to the name. */}
          <AgentStatusChip channelId={channel.id} />
          {/* Plan 13 §1.2 — Haiku one-liner under the header when fresh. */}
          <ToolSummaryChip channelId={channel.id} />
          <GIconButton
            icon="star"
            size="sm"
            title={channel.is_pinned ? "Unpin channel" : "Pin channel"}
            aria-label={channel.is_pinned ? "Unpin channel" : "Pin channel"}
            onClick={() => {
              const s = useChannels.getState();
              if (channel.is_pinned) void s.unpinChannel(channel.id);
              else void s.pinChannel(channel.id);
            }}
            className={channel.is_pinned ? "text-ai" : ""}
          />
        </div>
      </div>

      <div className="flex-1" />

      <FilesToggle channelId={channel.id} />

      <span
        className="inline-flex items-center gap-[5px] text-[11px] font-semibold px-[9px] py-[3px] rounded-md bg-ai-bg text-ai-deep"
        title="Agents on this channel"
      >
        <GlyphSlot name="sparkle" size={12} />
        {agents.length || 0} AI
      </span>

      <span
        className="inline-flex items-center gap-[5px] text-[11px] font-semibold px-[9px] py-[3px] rounded-md bg-bg-1 text-text-3"
        title="Channel members"
      >
        {humans.length} {humans.length === 1 ? "member" : "members"}
      </span>

      <span className="text-[11px] text-text-4">Pinned: {pinned}</span>
    </div>
  );
}
