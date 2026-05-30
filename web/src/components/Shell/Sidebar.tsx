// 252px channel/DM/agents list — middle-left column.
// Ported from donnaai/project/sidebar.jsx:1-141, then re-skinned onto the
// Goofy sticker library: list rows become `<GListItem/>` (sun-yellow ink
// border when active, mini-wiggle on hover), section headers use Fredoka,
// the workspace edit + add buttons are `<GIconButton/>` stickers.
//
// Sections, top to bottom:
//   1. Workspace header — active workspace name + edit affordance.
//   2. Top-level nav   — Search (⌘K), Personal·Donna, Activity, Threads.
//   3. Direct messages — channels where kind === "direct".
//   4. AI Teammates    — hardcoded single Donna row in v1 (no /agents endpoint).
//   5. Channels        — channels where kind === "channel", sorted by name.
//   6. Connections     — connected integrations (Gmail, Drive, Fathom, …).
//   7. Apps            — single stubbed Workflows row.
//
// Project grouping is intentionally not implemented: the backend has
// no Project model yet, so we render channels flat under one "Channels"
// header. When projects land, group channels by project FK and lift the
// project name onto a `.project-h` row above the channel cluster.

import { useEffect, useMemo, useState } from "react";
import { useLocation, useMatch, useNavigate } from "react-router-dom";

import { cn } from "../../lib/cn";
import { hueForAgent } from "../../lib/hueForAgent";
import { useChannels } from "../../state/channels";
import { useIntegrations } from "../../state/integrations";
import { useMessages } from "../../state/messages";
import { useWorkspace } from "../../state/workspace";
import type { AgentRef, Channel, IntegrationProvider } from "../../types";
import {
  GAvatar,
  GConnectorIcon,
  GIconButton,
  GListItem,
  GlyphSlot,
  type GListDot,
} from "../Goofy";
import { CreateChannelDialog } from "../Channel/CreateChannelDialog";

// Section header — small Fredoka label on the left, optional sticker
// `+` icon on the right. The AI Teammates header recolours the label
// to AI grape so the section still reads as the "AI" cluster.
function GroupHeader({
  label,
  ai,
  onAdd,
}: {
  label: string;
  ai?: boolean;
  onAdd?: () => void;
}) {
  return (
    <div
      className={cn(
        "font-display font-semibold text-[12.5px] px-2.5 pt-3 pb-1.5 flex items-center justify-between",
        ai ? "text-ai" : "text-text-2",
      )}
    >
      <span>{label}</span>
      {onAdd ? (
        <GIconButton
          icon="plus"
          size="xs"
          aria-label={`Add ${label}`}
          onClick={onAdd}
        />
      ) : null}
    </div>
  );
}

// Map a connector status to the dot-colour shown in the trailing badge
// slot. Only "live" and "error" providers reach the sidebar (filtered
// upstream), but the fallback keeps the type narrowed if that changes.
function statusToDot(status: IntegrationProvider["status"]): GListDot {
  if (status === "live") return "online";
  if (status === "error") return "ai"; // treat as warning — AI dot is the loudest
  return "muted";
}

// Standalone dot used in the trailing `badge` slot — same colour map
// as `<GListItem dot=…/>` but rendered manually so we don't shift
// every row's leading icon column when a status dot exists.
const TRAIL_DOT_CLS: Record<GListDot, string> = {
  online: "bg-ok",
  ai: "bg-ai shadow-[0_0_0_2px_var(--ai-glow)]",
  muted: "bg-text-3",
};
function TrailDot({ kind }: { kind: GListDot }) {
  return (
    <span
      aria-hidden
      className={cn(
        "w-[7px] h-[7px] rounded-full shrink-0",
        TRAIL_DOT_CLS[kind],
      )}
    />
  );
}

export default function Sidebar() {
  const { workspaces, activeId } = useWorkspace();
  const channels = useChannels((s) => s.channels);
  const byChannel = useMessages((s) => s.byChannel);
  const location = useLocation();
  const navigate = useNavigate();
  const channelMatch = useMatch("/channels/:channelId");
  const agentMatch = useMatch("/agents/:agentId");
  const activeChannelId = channelMatch?.params.channelId ?? null;
  const activeAgentId = agentMatch?.params.agentId ?? null;
  const [createOpen, setCreateOpen] = useState(false);

  const activeWorkspace = workspaces.find((w) => w.id === activeId);

  const { directs, publicChannels } = useMemo(() => {
    const dms: Channel[] = [];
    const chs: Channel[] = [];
    for (const c of channels) {
      if (c.kind === "direct") dms.push(c);
      else chs.push(c);
    }
    chs.sort((a, b) => a.name.localeCompare(b.name));
    dms.sort((a, b) => a.name.localeCompare(b.name));
    return { directs: dms, publicChannels: chs };
  }, [channels]);

  // AI teammates — scan every loaded message across every channel,
  // dedupe authoring agents by id. The backend has no /agents endpoint
  // yet, so we infer the roster from observed message authorship. If
  // nothing's been said, fall back to a single hardcoded Donna row so
  // the section isn't empty.
  const teammates = useMemo(() => {
    const seen = new Map<string, AgentRef>();
    for (const list of Object.values(byChannel)) {
      for (const m of list) {
        const a = m.author_agent;
        if (a && a.id && a.name && !seen.has(a.id)) {
          seen.set(a.id, a);
        }
      }
    }
    return Array.from(seen.values()).sort((a, b) =>
      a.name.localeCompare(b.name),
    );
  }, [byChannel]);

  const isSearchActive = location.pathname.startsWith("/search");
  const isPersonalActive = location.pathname.startsWith("/personal");

  return (
    <aside
      className="[grid-area:sidebar] bg-bg-1 border-r border-border-soft overflow-y-auto pt-2 px-1.5 pb-4"
      aria-label="Channels and direct messages"
    >
      <header className="flex items-center justify-between px-2.5 pt-1.5 pb-2.5">
        <div>
          <div className="font-display font-semibold text-text-0 text-[14px] tracking-[-0.005em]">
            {activeWorkspace?.name ?? "Workspace"}
          </div>
          {activeWorkspace?.slug ? (
            <div className="font-mono text-[10.5px] text-text-3">
              {activeWorkspace.slug}
            </div>
          ) : null}
        </div>
        <GIconButton
          icon="edit"
          size="xs"
          title="Workspace settings"
          aria-label="Workspace settings"
        />
      </header>

      {/* Top-level nav */}
      <div className="mt-2">
        <GListItem
          active={isSearchActive}
          aria-label="Search"
          onClick={() => navigate("/search")}
          icon={<GlyphSlot name="search" />}
          badge={
            <kbd className="font-mono text-[10.5px] px-1.5 py-0.5 rounded-[5px] border-[1.5px] border-ink bg-pop-sun text-on-bright">
              ⌘&nbsp;K
            </kbd>
          }
        >
          Search
        </GListItem>
        <GListItem
          active={isPersonalActive}
          aria-label="Personal AI"
          onClick={() => navigate("/personal")}
          icon={<GlyphSlot name="sparkle" className="text-ai" />}
          badge={<TrailDot kind="ai" />}
        >
          Personal · Donna
        </GListItem>
        <GListItem aria-label="Activity" icon={<GlyphSlot name="bell" />}>
          Activity
        </GListItem>
        <GListItem aria-label="Threads" icon={<GlyphSlot name="thread" />}>
          Threads
        </GListItem>
      </div>

      {/* Direct messages */}
      <div>
        <GroupHeader label="direct messages" />
        {directs.length === 0 ? (
          <GListItem className="text-text-3 italic">
            No direct messages yet
          </GListItem>
        ) : (
          directs.map((c) => (
            <GListItem
              key={c.id}
              active={activeChannelId === c.id}
              aria-label={c.name}
              onClick={() => navigate(`/channels/${c.id}`)}
              icon={<GAvatar size="sm" name={c.name} />}
            >
              {c.name}
            </GListItem>
          ))
        )}
      </div>

      {/* AI teammates — derived from observed message authorship; falls
          back to a single Donna placeholder when no agent has spoken yet. */}
      <div>
        <GroupHeader label="ai teammates" ai />
        {teammates.length === 0 ? (
          <GListItem
            aria-label="Donna"
            icon={<GAvatar kind="agent" size="sm" name="Donna" hue={282} />}
            badge={<TrailDot kind="ai" />}
          >
            Donna
          </GListItem>
        ) : (
          teammates.map((a) => (
            <GListItem
              key={a.id}
              active={activeAgentId === a.id}
              aria-label={a.name}
              onClick={() => navigate(`/agents/${a.id}`)}
              icon={
                <GAvatar
                  kind="agent"
                  size="sm"
                  name={a.name}
                  hue={hueForAgent(a.id)}
                />
              }
              badge={<TrailDot kind="ai" />}
            >
              {a.name}
            </GListItem>
          ))
        )}
      </div>

      {/* Channels — flat list (no project grouping in v1; backend has no Project model) */}
      <div>
        <GroupHeader label="channels" onAdd={() => setCreateOpen(true)} />
        {publicChannels.length === 0 ? (
          <GListItem className="text-text-3 italic">
            No channels yet
          </GListItem>
        ) : (
          publicChannels.map((c) => (
            <GListItem
              key={c.id}
              hash="#"
              active={activeChannelId === c.id}
              aria-label={`# ${c.name}`}
              onClick={() => navigate(`/channels/${c.id}`)}
            >
              {c.name}
            </GListItem>
          ))
        )}
      </div>

      <CreateChannelDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(ch) => navigate(`/channels/${ch.id}`)}
      />

      {/* Connections — connected integrations (Gmail, Drive, Fathom, ...).
          Pattern blend: Slack "Apps" entry placement + Linear connection cards
          + Discord-style brand icon + status dot. Clicking opens the existing
          IntegrationModal (same surface as the right rail listing). */}
      <ConnectionsGroup />

      {/* Apps — placeholder kept for v1 parity with the design source. */}
      <div>
        <GroupHeader label="apps" />
        <GListItem
          aria-disabled={true}
          // Disabled rows should be skipped during Tab navigation;
          // they're not actionable yet (Workflows stub) so taking them
          // out of the focus order keeps the keyboard tour purposeful.
          tabIndex={-1}
          className="opacity-60 cursor-not-allowed"
          icon={<GlyphSlot name="bolt" />}
        >
          Workflows
        </GListItem>
      </div>
    </aside>
  );
}

// ── Connections ─────────────────────────────────────────────────────────────

function ConnectionsGroup() {
  const providers = useIntegrations((s) => s.providers);
  const loaded = useIntegrations((s) => s.loaded);
  const load = useIntegrations((s) => s.load);
  const navigate = useNavigate();

  useEffect(() => {
    if (!loaded) void load();
  }, [loaded, load]);

  const connected = providers.filter(
    (p) => p.status === "live" || p.status === "error",
  );

  return (
    <div>
      <GroupHeader label="connections" onAdd={() => navigate("/integrations")} />

      {connected.length === 0 ? (
        <GListItem className="text-text-3 italic">
          No connections yet
        </GListItem>
      ) : (
        connected.map((p) => <ConnectionRow key={p.slug} provider={p} />)
      )}
    </div>
  );
}

function ConnectionRow({ provider }: { provider: IntegrationProvider }) {
  const active = !!useMatch(`/integrations/${provider.slug}`);
  const navigate = useNavigate();

  return (
    <GListItem
      active={active}
      aria-label={`${provider.display_name} integration settings`}
      onClick={() => navigate(`/integrations/${provider.slug}`)}
      icon={<GConnectorIcon slug={provider.slug} label={provider.display_name} />}
      badge={<TrailDot kind={statusToDot(provider.status)} />}
    >
      {provider.display_name}
    </GListItem>
  );
}
