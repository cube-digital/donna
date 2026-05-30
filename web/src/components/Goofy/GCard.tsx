// Goofy cards.
//
//   <GCard/>   plain sticker card with optional title + sub + AI tint
//   <GStat/>   tall numeric stat card — display value over a small label

import { forwardRef, type HTMLAttributes, type ReactNode } from "react";

import { cn } from "../../lib/cn";

// Cards are large surfaces, not stickers. We deliberately drop the
// `gx-wiggle-target` class here — the existing press-down `hover:` state
// (translate + shadow swap) already animates the whole card cleanly, and
// adding the wiggle keyframes on top fought the transition on `transform`,
// which made the description text appear to drift out of sync with the
// card edge. Inner stickers (avatars, chips, badges) still wiggle.
const CARD_BASE =
  "border-2 border-ink rounded-[12px] shadow-ink-1 bg-bg-1 px-4 py-3.5 " +
  "transition-[transform,box-shadow] duration-[140ms] ease-spring";

// Pure vertical lift on hover — the design source's diagonal shift read
// as a juddery sideways nudge when scanning a list of cards. The +1 px
// shadow growth still cues "lifted off the page" without any x-motion.
const CARD_HOVER =
  "hover:-translate-y-px hover:shadow-ink-4 cursor-pointer";

const CARD_AI =
  "bg-ai-bg border-ai shadow-[2px_2px_0_var(--ai)]";

export interface GCardProps
  extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  /** AI-tinted variant: grape border, soft grape fill, grape shadow. */
  ai?: boolean;
  /** Enable the spring-press hover state (use for tappable cards). */
  hover?: boolean;
  /** Card title — accepts any node so it can include icons or chips. */
  title?: ReactNode;
  /** Subdued line under the title. */
  sub?: ReactNode;
}

export const GCard = forwardRef<HTMLDivElement, GCardProps>(function GCard(
  { ai = false, hover = false, title, sub, className, children, onClick, ...rest },
  ref,
) {
  // When the card is interactive (`hover` + `onClick`), upgrade the
  // semantic to `role="button"` + add Space/Enter keyboard activation
  // so it isn't a click-only target. Plain non-interactive cards stay
  // as a bare <div>.
  const interactive = hover && typeof onClick === "function";
  return (
    <div
      ref={ref}
      role={interactive ? "button" : undefined}
      tabIndex={interactive ? 0 : undefined}
      onClick={onClick}
      onKeyDown={
        interactive
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onClick?.(e as unknown as React.MouseEvent<HTMLDivElement>);
              }
            }
          : undefined
      }
      className={cn(CARD_BASE, ai && CARD_AI, hover && CARD_HOVER, className)}
      {...rest}
    >
      {title ? (
        <div className="font-display font-semibold text-text-0 text-[15px]">
          {title}
        </div>
      ) : null}
      {sub ? (
        <div className="text-text-2 text-[12.5px] mt-[3px] leading-[1.5]">
          {sub}
        </div>
      ) : null}
      {children}
    </div>
  );
});

// ── Stat ───────────────────────────────────────────────────────────────

export interface GStatProps extends HTMLAttributes<HTMLDivElement> {
  value: ReactNode;
  label: ReactNode;
}

/**
 * Stat card built on top of GCard with two stacked spans. Numbers
 * render in Fredoka so they read as display type, not body copy.
 *
 * Stat cards don't share `GCard`'s -translate-y press-down (their job
 * is to be glanced at, not pressed), so they're free to wear a
 * single-shot ±1.5° wiggle on hover for the goofy "I'm a sticker"
 * cue without fighting any other transform. `motion-safe:` gates the
 * tilt behind OS-level prefers-reduced-motion.
 */
export const GStat = forwardRef<HTMLDivElement, GStatProps>(function GStat(
  { value, label, className, ...rest },
  ref,
) {
  return (
    <div
      ref={ref}
      className={cn(
        CARD_BASE,
        "flex flex-col gap-0.5 motion-safe:hover:animate-mini-wiggle",
        className,
      )}
      {...rest}
    >
      <span className="font-display font-semibold text-[22px] text-text-0 leading-none">
        {value}
      </span>
      <span className="text-[11px] text-text-3 tracking-[0.04em] uppercase">
        {label}
      </span>
    </div>
  );
});
