// Goofy popovers, menu items, separators, hover toolbars, and tooltips.
//
// All of these are pure presentation components — positioning + open
// state are left to the caller (use Radix Popover, Floating UI, or your
// own anchor logic and drop these in as children). The components don't
// hard-code z-index either; wrap them as needed.

import {
  forwardRef,
  type HTMLAttributes,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import { cn } from "../../lib/cn";
import { GlyphSlot, type IconName } from "./GIcons";

// `<div role="menuitem">` doesn't get Space/Enter → click for free —
// the browser only fires synthetic click on real <button>. Synthesise
// that activation, then forward to any caller-supplied onKeyDown so
// keyboard users + screen-reader users can pick menu items via the
// keyboard the same way they would a button.
function menuKeyActivation(
  onClick: ((e: React.MouseEvent<HTMLDivElement>) => void) | undefined,
  onKeyDown: ((e: KeyboardEvent<HTMLDivElement>) => void) | undefined,
) {
  return (e: KeyboardEvent<HTMLDivElement>) => {
    if (onKeyDown) onKeyDown(e);
    if (e.defaultPrevented) return;
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onClick?.(e as unknown as React.MouseEvent<HTMLDivElement>);
    }
  };
}

// ── Popover surface ─────────────────────────────────────────────────────

const POPOVER_BASE =
  "border-2 border-ink rounded-[12px] shadow-ink-2 bg-bg-1 p-1.5 min-w-[190px]";

export const GPopover = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  function GPopover({ className, children, ...rest }, ref) {
    return (
      <div
        ref={ref}
        role="menu"
        className={cn(POPOVER_BASE, className)}
        {...rest}
      >
        {children}
      </div>
    );
  },
);

// ── Menu item ───────────────────────────────────────────────────────────

// 9 px corner matches `GListItem` + `GDoc` so all row-shaped molecules
// read as one family. Hover changes only the background — `translate-x`
// was removed because it read as a juddery sideways nudge when scanning
// a popover. Focus-visible ring uses the same AI grape token.
//
// `motion-safe:hover:animate-mini-wiggle` adds a single-shot ±1.5° tilt
// on hover-enter for that goofy "this is clickable" cue. The variant
// honours OS-level prefers-reduced-motion automatically.
const MENU_ITEM_BASE =
  "flex items-center gap-[9px] py-1.5 px-2.5 rounded-[9px] text-text-1 text-[13px] cursor-pointer " +
  "transition-colors duration-[100ms] hover:bg-bg-3 motion-safe:hover:animate-mini-wiggle " +
  "outline-none focus-visible:ring-2 focus-visible:ring-ai focus-visible:ring-offset-1 focus-visible:ring-offset-bg-1";

const MENU_ITEM_AI = "hover:bg-ai-bg hover:text-ai-deep [&_.gx-icon]:hover:text-ai";
const MENU_ITEM_DANGER = "text-danger";

export interface GMenuItemProps extends HTMLAttributes<HTMLDivElement> {
  icon?: IconName;
  /** AI variant — hover tints the row grape. */
  ai?: boolean;
  /** Danger variant — red text. */
  danger?: boolean;
  /** Keyboard shortcut hint at the row's end. */
  kbd?: ReactNode;
}

export const GMenuItem = forwardRef<HTMLDivElement, GMenuItemProps>(
  function GMenuItem(
    {
      icon,
      ai = false,
      danger = false,
      kbd,
      className,
      children,
      onClick,
      onKeyDown,
      ...rest
    },
    ref,
  ) {
    return (
      <div
        ref={ref}
        role="menuitem"
        tabIndex={0}
        onClick={onClick}
        onKeyDown={menuKeyActivation(onClick, onKeyDown)}
        className={cn(
          MENU_ITEM_BASE,
          ai && MENU_ITEM_AI,
          danger && MENU_ITEM_DANGER,
          className,
        )}
        {...rest}
      >
        {icon ? (
          <span className="gx-icon w-4 grid place-items-center text-text-3">
            <GlyphSlot name={icon} size={15} />
          </span>
        ) : null}
        <span className="flex-1">{children}</span>
        {kbd ? (
          <kbd className="font-mono text-[10px] text-text-3">{kbd}</kbd>
        ) : null}
      </div>
    );
  },
);

/** Visual separator between menu groups — a dashed border in ink. */
export function GMenuSep() {
  return <div className="h-0 border-t-2 border-dashed border-border-soft my-1.5 mx-1" />;
}

// ── Floating hover toolbar ──────────────────────────────────────────────

export interface GToolbarAction {
  icon: IconName;
  title?: string;
  /** Tint the icon button with the AI hover state. */
  ai?: boolean;
  onClick?: () => void;
}

export interface GToolbarProps extends HTMLAttributes<HTMLDivElement> {
  actions: GToolbarAction[];
}

export const GToolbar = forwardRef<HTMLDivElement, GToolbarProps>(function GToolbar(
  { actions, className, ...rest },
  ref,
) {
  return (
    <div
      ref={ref}
      role="toolbar"
      className={cn(
        "inline-flex gap-0.5 p-0.5 border-2 border-ink rounded-[10px] shadow-ink-1 bg-bg-1",
        className,
      )}
      {...rest}
    >
      {actions.map((a, i) => (
        <button
          key={i}
          type="button"
          title={a.title}
          aria-label={a.title}
          onClick={a.onClick}
          className={cn(
            "w-7 h-7 grid place-items-center rounded-md text-text-2 transition-[background-color,color,transform] duration-[100ms]",
            // AI variant takes hover precedence over the default tints
            // by being appended later — same-specificity selectors fall
            // back to source order in CSS, so no `!important` needed.
            a.ai
              ? "hover:bg-ai-bg hover:text-ai hover:rotate-[6deg]"
              : "hover:bg-bg-3 hover:text-text-0 hover:rotate-[6deg]",
          )}
        >
          <GlyphSlot name={a.icon} size={15} />
        </button>
      ))}
    </div>
  );
});

// ── Tooltip / sticker note ──────────────────────────────────────────────

export interface GTooltipProps extends HTMLAttributes<HTMLSpanElement> {
  children: ReactNode;
}

/**
 * Self-contained tooltip surface — black ink fill, cream paper text,
 * sticker shadow. Positioning is the caller's responsibility.
 *
 * Accessibility: this component renders with `role="tooltip"` but does
 * not auto-associate with its trigger. Callers must give the tooltip
 * an `id` and reference it from the trigger via `aria-describedby`
 * (or `aria-labelledby` if the tooltip is the trigger's only accessible
 * name) — e.g.:
 *
 * ```tsx
 * <button aria-describedby="save-tip">Save</button>
 * <GTooltip id="save-tip">Saves the current draft (⌘S)</GTooltip>
 * ```
 */
export function GTooltip({ className, children, ...rest }: GTooltipProps) {
  return (
    <span
      role="tooltip"
      className={cn(
        "inline-block px-3 py-1.5 border-2 border-ink rounded-[9px] shadow-ink-1 bg-ink text-bg-1 text-[12px] font-semibold",
        className,
      )}
      {...rest}
    >
      {children}
    </span>
  );
}
