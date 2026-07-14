// Far-left 56px column — workspace pills + global nav + theme/user pill.
// Ported from donnaai/project/sidebar.jsx:144-180, then re-skinned onto
// the Goofy library: workspace + user pills are chunky sun-yellow ink
// stickers, nav buttons are square `<GIconButton/>` stickers, the
// separator is a dashed ink rule.
//
// One-pill-per-workspace is the *design intent* but we only show the
// active workspace here for v1 (no inter-workspace switcher inside the
// rail — that lives on the WorkspacePicker until multi-workspace use
// is real). The `+` pill is a non-functional stub so the visual rhythm
// matches the design.

import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { cn } from "../../lib/cn";
import { useMe } from "../../state/me";
import { useProfilePanel } from "../../state/profilePanel";
import { useWorkspace } from "../../state/workspace";
import { GIconButton, type IconName } from "../Goofy";
import { UserAvatar } from "./ProfilePanel";

type NavKey = "workspace" | "dms" | "personal" | "search" | "cortex";

interface NavItem {
  key: NavKey;
  label: string;
  icon: IconName;
  ai?: boolean;
  href?: string;
  matcher?: (pathname: string) => boolean;
}

const NAV: NavItem[] = [
  {
    key: "workspace",
    label: "Workspace",
    icon: "home",
    href: "/channels",
    matcher: (p) => p === "/" || p.startsWith("/channels"),
  },
  { key: "dms", label: "Direct messages", icon: "msg" },
  {
    key: "personal",
    label: "Personal AI",
    icon: "sparkle",
    ai: true,
    href: "/personal",
    matcher: (p) => p.startsWith("/personal"),
  },
  {
    key: "search",
    label: "Search",
    icon: "search",
    href: "/search",
    matcher: (p) => p.startsWith("/search"),
  },
  {
    key: "cortex",
    label: "Cortex memory",
    icon: "brain",
    href: "/cortex",
    matcher: (p) => p.startsWith("/cortex") || p.startsWith("/files"),
  },
];

function workspaceGlyph(name: string): string {
  return (name?.trim()?.[0] ?? "C").toUpperCase();
}

// Workspace + user sticker — sun-yellow fill, chunky ink border, hard
// offset shadow, Fredoka heavy weight. The active workspace also wears
// a 3 px ink "rail" pseudo-element 10 px outside its left edge.
const STICKER_PILL =
  "w-[38px] h-[38px] grid place-items-center border-2 border-ink rounded-[12px] " +
  "bg-pop-sun text-on-bright font-bold text-[15px] " +
  "transition-transform duration-[120ms] active:scale-95";

export default function WsRail() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { workspaces, activeId } = useWorkspace();
  const me = useMe((s) => s.me);
  const loadMe = useMe((s) => s.load);
  const openPanel = useProfilePanel((s) => s.openPanel);

  useEffect(() => {
    void loadMe();
  }, [loadMe]);

  const active = workspaces.find((w) => w.id === activeId);

  return (
    <nav
      className="h-full flex flex-col items-center gap-1.5 py-2.5 bg-bg-2 border-r border-border-soft"
      aria-label="Workspaces and global nav"
    >
      <button
        type="button"
        className={STICKER_PILL}
        title={active?.name ?? "Workspace"}
        aria-label={`${active?.name ?? "Workspace"} (active workspace)`}
        aria-current="true"
      >
        {workspaceGlyph(active?.name ?? "C")}
      </button>
      <button
        type="button"
        className="w-[38px] h-[38px] grid place-items-center border-2 border-ink rounded-[12px] bg-bg-1 text-text-2 transition-transform active:scale-95"
        title="Add workspace"
        aria-label="Add workspace"
      >
        <i className="ti ti-plus text-[17px]" aria-hidden />
      </button>

      {NAV.map((item) => {
        const isActive = item.matcher ? item.matcher(pathname) : false;
        const isAi = !!item.ai;
        // State-driven hover/active tints — these are colour mutations
        // on top of the base `size="lg"` pill, so they remain inline.
        // The geometry overrides (`!w-10 !h-10 !rounded-[12px]`) are
        // gone — `size="lg"` handles them.
        const stateCls = cn(
          "!w-9 !h-9 !rounded-[10px] text-text-3",
          isAi && "text-ai hover:text-ai",
          isActive && "bg-ai-bg text-ai",
        );
        return (
          <GIconButton
            key={item.key}
            icon={item.icon}
            size="lg"
            className={stateCls}
            title={item.label}
            aria-label={item.label}
            aria-current={isActive ? "page" : undefined}
            onClick={() => {
              if (item.href) navigate(item.href);
            }}
          />
        );
      })}

      <div className="flex-1" />

      <GIconButton
        icon="sun"
        size="lg"
        className="!w-9 !h-9 !rounded-[10px] text-text-3"
        title="Toggle theme"
        aria-label="Toggle theme"
      />
      <button
        type="button"
        className="rounded-[12px] transition-transform duration-[120ms] active:scale-95 outline-none focus-visible:ring-2 focus-visible:ring-ai"
        title="Your profile"
        aria-label="Open your profile"
        onClick={() => openPanel()}
      >
        <UserAvatar
          pictureUrl={me?.picture_url}
          name={me?.full_name || me?.email || active?.name || "You"}
          sizePx={38}
          isAway={!!me?.is_away}
          showDot
        />
      </button>
    </nav>
  );
}
