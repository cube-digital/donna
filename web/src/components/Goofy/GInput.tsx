// Goofy inputs.
//
//   <GInput/>   pill-shaped capsule (search bars, single-line fields)
//   <GField/>   bigger note-card surround for textarea-style composers
//
// Both use the design's focus state — the sticker shadow flips to the
// AI grape and the border darkens to AI to signal "active".

import { forwardRef, type InputHTMLAttributes, type ReactNode, type TextareaHTMLAttributes } from "react";

import { cn } from "../../lib/cn";
import { GlyphSlot, type IconName } from "./GIcons";

// ── Input ───────────────────────────────────────────────────────────────

const INPUT_SHELL =
  "flex items-center gap-[9px] h-[38px] px-[14px] " +
  "border-2 border-ink rounded-full shadow-ink-1 bg-bg-1 text-text-2 " +
  "transition-[box-shadow,border-color] duration-[120ms] " +
  "focus-within:border-ai focus-within:shadow-[3px_3px_0_var(--ai)]";

const INPUT_KBD =
  "font-mono text-[10.5px] font-semibold px-1.5 py-0.5 rounded-[5px] " +
  "border-[1.5px] border-ink bg-pop-sun text-on-bright";

export interface GInputProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "size"> {
  /** Optional leading icon (search by default). Pass `null` to omit. */
  icon?: IconName | null;
  /** Optional trailing keyboard hint, e.g. `⌘K`. */
  kbd?: ReactNode;
  /** Replace the default surround className entirely. */
  shellClassName?: string;
}

/**
 * Pill-shaped sticker input. Wraps a native `<input/>` and forwards
 * everything (incl. `ref`) so it composes with `react-hook-form` etc.
 */
export const GInput = forwardRef<HTMLInputElement, GInputProps>(function GInput(
  { icon = "search", kbd, shellClassName, className, placeholder = "Search…", type = "text", ...rest },
  ref,
) {
  return (
    <label className={cn(INPUT_SHELL, shellClassName)}>
      {icon ? (
        <span className="shrink-0 text-text-3">
          <GlyphSlot name={icon} size={16} />
        </span>
      ) : null}
      <input
        ref={ref}
        type={type}
        placeholder={placeholder}
        className={cn(
          "flex-1 min-w-0 text-text-0 text-[13.5px] placeholder:text-text-3",
          className,
        )}
        {...rest}
      />
      {kbd ? <kbd className={INPUT_KBD}>{kbd}</kbd> : null}
    </label>
  );
});

// ── Field (note card / textarea) ────────────────────────────────────────

const FIELD_BASE =
  "border-[2.5px] border-ink rounded-[14px] shadow-[3px_3px_0_var(--ink)] " +
  "bg-bg-1 px-[14px] py-3 " +
  "transition-[box-shadow,border-color] duration-[120ms] " +
  "focus-within:border-ai focus-within:shadow-[3px_3px_0_var(--ai)]";

const FIELD_AI =
  "bg-ai-bg border-ai shadow-[3px_3px_0_var(--ai)]";

export interface GFieldProps
  extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  /** Switch to the AI-tinted variant (used for "ask Donna" composer). */
  ai?: boolean;
  /** Trailing slot — typically a row of tags + send button. */
  trailing?: ReactNode;
}

/**
 * Larger "note-card" surround for composer-style fields. The inner
 * textarea has auto-sizing via `rows`; if you need true auto-grow,
 * pass a custom `style.height` from the caller.
 */
export const GField = forwardRef<HTMLTextAreaElement, GFieldProps>(function GField(
  { ai = false, trailing, className, placeholder = "Write something…", rows = 3, ...rest },
  ref,
) {
  return (
    <div className={cn(FIELD_BASE, ai && FIELD_AI, className)}>
      <textarea
        ref={ref}
        rows={rows}
        placeholder={placeholder}
        className="block w-full resize-none text-text-0 text-[13.5px] leading-[1.55] placeholder:text-text-3"
        {...rest}
      />
      {trailing}
    </div>
  );
});
