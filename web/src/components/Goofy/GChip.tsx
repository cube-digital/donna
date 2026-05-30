// Goofy chips, tags, badges, and role chips. The shared visual idea: a
// chunky ink border + (for chips) a sticker offset shadow that springs
// on hover. Tags are flat (no shadow); badges are small count pills;
// role-chips are tiny tilted "AGENT"/"AI" stamps.

import {
  forwardRef,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type ReactNode,
} from "react";

import { cn } from "../../lib/cn";
import { GlyphSlot } from "./GIcons";

// ── Chip ────────────────────────────────────────────────────────────────

export type GChipVariant =
  | "default"
  | "mint"
  | "sun"
  | "blue"
  | "coral"
  | "ai";

const CHIP_BASE =
  "gx-wiggle-target inline-flex items-center gap-1.5 h-7 px-3 " +
  "border-2 border-ink rounded-full shadow-ink-1 " +
  "text-[12.5px] font-medium " +
  "transition-[transform,box-shadow] duration-[120ms] ease-spring " +
  "hover:-translate-x-px hover:-translate-y-px hover:shadow-ink-3";

// Resting fill per variant. `active` overrides to sun-yellow regardless
// (chips are typically filterable controls — the active state is the
// "applied filter" signal and shouldn't depend on the resting tint).
const VARIANT_CLS: Record<GChipVariant, string> = {
  default: "bg-bg-1 text-text-1",
  mint: "bg-pop-mint text-on-bright",
  sun: "bg-pop-sun text-on-bright",
  blue: "bg-pop-blue text-white",
  coral: "bg-pop-coral text-white",
  ai: "bg-ai text-white",
};

const CHIP_ACTIVE = "bg-pop-sun text-on-bright";

export interface GChipProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Resting colour family. Default is paper-coloured. */
  variant?: GChipVariant;
  /** Filter-active state — overrides `variant` to sun-yellow. */
  active?: boolean;
  /** Show an `×` affordance and call this when clicked. */
  onRemove?: () => void;
}

/**
 * Sticker pill. Defaults to a single `<button/>` so it composes into
 * forms / toolbars naturally.
 *
 * When `onRemove` is set, the chip splits into a `<span role="group"/>`
 * wrapper around two independently-focusable `<button/>`s — one for the
 * chip body, one for the `×`. We deliberately avoid nesting interactive
 * elements (the previous shape rendered a `role="button"` X inside the
 * outer `<button>`), which is invalid HTML and produced inconsistent
 * keyboard / screen-reader behaviour. The forwarded `ref` always lands
 * on the body button so form-library refs keep working unchanged.
 */
export const GChip = forwardRef<HTMLButtonElement, GChipProps>(function GChip(
  { variant = "default", active = false, onRemove, className, children, type, ...rest },
  ref,
) {
  const variantCls = active ? CHIP_ACTIVE : VARIANT_CLS[variant];

  if (!onRemove) {
    return (
      <button
        ref={ref}
        type={type ?? "button"}
        aria-pressed={active}
        className={cn(CHIP_BASE, variantCls, className)}
        {...rest}
      >
        {children}
      </button>
    );
  }

  return (
    <span
      role="group"
      className={cn(
        CHIP_BASE,
        variantCls,
        // Re-tighten the right padding — the × button supplies its own
        // visual breathing room so we don't want the wrapper's default.
        "pr-1.5",
        className,
      )}
    >
      <button
        ref={ref}
        type={type ?? "button"}
        aria-pressed={active}
        className="inline-flex items-center gap-1.5 outline-none focus-visible:underline cursor-pointer"
        {...rest}
      >
        {children}
      </button>
      <button
        type="button"
        aria-label="Remove"
        onClick={(e) => {
          e.stopPropagation();
          onRemove();
        }}
        className={cn(
          "grid place-items-center w-4 h-4 ml-1.5 rounded-full opacity-70 cursor-pointer",
          "hover:opacity-100",
          "outline-none focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ai",
        )}
      >
        <GlyphSlot name="x" size={11} />
      </button>
    </span>
  );
});

// ── Tag ─────────────────────────────────────────────────────────────────

export type GTagVariant = "default" | "mint" | "sun";

const TAG_VARIANTS: Record<GTagVariant, string> = {
  default: "bg-bg-2 text-text-2",
  mint: "bg-pop-mint text-on-bright",
  sun: "bg-pop-sun text-on-bright",
};

export interface GTagProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: GTagVariant;
  /** Optional trailing count chip. */
  count?: number | string;
  children: ReactNode;
}

/**
 * Small inline tag with a 1.5 px ink border but no offset shadow.
 * Renders a `<span/>` so it composes inside paragraphs and list rows.
 */
export const GTag = forwardRef<HTMLSpanElement, GTagProps>(function GTag(
  { variant = "default", count, children, className, ...rest },
  ref,
) {
  return (
    <span
      ref={ref}
      className={cn(
        "gx-wiggle-target inline-flex items-center gap-1.5 px-[9px] py-0.5 border-[1.5px] border-ink rounded-full text-[11.5px] font-medium",
        TAG_VARIANTS[variant],
        className,
      )}
      {...rest}
    >
      {children}
      {count != null ? <span className="font-mono opacity-70">{count}</span> : null}
    </span>
  );
});

// ── Badge ───────────────────────────────────────────────────────────────

export interface GBadgeProps extends HTMLAttributes<HTMLSpanElement> {
  /** Mention variant — coral fill, ink border, sticker shadow, slight tilt. */
  mention?: boolean;
  children: ReactNode;
}

/**
 * Small numeric badge. Mention variant ("3 unread @-mentions") tilts
 * and stamps with a hard shadow to draw the eye.
 */
export const GBadge = forwardRef<HTMLSpanElement, GBadgeProps>(function GBadge(
  { mention = false, children, className, ...rest },
  ref,
) {
  return (
    <span
      ref={ref}
      className={cn(
        "gx-wiggle-target inline-grid place-items-center min-w-[18px] h-[18px] px-1.5 rounded-full text-[10px] font-bold tabular-nums",
        mention
          ? "bg-pop-coral text-white border-[1.5px] border-ink shadow-[1.5px_1.5px_0_var(--ink)] -rotate-6"
          : "bg-ink text-bg-1",
        className,
      )}
      {...rest}
    >
      {children}
    </span>
  );
});

// ── Role chip ──────────────────────────────────────────────────────────

export interface GRoleChipProps extends HTMLAttributes<HTMLSpanElement> {
  children?: ReactNode;
}

/**
 * Tilted micro-label, used inline next to a name to mark an agent.
 */
export const GRoleChip = forwardRef<HTMLSpanElement, GRoleChipProps>(
  function GRoleChip({ children = "AI", className, ...rest }, ref) {
    return (
      <span
        ref={ref}
        className={cn(
          "gx-wiggle-target inline-block px-1.5 py-0.5 border-[1.5px] border-ink rounded-[5px] shadow-[1.5px_1.5px_0_var(--ink)] bg-ai text-white text-[9.5px] font-semibold tracking-[0.05em] uppercase -rotate-[4deg]",
          className,
        )}
        {...rest}
      >
        {children}
      </span>
    );
  },
);
