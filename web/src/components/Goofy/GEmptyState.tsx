// Sticker-style empty-state — circle icon medallion + display title +
// hand-lettered sub + optional CTA. Use whenever a surface has nothing
// to show (empty channel, no notifications, no results, etc.).
//
// The icon medallion picks an accent fill from the `tone` prop. Pass
// any node as the `cta` slot — typically a `<GButton/>`.

import { forwardRef, type HTMLAttributes, type ReactNode } from "react";

import { cn } from "../../lib/cn";
import { GlyphSlot, type IconName } from "./GIcons";

export type GEmptyStateTone = "neutral" | "sun" | "mint" | "blue" | "coral" | "ai";

const TONE_BG: Record<GEmptyStateTone, string> = {
  neutral: "bg-bg-2 text-text-2",
  sun: "bg-pop-sun text-on-bright",
  mint: "bg-pop-mint text-on-bright",
  blue: "bg-pop-blue text-white",
  coral: "bg-pop-coral text-white",
  ai: "bg-ai text-white",
};

export interface GEmptyStateProps
  extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  icon?: IconName;
  /** Override the icon medallion entirely (use for emoji or custom SVG). */
  emblem?: ReactNode;
  tone?: GEmptyStateTone;
  title: ReactNode;
  /** Sub-line — renders in Caveat. Use a string for max charm. */
  sub?: ReactNode;
  /** Optional CTA — typically a `<GButton/>`. */
  cta?: ReactNode;
}

export const GEmptyState = forwardRef<HTMLDivElement, GEmptyStateProps>(
  function GEmptyState(
    {
      icon = "sparkle",
      emblem,
      tone = "neutral",
      title,
      sub,
      cta,
      className,
      ...rest
    },
    ref,
  ) {
    return (
      <div
        ref={ref}
        className={cn(
          "flex flex-col items-center text-center gap-3 py-10 px-6 max-w-[420px] mx-auto",
          className,
        )}
        {...rest}
      >
        <div
          aria-hidden="true"
          className={cn(
            "w-16 h-16 grid place-items-center rounded-2xl border-2 border-ink shadow-ink-1 text-2xl",
            TONE_BG[tone],
          )}
        >
          {emblem ?? <GlyphSlot name={icon} size={28} />}
        </div>
        <div className="font-display font-semibold text-[18px] text-text-0 leading-tight">
          {title}
        </div>
        {sub ? (
          <div className="font-hand font-bold text-[18px] text-text-2 leading-snug">
            {sub}
          </div>
        ) : null}
        {cta ? <div className="mt-1">{cta}</div> : null}
      </div>
    );
  },
);
