// Goofy chips, tags, badges, and role chips. The shared visual idea: a
// chunky ink border + (for chips) a sticker offset shadow that springs
// on hover. Tags are flat (no shadow); badges are small count pills;
// role-chips are tiny tilted "AGENT"/"AI" stamps.

import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";

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

export const GChip = forwardRef<HTMLButtonElement, GChipProps>(function GChip(
  { variant = "default", active = false, onRemove, className, children, type, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type ?? "button"}
      aria-pressed={active}
      className={cn(
        CHIP_BASE,
        // active wins over variant
        active ? CHIP_ACTIVE : VARIANT_CLS[variant],
        className,
      )}
      {...rest}
    >
      {children}
      {onRemove ? (
        <span
          role="button"
          aria-label="Remove"
          tabIndex={0}
          className="grid place-items-center w-3.5 h-3.5 opacity-70 hover:opacity-100"
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.stopPropagation();
              e.preventDefault();
              onRemove();
            }
          }}
        >
          <GlyphSlot name="x" size={11} />
        </span>
      ) : null}
    </button>
  );
});

// ── Tag ─────────────────────────────────────────────────────────────────

export type GTagVariant = "default" | "mint" | "sun";

const TAG_VARIANTS: Record<GTagVariant, string> = {
  default: "bg-bg-2 text-text-2",
  mint: "bg-pop-mint text-on-bright",
  sun: "bg-pop-sun text-on-bright",
};

export interface GTagProps {
  variant?: GTagVariant;
  /** Optional trailing count chip. */
  count?: number | string;
  children: ReactNode;
  className?: string;
}

/**
 * Small inline tag with a 1.5 px ink border but no offset shadow.
 * Renders a `<span/>` so it composes inside paragraphs and list rows.
 */
export function GTag({ variant = "default", count, children, className }: GTagProps) {
  return (
    <span
      className={cn(
        "gx-wiggle-target inline-flex items-center gap-1.5 px-[9px] py-0.5 border-[1.5px] border-ink rounded-full text-[11.5px] font-medium",
        TAG_VARIANTS[variant],
        className,
      )}
    >
      {children}
      {count != null ? <span className="font-mono opacity-70">{count}</span> : null}
    </span>
  );
}

// ── Badge ───────────────────────────────────────────────────────────────

export interface GBadgeProps {
  /** Mention variant — coral fill, ink border, sticker shadow, slight tilt. */
  mention?: boolean;
  children: ReactNode;
  className?: string;
}

/**
 * Small numeric badge. Mention variant ("3 unread @-mentions") tilts
 * and stamps with a hard shadow to draw the eye.
 */
export function GBadge({ mention = false, children, className }: GBadgeProps) {
  return (
    <span
      className={cn(
        "gx-wiggle-target inline-grid place-items-center min-w-[18px] h-[18px] px-1.5 rounded-full text-[10px] font-bold tabular-nums",
        mention
          ? "bg-pop-coral text-white border-[1.5px] border-ink shadow-[1.5px_1.5px_0_var(--ink)] -rotate-6"
          : "bg-ink text-bg-1",
        className,
      )}
    >
      {children}
    </span>
  );
}

// ── Role chip ──────────────────────────────────────────────────────────

export interface GRoleChipProps {
  children?: ReactNode;
  className?: string;
}

/**
 * Tilted micro-label, used inline next to a name to mark an agent.
 */
export function GRoleChip({ children = "AI", className }: GRoleChipProps) {
  return (
    <span
      className={cn(
        "gx-wiggle-target inline-block px-1.5 py-0.5 border-[1.5px] border-ink rounded-[5px] shadow-[1.5px_1.5px_0_var(--ink)] bg-ai text-white text-[9.5px] font-semibold tracking-[0.05em] uppercase -rotate-[4deg]",
        className,
      )}
    >
      {children}
    </span>
  );
}
