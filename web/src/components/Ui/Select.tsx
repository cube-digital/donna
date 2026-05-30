// Native <select> styled to match Input. Chevron rendered via inline SVG
// background-image so we keep the markup as one element. No portaling for v1
// — leave fancier dropdown UX to MultiSelect.

import { forwardRef, type SelectHTMLAttributes } from "react";

type SelectProps = SelectHTMLAttributes<HTMLSelectElement>;

// Chevron is a 12×12 stroke-1.5 down-caret in --text-3.
const CHEVRON =
  "data:image/svg+xml;utf8," +
  encodeURIComponent(
    "<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' " +
      "fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'>" +
      "<polyline points='6 9 12 15 18 9'></polyline>" +
      "</svg>",
  );

const CLS =
  "h-7 pl-2.5 pr-7 text-[13px] text-text-0 bg-bg-2 border border-border-soft rounded-md " +
  "appearance-none outline-none focus:border-border-strong " +
  "disabled:opacity-60 disabled:cursor-not-allowed cursor-pointer";

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { className, style, children, ...rest },
  ref,
) {
  return (
    <select
      ref={ref}
      className={`${CLS} ${className ?? ""}`}
      style={{
        backgroundImage: `url("${CHEVRON}")`,
        backgroundRepeat: "no-repeat",
        backgroundPosition: "right 8px center",
        ...style,
      }}
      {...rest}
    >
      {children}
    </select>
  );
});
