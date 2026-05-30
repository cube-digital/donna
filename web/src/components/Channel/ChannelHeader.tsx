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

import { useEffect, useRef, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  GAvatarStack,
  GButton,
  GChip,
  GIconButton,
  GMenuItem,
  GMenuSep,
  GPopover,
  GlyphSlot,
} from "../Goofy";
import { useChannels } from "../../state/channels";
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
  if (humans.length)
    metaParts.push(`${humans.length} member${humans.length === 1 ? "" : "s"}`);
  if (agents.length)
    metaParts.push(`${agents.length} AI`);
  metaParts.push(`Pinned: ${pinned}`);

  return (
    <div className="flex items-center gap-3 px-[18px] py-2.5 border-b border-border-soft shrink-0">
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
          <GIconButton
            icon="star"
            size="sm"
            title="Star channel"
            aria-label="Star channel"
            onClick={() => {
              /* v1: no star endpoint yet */
            }}
          />
        </div>
        <div className="font-hand font-bold text-[15px] text-ai-deep mt-px leading-none">
          {metaParts.join(" · ")}
        </div>
      </div>

      <div className="flex-1" />

      {/* AI pill — agents observed in the currently loaded messages. */}
      {visibleAgents.length > 0 ? (
        <GChip variant="ai" size="lg" title="Agents on this channel">
          <GlyphSlot name="sparkle" size={13} />
          <GAvatarStack
            people={visibleAgents.map((a) => ({
              kind: "agent",
              name: a.name,
              hue: hueForAgent(a.id),
            }))}
            size="sm"
          />
          <span className="ml-1">{agents.length}</span>
        </GChip>
      ) : (
        <GChip variant="ai" size="lg" title="No agents in this channel yet">
          <GlyphSlot name="sparkle" size={13} />
          AI on standby
        </GChip>
      )}

      {/* Member stack — humans observed in the currently loaded messages. */}
      {visibleHumans.length > 0 ? (
        <div className="flex items-center gap-1.5">
          <GAvatarStack
            people={visibleHumans.map((u) => ({
              name: u.full_name || u.email || "?",
              color: colorForUser(u.id),
            }))}
            size="sm"
          />
          {overflowHumans > 0 ? (
            <span className="text-[12px] text-text-2 px-1">
              +{overflowHumans}
            </span>
          ) : (
            <span className="text-[12px] text-text-2 px-1">
              {humans.length}
            </span>
          )}
        </div>
      ) : null}

      <GButton
        variant="default"
        size="sm"
        icon="bell"
        title="Notification settings"
        aria-label="Notification settings"
      >
        Notifications
      </GButton>
      <ChannelActionsMenu channel={channel} />
    </div>
  );
}

// ── Per-channel actions (rename + delete) ──────────────────────────────────
// Lightweight kebab menu attached to the header. Rename uses an
// inline prompt for v1; delete asks confirm() then routes back to /channels.

function ChannelActionsMenu({ channel }: { channel: Channel }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const updateChannel = useChannels((s) => s.updateChannel);
  const deleteChannel = useChannels((s) => s.deleteChannel);

  useEffect(() => {
    if (!open) return;
    function onDoc(e: MouseEvent) {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  async function rename() {
    const next = window.prompt("Rename channel", channel.name);
    if (next === null) return;
    const trimmed = next.trim();
    if (!trimmed || trimmed === channel.name) return;
    setBusy(true);
    try {
      await updateChannel(channel.id, { name: trimmed });
    } catch (e) {
      window.alert((e as Error).message);
    } finally {
      setBusy(false);
      setOpen(false);
    }
  }

  async function setTopic() {
    const next = window.prompt("Channel topic", channel.topic);
    if (next === null) return;
    setBusy(true);
    try {
      await updateChannel(channel.id, { topic: next });
    } catch (e) {
      window.alert((e as Error).message);
    } finally {
      setBusy(false);
      setOpen(false);
    }
  }

  async function toggleVisibility() {
    const next = channel.visibility === "public" ? "private" : "public";
    setBusy(true);
    try {
      await updateChannel(channel.id, { visibility: next });
    } catch (e) {
      window.alert((e as Error).message);
    } finally {
      setBusy(false);
      setOpen(false);
    }
  }

  async function destroy() {
    const ok = window.confirm(
      `Delete #${channel.name}? All messages and history will be removed.`,
    );
    if (!ok) return;
    setBusy(true);
    try {
      await deleteChannel(channel.id);
      navigate("/channels");
    } catch (e) {
      window.alert((e as Error).message);
      setBusy(false);
    }
  }

  // Wrap each menu item in a small `aria-disabled` shim so the busy
  // state surfaces visually + blocks the click without breaking
  // GMenuItem's role / keyboard semantics.
  function handleClick(fn: () => void) {
    return () => {
      if (busy) return;
      fn();
    };
  }

  return (
    <div ref={ref} className="relative">
      <GIconButton
        icon="more"
        title="More actions"
        aria-label="More actions"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      />
      {open && (
        <GPopover className="absolute right-0 mt-1 z-20 w-[200px]">
          <GMenuItem
            icon="edit"
            aria-disabled={busy}
            onClick={handleClick(rename)}
          >
            Rename channel
          </GMenuItem>
          <GMenuItem
            icon="pin"
            aria-disabled={busy}
            onClick={handleClick(setTopic)}
          >
            Set topic
          </GMenuItem>
          <GMenuItem
            icon="lock"
            aria-disabled={busy}
            onClick={handleClick(toggleVisibility)}
          >
            Make {channel.visibility === "public" ? "private" : "public"}
          </GMenuItem>
          <GMenuSep />
          <GMenuItem
            danger
            icon="trash"
            aria-disabled={busy}
            onClick={handleClick(destroy)}
          >
            Delete channel
          </GMenuItem>
        </GPopover>
      )}
    </div>
  );
}
