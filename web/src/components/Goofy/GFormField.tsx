// Semantic field wrapper. Renders a label above the control with an
// optional helper line or error message below. Designed to wrap any of
// the Goofy input atoms (`GInput`, `GField`) but accepts any child
// element so callers can drop in native controls too.
//
// The label associates with the inner control via the standard
// label-wraps-control pattern; no `htmlFor` plumbing needed unless the
// caller renders the control elsewhere (in which case pass `htmlFor`).

import type { ReactNode } from "react";

import { cn } from "../../lib/cn";

export interface GFormFieldProps {
  label: ReactNode;
  /** Subtle helper line below the control. Hidden when `error` is set. */
  hint?: ReactNode;
  /** Error message — replaces the hint in danger colour when set. */
  error?: ReactNode;
  /** Mark the field as required (adds an asterisk after the label). */
  required?: boolean;
  /** `for=` target if the control isn't a direct child. */
  htmlFor?: string;
  /** Layout: column (default) or row (label + control on one line). */
  layout?: "column" | "row";
  children: ReactNode;
  className?: string;
}

export function GFormField({
  label,
  hint,
  error,
  required = false,
  htmlFor,
  layout = "column",
  children,
  className,
}: GFormFieldProps) {
  const inner = (
    <>
      <span
        className={cn(
          "font-display font-medium text-[12.5px] text-text-1 select-none",
          layout === "row" && "min-w-[110px] pt-2",
        )}
      >
        {label}
        {required ? <span className="text-danger ml-0.5">*</span> : null}
      </span>
      <div className="flex-1 min-w-0 flex flex-col gap-1">
        {children}
        {error ? (
          <span className="font-mono text-[11px] text-danger">{error}</span>
        ) : hint ? (
          <span className="text-[11.5px] text-text-3">{hint}</span>
        ) : null}
      </div>
    </>
  );

  // When `htmlFor` is provided, we render a fragment so the caller's own
  // <label/> association rules apply. Otherwise we wrap with a <label/>
  // so clicking the label focuses the control.
  if (htmlFor) {
    return (
      <div
        className={cn(
          layout === "row" ? "flex items-start gap-3" : "flex flex-col gap-1.5",
          className,
        )}
      >
        <label htmlFor={htmlFor} className="contents">
          {inner}
        </label>
      </div>
    );
  }
  return (
    <label
      className={cn(
        layout === "row" ? "flex items-start gap-3" : "flex flex-col gap-1.5",
        className,
      )}
    >
      {inner}
    </label>
  );
}
