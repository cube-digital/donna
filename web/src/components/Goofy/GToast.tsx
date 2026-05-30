// Toast — a sticker-card with a status-tinted left bar, title, sub,
// optional CTA row, and a close button. Pure presentation; the caller
// owns mounting + positioning + auto-dismiss timers.
//
// Status tones flip the accent stripe + icon medallion colour but keep
// the body on cream paper so the message stays legible.

import { forwardRef, type HTMLAttributes, type ReactNode } from "react";

import { cn } from "../../lib/cn";
import { GIconButton } from "./GButton";
import { GlyphSlot, type IconName } from "./GIcons";

export type GToastTone = "info" | "success" | "warn" | "danger" | "ai";

const TONE_BG: Record<GToastTone, string> = {
  info: "bg-pop-blue text-white",
  success: "bg-pop-mint text-on-bright",
  warn: "bg-warn text-on-bright",
  danger: "bg-danger text-white",
  ai: "bg-ai text-white",
};

const TONE_ICON: Record<GToastTone, IconName> = {
  info: "sparkle",
  success: "check",
  warn: "bolt",
  danger: "x",
  ai: "sparkle",
};

export interface GToastProps
  extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  tone?: GToastTone;
  /** Title line (Fredoka). */
  title: ReactNode;
  /** Subline body copy. */
  sub?: ReactNode;
  /** Optional trailing row — typically a <GButton/> or two. */
  actions?: ReactNode;
  /** Show a close × button; fires `onDismiss` when clicked. */
  onDismiss?: () => void;
  /** Replace the medallion icon with a custom node. */
  emblem?: ReactNode;
}

export const GToast = forwardRef<HTMLDivElement, GToastProps>(function GToast(
  { tone = "info", title, sub, actions, onDismiss, emblem, className, ...rest },
  ref,
) {
  return (
    <div
      ref={ref}
      role="status"
      aria-live="polite"
      className={cn(
        "flex items-start gap-3 border-2 border-ink rounded-[14px] shadow-ink-2 bg-bg-1 p-3.5 pr-2.5 min-w-[280px] max-w-[460px]",
        className,
      )}
      {...rest}
    >
      <div
        className={cn(
          "w-10 h-10 shrink-0 grid place-items-center border-2 border-ink rounded-[10px] shadow-ink-1",
          TONE_BG[tone],
        )}
      >
        {emblem ?? <GlyphSlot name={TONE_ICON[tone]} size={18} />}
      </div>
      <div className="flex-1 min-w-0 flex flex-col gap-1">
        <div className="font-display font-semibold text-[14px] text-text-0 leading-tight">
          {title}
        </div>
        {sub ? (
          <div className="text-[12.5px] text-text-2 leading-snug">{sub}</div>
        ) : null}
        {actions ? <div className="flex items-center gap-2 mt-1.5">{actions}</div> : null}
      </div>
      {onDismiss ? (
        <GIconButton
          icon="x"
          aria-label="Dismiss"
          onClick={onDismiss}
          className="!w-7 !h-7"
        />
      ) : null}
    </div>
  );
});
