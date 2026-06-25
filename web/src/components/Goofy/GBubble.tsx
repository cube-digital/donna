// Goofy chat bubbles. User bubbles ride right-aligned in solid grape
// (the brand AI accent) with a custom corner radius; agent bubbles sit
// left, paired with their avatar, in cream paper.

import { forwardRef, type HTMLAttributes, type ReactNode } from "react";

import { cn } from "../../lib/cn";
import { GAvatar } from "./GAvatar";

export type GBubbleFrom = "user" | "agent";

export interface GBubbleProps extends Omit<HTMLAttributes<HTMLDivElement>, "children"> {
  from?: GBubbleFrom;
  /** Override the default agent avatar — pass any node, typically a `<GAvatar/>`. */
  avatar?: ReactNode;
  children: ReactNode;
}

export const GBubble = forwardRef<HTMLDivElement, GBubbleProps>(function GBubble(
  { from = "agent", avatar, className, children, ...rest },
  ref,
) {
  if (from === "user") {
    return (
      <div
        ref={ref}
        className={cn(
          "max-w-[460px] text-[14px] leading-[1.5] ml-auto bg-ai text-white rounded-[16px_16px_5px_16px] px-3.5 py-2.5 font-display font-medium",
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
      ref={ref}
      className={cn(
        "flex items-start gap-2.5 max-w-[640px] text-[14px] leading-[1.5]",
        className,
      )}
      {...rest}
    >
      {avatar ?? <GAvatar kind="agent" name="AG" />}
      <div className="text-text-1 leading-[1.6] rounded-lg px-2 py-1 hover:bg-[oklch(0.30_0.02_285/.03)]">
        {children}
      </div>
    </div>
  );
});
