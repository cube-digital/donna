// Goofy agent-run card — the showpiece sticker.
//
// One card communicates: who's running, what they're doing, every step
// they've taken, the thought stream while in-flight, the final output,
// and what memory got touched. The grape backdrop + dashed-ink dividers
// + offset shadow in `var(--ai)` set it apart from regular cards.

import { forwardRef, type HTMLAttributes, type ReactNode } from "react";

import { cn } from "../../lib/cn";
import { GlyphSlot, type IconName } from "./GIcons";

export type GRunStepState = "todo" | "running" | "done";

export interface GRunStepData {
  icon?: IconName;
  label: ReactNode;
  /** Tiny monospace caption to the right of the label. */
  meta?: ReactNode;
  state?: GRunStepState;
}

export interface GRunProps extends HTMLAttributes<HTMLDivElement> {
  /** Hand-lettered prefix — e.g. "Donna ran". */
  label?: ReactNode;
  /** Plain-text summary after the label. */
  summary?: ReactNode;
  /** Status text shown next to the LED ("done", "thinking", "queued"). */
  status?: ReactNode;
  /** Pulse the running LED + show thought dots. */
  running?: boolean;
  /** Inline thought line while running. */
  thought?: ReactNode;
  steps?: GRunStepData[];
  /** The agent's final answer / artefact. */
  output?: ReactNode;
  /** Memory chip text (single line) — pass any node for richer chips. */
  memory?: ReactNode;
  /** Show the footer with Dismiss / Approve actions. */
  footer?: boolean | { dismissLabel?: ReactNode; approveLabel?: ReactNode };
  onDismiss?: () => void;
  onApprove?: () => void;
}

const STEP_ICON_CLS =
  "w-6 h-6 shrink-0 grid place-items-center border-[1.5px] border-ink rounded-[7px] bg-pop-mint text-on-bright";

export const GRun = forwardRef<HTMLDivElement, GRunProps>(function GRun(
  {
    label = "Agent run",
    summary,
    status = "done",
    running = false,
    thought,
    steps = [],
    output,
    memory,
    footer,
    onDismiss,
    onApprove,
    className,
    ...rest
  },
  ref,
) {
  const showFooter = footer !== false && (footer || memory || output);
  const footerOpts = typeof footer === "object" ? footer : null;

  return (
    <div
      ref={ref}
      className={cn(
        "border-[2.5px] border-ink rounded-[16px] shadow-ai-stamp run-card-bg overflow-hidden",
        className,
      )}
      {...rest}
    >
      <header className="flex items-center gap-[9px] py-2.5 px-3.5 border-b-2 border-dashed border-ink">
        <span className="font-hand font-bold text-[16px] text-ai-deep">{label}</span>
        {summary ? (
          <span className="text-[12.5px] text-text-1">{summary}</span>
        ) : null}
        <span className="flex-1" />
        <span className="flex items-center gap-1.5 text-[11.5px] text-text-2">
          <span
            className={cn(
              "w-2 h-2 rounded-full",
              running ? "bg-ai animate-led-blink" : "bg-ok",
            )}
          />
          {status}
        </span>
      </header>

      <div className="flex flex-col gap-1.5 py-2.5 px-3.5">
        {thought ? (
          <div className="flex items-start gap-2 text-text-2 italic text-[12.5px]">
            <span
              aria-hidden
              className="w-[3px] self-stretch rounded-[2px] bg-ai shrink-0"
            />
            <span>
              {thought}
              {running ? <span className="thought-dots" /> : null}
            </span>
          </div>
        ) : null}

        {steps.map((s, i) => (
          <div
            key={i}
            className="flex items-center gap-2.5 text-[12.5px] text-text-1"
          >
            <span className={STEP_ICON_CLS}>
              <GlyphSlot name={s.icon ?? "bolt"} size={13} />
            </span>
            <span className="text-text-0">{s.label}</span>
            {s.meta ? (
              <span className="text-text-3 font-mono text-[11px]">{s.meta}</span>
            ) : null}
            {s.state ? (
              <span
                className={cn(
                  "ml-auto text-[10.5px] tracking-[0.04em] uppercase",
                  s.state === "running" ? "text-ai" : "text-text-3",
                )}
              >
                {s.state}
              </span>
            ) : null}
          </div>
        ))}

        {output ? (
          <div className="border-2 border-ink rounded-[11px] shadow-ink-1 bg-bg-1 px-3 py-2.5 text-text-0 text-[13px] leading-[1.55] mt-1">
            {output}
          </div>
        ) : null}
      </div>

      {showFooter ? (
        <footer className="flex items-center gap-2 py-2.5 px-3.5 border-t-2 border-dashed border-ink">
          {memory ? (
            <span className="inline-flex items-center gap-1.5 py-0.5 px-2.5 rounded-full border-[1.5px] border-ink bg-bg-1 font-mono text-[11px] text-text-2">
              <GlyphSlot name="brain" size={12} />
              {memory}
            </span>
          ) : null}
          <span className="flex-1" />
          <button
            type="button"
            onClick={onDismiss}
            className="text-[11.5px] text-text-2 py-1 px-2.5 rounded-md hover:bg-bg-2 hover:text-text-0"
          >
            {footerOpts?.dismissLabel ?? "Dismiss"}
          </button>
          <button
            type="button"
            onClick={onApprove}
            className="text-[11.5px] font-semibold py-1 px-2.5 rounded-md bg-ai text-white border-[1.5px] border-ink shadow-ink-1"
          >
            {footerOpts?.approveLabel ?? "Approve"}
          </button>
        </footer>
      ) : null}
    </div>
  );
});
