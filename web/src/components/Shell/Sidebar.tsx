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
import { openAgentDM } from "../../api/chat";
import { useChannels } from "../../state/channels";
import { useIntegrations } from "../../state/integrations";
import { useWorkspace } from "../../state/workspace";
import type { Channel, IntegrationProvider } from "../../types";
import {
  GAvatar,
  GConnectorIcon,
  GListItem,
  GlyphSlot,
  type GListDot,
} from "../Goofy";
import { CreateChannelDialog } from "../Channel/CreateChannelDialog";
import { InviteToWorkspaceDialog } from "./InviteToWorkspaceDialog";

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
        "text-[11px] font-semibold uppercase tracking-[0.05em] px-1.5 pt-[15px] pb-[5px] flex items-center justify-between",
        ai ? "text-ai" : "text-text-4",
      )}
    >
      <span>{label}</span>
      {onAdd ? (
        <button
          type="button"
          aria-label={`Add ${label}`}
          onClick={onAdd}
          className="text-text-4 hover:text-text-1 bg-transparent border-0 p-0 leading-none"
        >
          <GlyphSlot name="plus" size={13} />
        </button>
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
  ai: "bg-ai",
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
  const location = useLocation();
  const navigate = useNavigate();
  const channelMatch = useMatch("/channels/:channelId");
  const activeChannelId = channelMatch?.params.channelId ?? null;
  const [createOpen, setCreateOpen] = useState(false);
  const [inviteOpen, setInviteOpen] = useState(false);
  const pinChannel = useChannels((s) => s.pinChannel);
  const unpinChannel = useChannels((s) => s.unpinChannel);

  const activeWorkspace = workspaces.find((w) => w.id === activeId);

  const { directs, pinned, publicChannels } = useMemo(() => {
    const dms: Channel[] = [];
    const pin: Channel[] = [];
    const chs: Channel[] = [];
    for (const c of channels) {
      // Agent DMs (the user's private Donna chat) are surfaced under
      // "AI teammates", not the human direct-messages list.
      if (c.kind === "direct") {
        if (!c.is_agent_dm) dms.push(c);
      } else if (c.is_pinned) pin.push(c);
      else chs.push(c);
    }
    chs.sort((a, b) => a.name.localeCompare(b.name));
    pin.sort((a, b) => a.name.localeCompare(b.name));
    dms.sort((a, b) => a.name.localeCompare(b.name));
    return { directs: dms, pinned: pin, publicChannels: chs };
  }, [channels]);

  const isSearchActive = location.pathname.startsWith("/search");

  // The active channel is the user's Donna DM when it's flagged is_agent_dm.
  const agentDmActive = channels.some(
    (c) => c.id === activeChannelId && c.is_agent_dm,
  );

  // Open (or reuse) the caller's isolated Donna DM, then navigate to it.
  const openDonna = async () => {
    try {
      const ch = await openAgentDM();
      await useChannels.getState().loadChannels();
      navigate(`/channels/${ch.id}`);
    } catch {
      /* surfaced by the channel view if it fails */
    }
  };

  return (
    <aside
      className="h-full bg-bg-2 border-r border-border-soft overflow-y-auto py-3 px-[11px]"
      aria-label="Channels and direct messages"
    >
      <header className="px-1.5 pt-1 pb-2.5">
        <button
          type="button"
          title="Workspace settings"
          aria-label="Open workspace settings"
          onClick={() => navigate("/settings")}
          className="w-full flex items-center gap-2.5 rounded-[10px] p-1 -mx-1 text-left hover:bg-bg-3 transition-colors"
        >
          <span className="w-8 h-8 shrink-0 grid place-items-center rounded-[9px] bg-pop-sun border-2 border-ink text-on-bright font-display font-bold text-[14px]">
            {(activeWorkspace?.name ?? "W").trim().charAt(0).toUpperCase()}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block font-display font-semibold text-text-0 text-[14px] tracking-[-0.005em] truncate">
              {activeWorkspace?.name ?? "Workspace"}
            </span>
            {activeWorkspace?.slug ? (
              <span className="block text-[11px] text-text-4 truncate">
                {activeWorkspace.slug}
              </span>
            ) : null}
          </span>
        </button>
      </header>

      {/* Top-level nav */}
      <div className="mt-2">
        <button
          type="button"
          aria-label="Search"
          aria-current={isSearchActive ? "page" : undefined}
          onClick={() => navigate("/search")}
          className="w-full flex items-center gap-[9px] py-2 px-2.5 rounded-[9px] bg-bg-1 border border-border-soft text-text-3 text-[13px] hover:border-border-strong"
        >
          <GlyphSlot name="search" size={16} />
          <span className="flex-1 text-left">Search</span>
          <kbd className="font-mono text-[10.5px] font-semibold px-1.5 py-0.5 rounded-[5px] border-[1.5px] border-ink bg-pop-sun text-on-bright">
            ⌘&nbsp;K
          </kbd>
        </button>
      </div>

      {/* Pinned channels — surfaced above DMs / Channels for quick access. */}
      {pinned.length > 0 && (
        <div>
          <GroupHeader label="pinned" />
          {pinned.map((c) => (
            <GListItem
              key={c.id}
              hash="#"
              active={activeChannelId === c.id}
              aria-label={`# ${c.name} (pinned)`}
              onClick={() => navigate(`/channels/${c.id}`)}
              badge={
                <button
                  type="button"
                  aria-label="Unpin"
                  onClick={(e) => {
                    e.stopPropagation();
                    void unpinChannel(c.id);
                  }}
                  className="text-text-3 hover:text-text-0 text-[14px] leading-none"
                  title="Unpin"
                >
                  ★
                </button>
              }
            >
              {c.name}
            </GListItem>
          ))}
        </div>
      )}

      {/* AI teammates — clicking Donna opens the user's private, isolated
          DM with her (context separate from channels, per-user memory). */}
      <div>
        <GroupHeader label="ai teammates" ai />
        <GListItem
          active={agentDmActive}
          aria-label="Donna"
          onClick={() => void openDonna()}
          icon={
            <GAvatar
              kind="agent"
              size="sm"
              name="Donna"
              hue={282}
              className="!bg-ai !bg-none !border-0 !rounded-md"
            />
          }
          badge={<TrailDot kind="ai" />}
        >
          Donna
        </GListItem>
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
              badge={
                <button
                  type="button"
                  aria-label="Pin channel"
                  onClick={(e) => {
                    e.stopPropagation();
                    void pinChannel(c.id);
                  }}
                  className="text-text-3 hover:text-ai opacity-0 group-hover:opacity-100 text-[14px] leading-none"
                  title="Pin"
                >
                  ☆
                </button>
              }
            >
              {c.name}
            </GListItem>
          ))
        )}
      </div>

      {/* Direct messages — below Channels; each row shows the peer's avatar
          + name (the person this DM is with). */}
      <div>
        <GroupHeader label="direct messages" onAdd={() => navigate("/new-message")} />
        {directs.length === 0 ? (
          <GListItem className="text-text-3 italic">
            No direct messages yet
          </GListItem>
        ) : (
          directs.map((c) => {
            const label = c.peer?.full_name || c.peer?.email || c.name || "Direct message";
            const away = c.peer?.is_away;
            return (
              <GListItem
                key={c.id}
                active={activeChannelId === c.id}
                aria-label={
                  c.peer ? `${label} · ${away ? "away" : "active"}` : label
                }
                onClick={() => navigate(`/channels/${c.id}`)}
                icon={
                  <span className="relative inline-flex">
                    <GAvatar
                      size="sm"
                      name={label}
                      src={c.peer?.picture_url ?? undefined}
                    />
                    {c.peer ? (
                      <span
                        className="absolute -bottom-0.5 -right-0.5 w-[9px] h-[9px] rounded-full border-2 border-bg-1"
                        style={{
                          background: away
                            ? "oklch(0.70 0.15 70)"
                            : "var(--ok, #22c55e)",
                        }}
                        title={away ? "Away" : "Active"}
                      />
                    ) : null}
                  </span>
                }
              >
                {label}
                {c.peer?.status ? (
                  <span className="ml-1.5 text-[11px] text-text-4 font-normal">
                    {c.peer.status}
                  </span>
                ) : null}
              </GListItem>
            );
          })
        )}
      </div>

      {/* Invite to workspace */}
      <div className="px-1.5 pt-2">
        <button
          type="button"
          onClick={() => setInviteOpen(true)}
          className="w-full flex items-center justify-center gap-1.5 px-2 py-2 text-[13px] font-medium border border-dashed border-border-strong rounded-[8px] text-text-3 hover:text-text-0 hover:border-ink"
        >
          <GlyphSlot name="plus" size={14} />
          Invite teammates
        </button>
      </div>

      <CreateChannelDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(ch) => navigate(`/channels/${ch.id}`)}
      />
      <InviteToWorkspaceDialog
        open={inviteOpen}
        onClose={() => setInviteOpen(false)}
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
          icon={<GlyphSlot name="bolt" size={16} />}
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
