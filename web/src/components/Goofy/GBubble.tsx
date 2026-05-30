// Goofy chat bubbles. User bubbles ride right-aligned in pop-blue with
// a custom corner radius; agent bubbles sit left, paired with their
// avatar, in cream paper.

import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "../../lib/cn";
import { GAvatar } from "./GAvatar";

export type GBubbleFrom = "user" | "agent";

export interface GBubbleProps extends Omit<HTMLAttributes<HTMLDivElement>, "children"> {
  from?: GBubbleFrom;
  /** Override the default agent avatar — pass any node, typically a `<GAvatar/>`. */
  avatar?: ReactNode;
  children: ReactNode;
}

export function GBubble({
  from = "agent",
  avatar,
  className,
  children,
  ...rest
}: GBubbleProps) {
  if (from === "user") {
    return (
      <div
        className={cn(
          "max-w-[460px] text-[14px] leading-[1.5] ml-auto bg-pop-blue text-white border-2 border-ink rounded-[16px_16px_5px_16px] shadow-ink-1 px-3.5 py-2.5 font-display font-medium",
          className,
        )}
        {...rest}
      >
        {children}
      </div>
    );
  }
  return (
    <div
      className={cn(
        "flex items-start gap-2.5 max-w-[460px] text-[14px] leading-[1.5]",
        className,
      )}
      {...rest}
    >
      {avatar ?? <GAvatar kind="agent" name="AG" />}
      <div className="bg-bg-1 text-text-1 border-2 border-ink rounded-[16px_16px_16px_5px] shadow-ink-1 px-3.5 py-2.5">
        {children}
      </div>
    </div>
  );
}
