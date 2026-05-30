// Wraps any Goofy subtree with the `.gx` namespace class and (optional)
// `dark` + `wiggly` modifiers. Mirrors the design source's
// `<div className="gx dark wiggly">` pattern.
//
// `paper` opts into the paper-dot background texture. Off by default so
// embedding the kit inside an existing surface doesn't repaint it.
//
// The wiggly hover animations live in `global.css` (gated behind
// `prefers-reduced-motion: no-preference`) so this provider only flips
// the class — no inline arbitrary-variant chain bloating every render.

import {
  forwardRef,
  type ElementType,
  type HTMLAttributes,
  type ReactNode,
  type Ref,
} from "react";

import { cn } from "../../lib/cn";

export interface GoofyThemeProps extends HTMLAttributes<HTMLDivElement> {
  /** Render Midnight palette instead of Cream. */
  dark?: boolean;
  /** Make every sticker restlessly wiggle (decorative — off by default). */
  wiggly?: boolean;
  /** Paint the cream paper-dot background under the kit. */
  paper?: boolean;
  /** Render as a different tag if you don't want a div. */
  as?: ElementType;
  children: ReactNode;
}

/**
 * Theme provider for the Goofy kit. The classes flip the OKLCH variables
 * declared in `tokens.css`, so colour utilities like `bg-bg-0` resolve
 * to the right palette without per-component conditionals.
 */
export const GoofyTheme = forwardRef<HTMLElement, GoofyThemeProps>(
  function GoofyTheme(
    {
      dark = false,
      wiggly = false,
      paper = false,
      as,
      className,
      children,
      ...rest
    },
    ref,
  ) {
    const Tag = (as ?? "div") as ElementType;
    return (
      <Tag
        ref={ref as Ref<HTMLElement>}
        data-theme={dark ? "midnight" : "cream"}
        className={cn(
          "gx",
          dark && "dark",
          wiggly && "wiggly",
          paper && "paper-dots",
          className,
        )}
        {...rest}
      >
        {children}
      </Tag>
    );
  },
);
