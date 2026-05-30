// Goofy buttons — every button presses down and tilts on hover, with a
// hard "sticker" offset shadow underneath. Variants pick a crayon fill
// (coral, sun, mint, blue) or the AI grape; `ghost` strips the shadow
// for less-prominent affordances.
//
// Behaviour
// ─────────
//   - Render as a real <button> (not <div>) — extends ButtonHTMLAttributes
//   - Forwards refs so callers can imperatively focus / measure
//   - Icons are referenced by name and resolved via <GlyphSlot/>
//
// The classes below recreate `.gx-btn` and `.gx-btn-icon` from
// goofy-ui.css using Tailwind utilities + the project's CSS variables.

import { forwardRef, type ButtonHTMLAttributes } from "react";

import { cn } from "../../lib/cn";
import { GlyphSlot, type IconName } from "./GIcons";

export type GButtonVariant =
  | "default"
  | "coral"
  | "sun"
  | "mint"
  | "blue"
  | "ai"
  | "ghost";

export type GButtonSize = "sm" | "md" | "lg";

const VARIANT_CLS: Record<GButtonVariant, string> = {
  // Default = paper-coloured fill that warms to beige (bg-3) on hover so
  // "secondary" buttons read as a real interactive surface, not a flat
  // chip. The Dismiss button in toast / form patterns is just this
  // variant with no extra props.
  default: "bg-bg-1 text-text-0 hover:bg-bg-3",
  coral: "bg-pop-coral text-white",
  sun: "bg-pop-sun text-on-bright",
  mint: "bg-pop-mint text-on-bright",
  blue: "bg-pop-blue text-white",
  ai: "bg-ai text-white",
  ghost:
    "bg-transparent shadow-none border-border-soft hover:bg-bg-3 hover:shadow-ink-1",
};

const SIZE_CLS: Record<GButtonSize, string> = {
  sm: "h-[27px] px-[11px] text-[12px]",
  md: "h-[34px] px-4 text-[13px]",
  lg: "h-[42px] px-[22px] text-[15px]",
};

const BASE =
  // structure
  "inline-flex items-center gap-[7px] whitespace-nowrap font-semibold " +
  // sticker chrome
  "border-2 border-ink rounded-full shadow-ink-1 " +
  // hover-press spring
  "transition-[transform,box-shadow] duration-[120ms] ease-spring " +
  "hover:-translate-x-px hover:-translate-y-px hover:-rotate-2 hover:shadow-ink-3 " +
  "active:translate-x-0.5 active:translate-y-0.5 active:rotate-0 active:shadow-none " +
  // disabled
  "disabled:opacity-50 disabled:pointer-events-none";

export interface GButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Crayon fill (or `ghost` for a no-shadow variant). */
  variant?: GButtonVariant;
  size?: GButtonSize;
  /** Optional leading icon by name. */
  icon?: IconName;
  /** Optional trailing icon by name. */
  iconRight?: IconName;
}

/**
 * Pill-shaped sticker button — chunky 2 px ink border, hard offset
 * shadow, springy hover-press.
 */
export const GButton = forwardRef<HTMLButtonElement, GButtonProps>(
  function GButton(
    { variant = "default", size = "md", icon, iconRight, className, children, type, ...rest },
    ref,
  ) {
    return (
      <button
        ref={ref}
        type={type ?? "button"}
        className={cn(BASE, VARIANT_CLS[variant], SIZE_CLS[size], className)}
        {...rest}
      >
        {icon ? <GlyphSlot name={icon} size={15} /> : null}
        {children}
        {iconRight ? <GlyphSlot name={iconRight} size={15} /> : null}
      </button>
    );
  },
);

// ── Icon button ─────────────────────────────────────────────────────────

const ICON_BTN_BASE =
  "w-[34px] h-[34px] grid place-items-center rounded-[9px] text-text-2 " +
  "transition-[transform,background,color] duration-[140ms] ease-out " +
  "hover:bg-bg-3 hover:text-text-0 hover:rotate-[8deg] " +
  "active:translate-x-0.5 active:translate-y-0.5";

const ICON_BTN_OUTLINED =
  "border-2 border-ink shadow-ink-1 text-text-0 " +
  "hover:-translate-x-px hover:-translate-y-px hover:rotate-[6deg] hover:shadow-ink-3 " +
  "active:translate-x-0.5 active:translate-y-0.5 active:shadow-none";

export interface GIconButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon: IconName;
  /** If set, the button gets a chunky ink border + sticker shadow. */
  outlined?: boolean;
}

export const GIconButton = forwardRef<HTMLButtonElement, GIconButtonProps>(
  function GIconButton({ icon, outlined = false, className, type, ...rest }, ref) {
    return (
      <button
        ref={ref}
        type={type ?? "button"}
        className={cn(ICON_BTN_BASE, outlined && ICON_BTN_OUTLINED, className)}
        {...rest}
      >
        <GlyphSlot name={icon} size={17} />
      </button>
    );
  },
);
