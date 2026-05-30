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

import { useLocation, useNavigate } from "react-router-dom";

import { cn } from "../../lib/cn";
import { useAuth } from "../../state/auth";
import { useWorkspace } from "../../state/workspace";
import { GIconButton, type IconName } from "../Goofy";

type NavKey = "workspace" | "dms" | "personal" | "search" | "files";

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
  { key: "files", label: "Files", icon: "file" },
];

function workspaceGlyph(name: string): string {
  return (name?.trim()?.[0] ?? "C").toUpperCase();
}

function userInitials(activeWorkspaceName?: string): string {
  // Until a /me endpoint is wired here we don't have an email/name to
  // initialise from. Fall back to the active workspace's first letter so
  // the pill renders with something rather than blank.
  return workspaceGlyph(activeWorkspaceName ?? "");
}

// Workspace + user sticker — sun-yellow fill, chunky ink border, hard
// offset shadow, Fredoka heavy weight. The active workspace also wears
// a 3 px ink "rail" pseudo-element 10 px outside its left edge.
const STICKER_PILL =
  "w-10 h-10 grid place-items-center border-2 border-ink rounded-[12px] " +
  "shadow-ink-2 bg-pop-sun text-on-bright font-display font-bold text-[15px] " +
  "transition-[transform,box-shadow] duration-[120ms] ease-spring " +
  "hover:-translate-x-px hover:-translate-y-px hover:-rotate-2 hover:shadow-ink-3 " +
  "active:translate-x-0.5 active:translate-y-0.5 active:rotate-0 active:shadow-none";

const STICKER_ACTIVE_RAIL =
  "relative before:content-[''] before:absolute before:-left-[10px] " +
  "before:top-1.5 before:bottom-1.5 before:w-[3px] before:rounded-full before:bg-ink";

export default function WsRail() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { workspaces, activeId } = useWorkspace();
  const signOut = useAuth((s) => s.signOut);

  const active = workspaces.find((w) => w.id === activeId);

  return (
    <nav
      className="[grid-area:rail] flex flex-col items-center gap-1.5 py-2.5 bg-bg-0 border-r border-border-soft"
      aria-label="Workspaces and global nav"
    >
      <button
        type="button"
        className={cn(STICKER_PILL, STICKER_ACTIVE_RAIL)}
        title={active?.name ?? "Workspace"}
        aria-label={`${active?.name ?? "Workspace"} (active workspace)`}
        aria-current="true"
      >
        {workspaceGlyph(active?.name ?? "C")}
      </button>
      <GIconButton
        icon="plus"
        outlined
        size="lg"
        title="Add workspace"
        aria-label="Add workspace"
      />

      <div
        className="w-7 border-t-2 border-dashed border-ink/40 my-1"
        aria-hidden="true"
      />

      {NAV.map((item) => {
        const isActive = item.matcher ? item.matcher(pathname) : false;
        const isAi = !!item.ai;
        // State-driven hover/active tints — these are colour mutations
        // on top of the base `size="lg"` pill, so they remain inline.
        // The geometry overrides (`!w-10 !h-10 !rounded-[12px]`) are
        // gone — `size="lg"` handles them.
        const stateCls = cn(
          isAi && "text-ai hover:text-ai",
          isAi && isActive && "bg-ai-bg text-ai shadow-[inset_0_0_0_2px_var(--ai-glow)]",
          !isAi && isActive && "bg-bg-3 text-text-0",
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
        title="Toggle theme"
        aria-label="Toggle theme"
      />
      <button
        type="button"
        className={cn(STICKER_PILL, "text-[12px]")}
        title="Sign out"
        aria-label="Sign out"
        onClick={() => signOut()}
      >
        {userInitials(active?.name)}
      </button>
    </nav>
  );
}
