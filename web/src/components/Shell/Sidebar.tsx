// 252px channel/DM/agents list — middle-left column.
// Ported from donnaai/project/sidebar.jsx:1-141.
//
// Sections, top to bottom:
//   1. Workspace header — active workspace name + edit affordance.
//   2. Top-level nav   — Search (⌘K), Personal·Donna, Activity, Threads.
//   3. Direct messages — channels where kind === "direct".
//   4. AI Teammates    — hardcoded single Donna row in v1 (no /agents endpoint).
//   5. Channels        — channels where kind === "channel", sorted by name.
//   6. Apps            — single stubbed Workflows row.
//
// Project grouping is intentionally not implemented: the backend has
// no Project model yet, so we render channels flat under one "Channels"
// header. When projects land, group channels by project FK and lift the
// project name onto a `.project-h` row above the channel cluster.

import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useMatch, useNavigate } from "react-router-dom";

import { hueForAgent } from "../../lib/hueForAgent";
import { useChannels } from "../../state/channels";
import { useIntegrations } from "../../state/integrations";
import { useMessages } from "../../state/messages";
import { useWorkspace } from "../../state/workspace";
import type { AgentRef, Channel, IntegrationProvider } from "../../types";
import { ConnectorIcon } from "../Ui/BrandIc";
import { Av } from "../Ui/Av";
import { Ic } from "../Ui/Ic";
import { CreateChannelDialog } from "../Channel/CreateChannelDialog";

// Tailwind class fragments for the sidebar row variants. Hoisted so
// the JSX below stays scannable.
const ROW_BASE =
  "relative flex items-center gap-2 px-2.5 py-1 my-px rounded-md text-text-1 text-[13px] hover:bg-bg-2 hover:text-text-0";
const ROW_ACTIVE = "bg-bg-3 text-text-0";
const ROW_UNREAD = "text-text-0 font-medium";
const ROW_DISABLED = "text-text-3 cursor-default hover:bg-transparent hover:text-text-3";

const HASH_SLOT = "text-text-3 w-3.5 text-center flex-shrink-0";
const NAME_SLOT =
  "flex-1 min-w-0 overflow-hidden text-ellipsis whitespace-nowrap";

function cls(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

interface NavRowProps {
  active?: boolean;
  unread?: boolean;
  to?: string;
  ariaLabel?: string;
  onClick?: () => void;
  children: React.ReactNode;
}

function NavRow({
  active,
  unread,
  to,
  ariaLabel,
  onClick,
  children,
}: NavRowProps) {
  const className = cls(ROW_BASE, active && ROW_ACTIVE, unread && ROW_UNREAD);

  if (to) {
    return (
      <Link
        to={to}
        className={className}
        aria-label={ariaLabel}
        aria-current={active ? "page" : undefined}
      >
        {children}
      </Link>
    );
  }
  return (
    <button
      type="button"
      className={cls(className, "w-full text-left")}
      aria-label={ariaLabel}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

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
      className={cls(
        "flex items-center justify-between px-2.5 py-1 text-[11px] tracking-[0.04em] uppercase font-medium",
        ai ? "text-ai" : "text-text-3",
      )}
    >
      <span>{label}</span>
      {onAdd ? (
        <button
          type="button"
          className="w-[18px] h-[18px] rounded-sm grid place-items-center text-text-3 hover:bg-bg-2 hover:text-text-0"
          aria-label={`Add ${label}`}
          onClick={onAdd}
        >
          <Ic.plus />
        </button>
      ) : null}
    </div>
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

  return (
    <aside
      className="[grid-area:sidebar] bg-bg-1 border-r border-border-soft overflow-y-auto pt-2 px-1.5 pb-4"
      aria-label="Channels and direct messages"
    >
      <header className="flex items-center justify-between px-2.5 pt-1.5 pb-2.5">
        <div>
          <div className="font-semibold text-text-0 text-sm tracking-[-0.005em]">
            {activeWorkspace?.name ?? "Workspace"}
          </div>
          {activeWorkspace?.slug ? (
            <div className="text-[11px] text-text-3">
              {activeWorkspace.slug}
            </div>
          ) : null}
        </div>
        <div className="flex gap-1">
          <button
            type="button"
            className="w-6 h-6 rounded-md grid place-items-center text-text-2 hover:bg-bg-2 hover:text-text-0"
            title="Workspace settings"
            aria-label="Workspace settings"
          >
            <Ic.edit />
          </button>
        </div>
      </header>

      {/* Top-level nav */}
      <div className="mt-3">
        <NavRow
          to="/search"
          active={location.pathname.startsWith("/search")}
          ariaLabel="Search"
        >
          <span className={HASH_SLOT}>
            <Ic.search />
          </span>
          <span className={NAME_SLOT}>Search</span>
          <kbd className="font-mono text-[10.5px] text-text-3 px-[5px] py-px rounded-sm bg-bg-2 border border-border-soft">
            ⌘K
          </kbd>
        </NavRow>
        <NavRow
          to="/personal"
          active={location.pathname.startsWith("/personal")}
          ariaLabel="Personal AI"
        >
          <span className={HASH_SLOT}>
            <Ic.sparkle />
          </span>
          <span className={cls(NAME_SLOT, "text-text-0")}>
            Personal · Donna
          </span>
          <span className="w-1.5 h-1.5 rounded-full bg-ai shadow-[0_0_6px_var(--ai-glow)]" />
        </NavRow>
        <NavRow ariaLabel="Activity">
          <span className={HASH_SLOT}>
            <Ic.bell />
          </span>
          <span className={NAME_SLOT}>Activity</span>
        </NavRow>
        <NavRow ariaLabel="Threads">
          <span className={HASH_SLOT}>
            <Ic.thread />
          </span>
          <span className={NAME_SLOT}>Threads</span>
        </NavRow>
      </div>

      {/* Direct messages */}
      <div className="mt-3">
        <GroupHeader label="Direct messages" />
        {directs.length === 0 ? (
          <div className={cls(ROW_BASE, ROW_DISABLED)}>
            <span className={cls(NAME_SLOT, "text-[12px]")}>
              No direct messages yet
            </span>
          </div>
        ) : (
          directs.map((c) => (
            <NavRow
              key={c.id}
              to={`/channels/${c.id}`}
              active={activeChannelId === c.id}
              ariaLabel={c.name}
            >
              <Av
                kind="human"
                size="sm"
                who={{ name: c.name, initials: c.name.slice(0, 2).toUpperCase() }}
              />
              <span className={NAME_SLOT}>{c.name}</span>
            </NavRow>
          ))
        )}
      </div>

      {/* AI teammates — derived from observed message authorship; falls
          back to a single Donna placeholder when no agent has spoken yet. */}
      <div className="mt-3">
        <GroupHeader label="AI Teammates" ai />
        {teammates.length === 0 ? (
          <NavRow ariaLabel="Donna">
            <Av kind="agent" size="sm" agent={{ name: "Donna", hue: 282 }} />
            <span className={cls(NAME_SLOT, "text-text-0")}>Donna</span>
            <span className="w-1.5 h-1.5 rounded-full bg-ai shadow-[0_0_6px_var(--ai-glow)]" />
          </NavRow>
        ) : (
          teammates.map((a) => (
            <NavRow
              key={a.id}
              to={`/agents/${a.id}`}
              active={activeAgentId === a.id}
              ariaLabel={a.name}
            >
              <Av
                kind="agent"
                size="sm"
                agent={{ name: a.name, hue: hueForAgent(a.id) }}
              />
              <span className={cls(NAME_SLOT, "text-text-0")}>{a.name}</span>
              <span className="w-1.5 h-1.5 rounded-full bg-ai shadow-[0_0_6px_var(--ai-glow)]" />
            </NavRow>
          ))
        )}
      </div>

      {/* Channels — flat list (no project grouping in v1; backend has no Project model) */}
      <div className="mt-3">
        <GroupHeader label="Channels" onAdd={() => setCreateOpen(true)} />
        {publicChannels.length === 0 ? (
          <div className={cls(ROW_BASE, ROW_DISABLED)}>
            <span className={cls(NAME_SLOT, "text-[12px]")}>
              No channels yet
            </span>
          </div>
        ) : (
          publicChannels.map((c) => (
            <NavRow
              key={c.id}
              to={`/channels/${c.id}`}
              active={activeChannelId === c.id}
              ariaLabel={`# ${c.name}`}
            >
              <span className={HASH_SLOT}>#</span>
              <span className={NAME_SLOT}>{c.name}</span>
            </NavRow>
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
      <div className="mt-3">
        <GroupHeader label="Apps" />
        <div
          className={cls(ROW_BASE, "text-text-2 cursor-default hover:bg-transparent hover:text-text-2")}
        >
          <span className={HASH_SLOT}>
            <Ic.bolt />
          </span>
          <span className={NAME_SLOT}>Workflows</span>
        </div>
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
    <div className="mt-3">
      <GroupHeader label="Connections" onAdd={() => navigate("/integrations")} />

      {connected.length === 0 ? (
        <div className={cls(ROW_BASE, ROW_DISABLED)}>
          <span className={cls(NAME_SLOT, "text-[12px]")}>
            No connections yet
          </span>
        </div>
      ) : (
        connected.map((p) => <ConnectionRow key={p.slug} provider={p} />)
      )}
    </div>
  );
}

function ConnectionRow({ provider }: { provider: IntegrationProvider }) {
  const active = !!useMatch(`/integrations/${provider.slug}`);
  const dotClass =
    provider.status === "live"
      ? "bg-ok shadow-[0_0_6px_var(--ok)]"
      : provider.status === "error"
      ? "bg-danger"
      : "bg-bg-3";

  return (
    <Link
      to={`/integrations/${provider.slug}`}
      aria-label={`${provider.display_name} integration settings`}
      aria-current={active ? "page" : undefined}
      className={cls(ROW_BASE, active && ROW_ACTIVE)}
    >
      <span className="w-[18px] h-[18px] flex items-center justify-center flex-shrink-0">
        <ConnectorIcon slug={provider.slug} label={provider.display_name} />
      </span>
      <span className={cls(NAME_SLOT, "text-text-0")}>
        {provider.display_name}
      </span>
      <span
        className={cls(
          "w-1.5 h-1.5 rounded-full flex-shrink-0",
          dotClass,
        )}
        aria-hidden="true"
      />
    </Link>
  );
}
