// Wraps any Goofy subtree with the `.gx` namespace class and (optional)
// `dark` + `wiggly` modifiers. Mirrors the design source's
// `<div className="gx dark wiggly">` pattern.
//
// `paper` opts into the paper-dot background texture. Off by default so
// embedding the kit inside an existing surface doesn't repaint it.

import type { ElementType, HTMLAttributes, ReactNode } from "react";

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
export function GoofyTheme({
  dark = false,
  wiggly = false,
  paper = false,
  as,
  className,
  children,
  ...rest
}: GoofyThemeProps) {
  const Tag = (as ?? "div") as ElementType;
  return (
    <Tag
      data-theme={dark ? "midnight" : "cream"}
      className={cn(
        "gx",
        dark && "dark",
        wiggly && "wiggly",
        paper && "paper-dots",
        // Wiggly mode — every interactive sticker tilts restlessly on hover.
        // Covers `<button>`, plus all the ARIA roles our components use for
        // composable elements that aren't <button> (list items, tabs,
        // toggles, menu items, custom-rendered avatars/chips, etc.).
        wiggly &&
          "[&_button:hover]:animate-wiggle " +
            "[&_[role=button]:hover]:animate-wiggle " +
            "[&_[role=tab]:hover]:animate-wiggle " +
            "[&_[role=switch]:hover]:animate-wiggle " +
            "[&_[role=checkbox]:hover]:animate-wiggle " +
            "[&_[role=menuitem]:hover]:animate-wiggle " +
            "[&_[role=tooltip]:hover]:animate-wiggle " +
            "[&_.gx-wiggle-target:hover]:animate-wiggle",
        className,
      )}
      {...rest}
    >
      {children}
    </Tag>
  );
}
