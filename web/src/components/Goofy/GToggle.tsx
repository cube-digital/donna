// Goofy toggles — checkbox, task check (spinner), and switch.
//
// Each is a controlled component that takes `checked`/`on` and an
// `onChange(next: boolean)`. They expose the underlying element via
// `forwardRef` so callers can integrate with form libraries.

import { forwardRef, type ButtonHTMLAttributes } from "react";

import { cn } from "../../lib/cn";
import { GlyphSlot } from "./GIcons";

// ── Checkbox ───────────────────────────────────────────────────────────

const CHECK_BASE =
  "w-[18px] h-[18px] shrink-0 inline-grid place-items-center border-2 border-ink rounded-md cursor-pointer text-transparent " +
  "bg-bg-1 transition-transform duration-[120ms] ease-spring hover:scale-105";

const CHECK_ON = "bg-ok text-white";

export interface GCheckProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "onChange"> {
  checked?: boolean;
  onChange?: (next: boolean) => void;
}

export const GCheck = forwardRef<HTMLButtonElement, GCheckProps>(function GCheck(
  { checked = false, onChange, className, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      role="checkbox"
      aria-checked={checked}
      // Inline arrow — `useCallback` here would be redundant: the click
      // handler isn't passed to a memo'd child or stored as a dependency,
      // so closure churn on each render costs nothing measurable.
      onClick={() => onChange?.(!checked)}
      className={cn(CHECK_BASE, checked && CHECK_ON, className)}
      {...rest}
    >
      {checked ? <GlyphSlot name="check" size={12} /> : null}
    </button>
  );
});

// ── Task check (round) ─────────────────────────────────────────────────

export type GTaskState = "todo" | "running" | "done";

const TASK_BASE =
  "w-[18px] h-[18px] shrink-0 inline-grid place-items-center relative border-2 border-ink rounded-full bg-bg-1 text-transparent";

const TASK_DONE = "bg-ok text-white";

export interface GTaskCheckProps {
  state?: GTaskState;
  className?: string;
}

/**
 * Round status indicator. `running` overlays a spinning arc; `done`
 * fills with the ok colour and shows a check.
 */
export function GTaskCheck({ state = "todo", className }: GTaskCheckProps) {
  return (
    <span
      className={cn(
        TASK_BASE,
        state === "done" && TASK_DONE,
        className,
      )}
      aria-label={state}
    >
      {state === "done" ? <GlyphSlot name="check" size={11} /> : null}
      {state === "running" ? (
        <span
          aria-hidden
          className="absolute inset-0.5 rounded-full border-2 border-transparent [border-top-color:var(--ai)] [border-right-color:var(--ai)] animate-spin-360"
        />
      ) : null}
    </span>
  );
}

// ── Switch ─────────────────────────────────────────────────────────────

// Switch geometry: 44 × 26 outer (2 px ink border). The knob is 18 × 18
// outer, so the available track between borders is 40 × 22 — knob
// should sit with a 2 px clearance inside the borders on every active
// side (so 4 px from the outer edge: 2 px border + 2 px clearance).
//
// Vertical uses `top-1/2 -translate-y-1/2` for centring-by-physics.
// Horizontal uses the design-source values (left: 2 / 20), which work
// because absolute-position offsets are measured from the parent's
// padding edge — i.e. inside its border.
const SWITCH_BASE =
  "w-[44px] h-[26px] shrink-0 inline-block relative border-2 border-ink rounded-full shadow-ink-1 bg-bg-2 cursor-pointer transition-colors duration-[150ms] " +
  // Replace the browser default :focus blue outline with a goofy AI ring.
  "outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-ai focus-visible:ring-offset-bg-0";

const SWITCH_ON = "bg-pop-mint";

const KNOB_BASE =
  "absolute top-1/2 -translate-y-1/2 w-[18px] h-[18px] rounded-full border-2 border-ink bg-bg-1 transition-[left] duration-[180ms] ease-spring pointer-events-none";

export interface GSwitchProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "onChange"> {
  on?: boolean;
  onChange?: (next: boolean) => void;
}

export const GSwitch = forwardRef<HTMLButtonElement, GSwitchProps>(function GSwitch(
  { on = false, onChange, className, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      role="switch"
      aria-checked={on}
      // See `GCheck` — inline arrow is intentional, no memoization needed.
      onClick={() => onChange?.(!on)}
      className={cn(SWITCH_BASE, on && SWITCH_ON, className)}
      {...rest}
    >
      <span className={cn(KNOB_BASE, on ? "left-[20px]" : "left-[2px]")} />
    </button>
  );
});
