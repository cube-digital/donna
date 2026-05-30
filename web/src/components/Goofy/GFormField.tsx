// Semantic field wrapper. Renders a label above the control with an
// optional helper line or error message below. Designed to wrap any of
// the Goofy input atoms (`GInput`, `GField`) but accepts any child
// element so callers can drop in native controls too.
//
// The label associates with the inner control via the standard
// label-wraps-control pattern; no `htmlFor` plumbing needed unless the
// caller renders the control elsewhere (in which case pass `htmlFor`).

import { forwardRef, type HTMLAttributes, type ReactNode } from "react";

import { cn } from "../../lib/cn";

export interface GFormFieldProps
  extends Omit<HTMLAttributes<HTMLLabelElement>, "title"> {
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
}

export const GFormField = forwardRef<HTMLElement, GFormFieldProps>(
  function GFormField(
    {
      label,
      hint,
      error,
      required = false,
      htmlFor,
      layout = "column",
      children,
      className,
      ...rest
    },
    ref,
  ) {
    const inner = (
      <>
        <span
          className={cn(
            "font-display font-medium text-[12.5px] text-text-1 select-none",
            layout === "row" && "min-w-[110px] pt-2",
          )}
        >
          {label}
          {required ? (
            // Visual `*` marker. Decorative — screen readers already get
            // the required signal from the consumer's `required` /
            // `aria-required` on the inner control, so we hide the
            // asterisk from AT to avoid "asterisk" being announced
            // mid-label.
            <span aria-hidden="true" className="text-danger ml-0.5">
              *
            </span>
          ) : null}
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

    const containerCls = cn(
      layout === "row" ? "flex items-start gap-3" : "flex flex-col gap-1.5",
      className,
    );

    // When `htmlFor` is provided, we render a div + nested label so the
    // caller's own <label/> association rules apply via the for-id link.
    // Otherwise the whole component is one <label/> so clicking anywhere
    // (the label text included) focuses the inner control.
    if (htmlFor) {
      return (
        <div
          ref={ref as React.Ref<HTMLDivElement>}
          className={containerCls}
          {...(rest as HTMLAttributes<HTMLDivElement>)}
        >
          <label htmlFor={htmlFor} className="contents">
            {inner}
          </label>
        </div>
      );
    }
    return (
      <label
        ref={ref as React.Ref<HTMLLabelElement>}
        className={containerCls}
        {...rest}
      >
        {inner}
      </label>
    );
  },
);
