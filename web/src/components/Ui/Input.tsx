// Bare text input. Matches web/VIBE.md form metrics.
//
// Use directly for free text; or as the inner control of MultiSelect.
// For typed inputs (number, email) pass `type` through.

import { forwardRef, type InputHTMLAttributes } from "react";

type InputProps = InputHTMLAttributes<HTMLInputElement>;

const CLS =
  "h-7 px-2.5 text-[13px] text-text-0 bg-bg-2 border border-border-soft rounded-md " +
  "outline-none focus:border-border-strong placeholder:text-text-3 " +
  "disabled:opacity-60 disabled:cursor-not-allowed";

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { className, ...rest },
  ref,
) {
  return <input ref={ref} className={`${CLS} ${className ?? ""}`} {...rest} />;
});
