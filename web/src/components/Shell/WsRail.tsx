// Far-left 56px column — workspace pills + global nav + theme/user pill.
// Ported from donnaai/project/sidebar.jsx:144-180.
//
// One-pill-per-workspace is the *design intent* but we only show the
// active workspace here for v1 (no inter-workspace switcher inside the
// rail — that lives on the WorkspacePicker until multi-workspace use
// is real). The `+` pill is a non-functional stub so the visual rhythm
// matches the design.

import { useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../../state/auth";
import { useWorkspace } from "../../state/workspace";
import { Ic } from "../Ui/Ic";

type NavKey = "workspace" | "dms" | "personal" | "search" | "files";

interface NavItem {
  key: NavKey;
  label: string;
  icon: keyof typeof Ic;
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

// Tailwind class fragments for the rail pill / icon variants. Kept as
// constants so the JSX stays readable.
//
// The active workspace pill carries a 3px vertical indicator bar 10px
// outside its left edge — expressed entirely as `before:` utilities below
// so we don't need a child element or a custom @layer rule.
const PILL_BASE =
  "w-9 h-9 rounded-md grid place-items-center text-[13px] font-semibold text-text-1 bg-bg-2 border border-border-soft relative";
const PILL_ACTIVE =
  "before:content-[''] before:absolute before:-left-[10px] before:top-1.5 before:bottom-1.5 before:w-[3px] before:rounded-sm before:bg-text-0";
const ICON_BASE =
  "w-9 h-9 rounded-md grid place-items-center text-text-2 hover:bg-bg-2 hover:text-text-0";
const ICON_ACTIVE = "bg-bg-3 text-text-0";
const ICON_AI = "text-ai hover:text-ai";
const ICON_AI_ACTIVE =
  "bg-ai-bg text-ai shadow-[inset_0_0_0_1px_var(--ai-glow)] hover:bg-ai-bg hover:text-ai";

function cls(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

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
        className={cls(PILL_BASE, PILL_ACTIVE)}
        title={active?.name ?? "Workspace"}
        aria-label={active?.name ?? "Workspace"}
      >
        {workspaceGlyph(active?.name ?? "C")}
      </button>
      <button
        type="button"
        className={cls(PILL_BASE, "opacity-65")}
        title="Add workspace"
        aria-label="Add workspace"
      >
        <Ic.plus />
      </button>

      <div className="w-6 h-px bg-border-soft my-1" />

      {NAV.map((item) => {
        const Icon = Ic[item.icon];
        const isActive = item.matcher ? item.matcher(pathname) : false;
        const isAi = !!item.ai;
        const className = cls(
          ICON_BASE,
          isAi && ICON_AI,
          isActive && !isAi && ICON_ACTIVE,
          isActive && isAi && ICON_AI_ACTIVE,
        );
        return (
          <button
            key={item.key}
            type="button"
            className={className}
            title={item.label}
            aria-label={item.label}
            aria-current={isActive ? "page" : undefined}
            onClick={() => {
              if (item.href) navigate(item.href);
            }}
          >
            <Icon />
          </button>
        );
      })}

      <div className="flex-1" />

      <button
        type="button"
        className={ICON_BASE}
        title="Toggle theme"
        aria-label="Toggle theme"
      >
        <Ic.sun />
      </button>
      <button
        type="button"
        className={cls(PILL_BASE, "text-[11px]")}
        title="Sign out"
        aria-label="Sign out"
        onClick={() => signOut()}
      >
        {userInitials(active?.name)}
      </button>
    </nav>
  );
}
