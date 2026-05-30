// Two-variant button. `primary` is high-contrast (text-0 on bg-0), used for
// the main action per surface. `secondary` is a quiet bordered fallback.
// Sizes: `sm` (h-6 px-2.5 11px) for inline actions, default (h-7 px-3 12.5px),
// `lg` (h-9 px-4 13px) for hero CTAs in the auth screen.

import { forwardRef, type ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "danger" | "ghost";
type Size = "sm" | "md" | "lg";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

const SIZES: Record<Size, string> = {
  sm: "h-6 px-2 text-[11px]",
  md: "h-7 px-3 text-[12.5px]",
  lg: "h-9 px-4 text-[13px]",
};

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-text-0 text-bg-0 font-medium border border-text-0 hover:opacity-90",
  secondary:
    "bg-bg-2 text-text-0 border border-border-soft hover:bg-bg-3",
  danger:
    "bg-bg-2 text-danger border border-danger hover:bg-danger hover:text-bg-0",
  ghost:
    "bg-transparent text-text-1 hover:bg-bg-2 hover:text-text-0",
};

const BASE =
  "inline-flex items-center justify-center gap-1.5 rounded-md " +
  "cursor-pointer outline-none focus:ring-1 focus:ring-border-strong " +
  "disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-bg-2";

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", className, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      className={`${BASE} ${SIZES[size]} ${VARIANTS[variant]} ${className ?? ""}`}
      {...rest}
    />
  );
});
