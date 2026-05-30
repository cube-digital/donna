// Goofy lists.
//
//   <GList/>       flex column with tight gap
//   <GListItem/>   one row — `hash` for channel-style #, `dot` for status,
//                  `badge` slot on the right; active rows become a
//                  sticker (sun bg + ink border + shadow)
//   <GDoc/>        document row — icon + name + meta, scoots right on hover

import { forwardRef, type HTMLAttributes, type ReactNode } from "react";

import { cn } from "../../lib/cn";
import { GlyphSlot, type IconName } from "./GIcons";

export type GListDot = "online" | "ai" | "muted";

const DOT_CLS: Record<GListDot, string> = {
  online: "bg-ok",
  ai: "bg-ai shadow-[0_0_0_2px_var(--ai-glow)]",
  muted: "bg-text-3",
};

// ── List ───────────────────────────────────────────────────────────────

export const GList = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  function GList({ className, children, ...rest }, ref) {
    return (
      <div ref={ref} className={cn("flex flex-col gap-0.5", className)} {...rest}>
        {children}
      </div>
    );
  },
);

// ── List item ──────────────────────────────────────────────────────────

// `motion-safe:hover:animate-mini-wiggle` — single-shot ±1.5° tilt on
// hover-enter, gated by OS-level prefers-reduced-motion. Same affordance
// as `GMenuItem` so list rows and menu items feel like one family.
//
// `leading-4` pins the text line-height to 16 px so it matches the
// 16 × 16 icon slot. Without that, browser-default line-height (~1.5)
// makes the text box ~19.5 px tall, larger than the icon box, and
// `items-center` then centres the icon on a baseline that's optically
// above the text mid-line — the rows look 1-2 px off. Matching the
// flex children's heights keeps everything optically square.
const ITEM_BASE =
  "flex items-center gap-[9px] py-1.5 px-[9px] rounded-[9px] text-text-1 text-[13px] leading-4 cursor-pointer " +
  "transition-colors duration-[100ms] hover:bg-bg-3 motion-safe:hover:animate-mini-wiggle " +
  "outline-none focus-visible:ring-2 focus-visible:ring-ai focus-visible:ring-offset-1 focus-visible:ring-offset-bg-1";

// sun bg + ink border + sticker shadow = "this row is the chosen sticker"
// The padding shrinks by 2 px in each direction to compensate for the
// `border-2` (the inactive row has no border), keeping total geometry
// pixel-stable when toggling active. Appended after `ITEM_BASE` in the
// `cn(…)` chain in `GListItem`, so the smaller padding wins by
// source order — no `!important` needed.
const ITEM_ACTIVE =
  "bg-pop-sun text-on-bright border-2 border-ink shadow-ink-1 font-semibold py-1 px-[7px]";

export interface GListItemProps extends HTMLAttributes<HTMLDivElement> {
  active?: boolean;
  /**
   * Leading content slot — typically an icon (`<GlyphSlot/>`) or a small
   * avatar. Rendered in a 16 × 16 flex cell with `place-items-center`,
   * so the icon's optical centre lines up with the text's centre when
   * the row uses the default `leading-4` text height. Use this instead
   * of nesting an inline-flex inside `children` so every row's icon
   * column sits at the same x-position regardless of which side slots
   * (hash / dot / badge) are present.
   */
  icon?: ReactNode;
  /** Leading hash character — typically `#` for channels. */
  hash?: ReactNode;
  /** Leading status dot. */
  dot?: GListDot;
  /** Trailing element — usually a `<GBadge/>`. */
  badge?: ReactNode;
}

export const GListItem = forwardRef<HTMLDivElement, GListItemProps>(
  function GListItem(
    { active = false, icon, hash, dot, badge, className, children, ...rest },
    ref,
  ) {
    return (
      <div
        ref={ref}
        role="button"
        tabIndex={0}
        aria-current={active ? "true" : undefined}
        className={cn(ITEM_BASE, active && ITEM_ACTIVE, className)}
        {...rest}
      >
        {icon ? (
          <span
            className={cn(
              "w-4 h-4 grid place-items-center shrink-0",
              active ? "text-on-bright" : "text-text-3",
            )}
          >
            {icon}
          </span>
        ) : null}
        {hash ? (
          <span
            className={cn(
              "w-3.5 text-center shrink-0",
              active ? "text-on-bright" : "text-text-3",
            )}
          >
            {hash}
          </span>
        ) : null}
        {dot ? (
          <span
            className={cn("w-[7px] h-[7px] rounded-full shrink-0", DOT_CLS[dot])}
          />
        ) : null}
        <span className="flex-1 min-w-0 truncate">{children}</span>
        {badge}
      </div>
    );
  },
);

// ── Doc row ────────────────────────────────────────────────────────────

// Matches `GListItem`'s 9 px radius so a `GDoc` sitting next to a list
// item reads as the same family. Hover changes only the background —
// the previous `translate-x-0.5` looked juddery when scanning a list.
// Focus outline is replaced with a goofy AI-grape ring at the same 9 px corner.
// `motion-safe:hover:animate-mini-wiggle` adds the same single-shot tilt
// affordance as `GListItem` / `GMenuItem`.
const DOC_BASE =
  "flex items-center gap-[9px] py-1.5 px-[9px] rounded-[9px] text-text-1 text-[12.5px] cursor-pointer " +
  "transition-colors duration-[100ms] hover:bg-bg-3 motion-safe:hover:animate-mini-wiggle " +
  "outline-none focus-visible:ring-2 focus-visible:ring-ai focus-visible:ring-offset-1 focus-visible:ring-offset-bg-1";

export interface GDocProps extends HTMLAttributes<HTMLDivElement> {
  icon?: IconName;
  name: ReactNode;
  meta?: ReactNode;
}

/**
 * Document / link row. Renders an icon, a truncated name, and an
 * optional monospace meta string at the end.
 */
export const GDoc = forwardRef<HTMLDivElement, GDocProps>(function GDoc(
  { icon = "doc", name, meta, className, ...rest },
  ref,
) {
  return (
    <div
      ref={ref}
      role="button"
      tabIndex={0}
      className={cn(DOC_BASE, className)}
      {...rest}
    >
      <span className="grid place-items-center text-text-3">
        <GlyphSlot name={icon} size={15} />
      </span>
      <span className="flex-1 min-w-0 truncate">{name}</span>
      {meta != null ? (
        <span className="text-text-3 text-[11px] font-mono">{meta}</span>
      ) : null}
    </div>
  );
});
