// Goofy tabs — segmented sticker with one active tab painted in pop-sun
// and the rest in muted text. Generic over the tab key type so type
// errors catch mistyped values at the call site.

import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "../../lib/cn";

interface BaseTab<T> {
  value: T;
  label: ReactNode;
}

export type GTabsItem<T extends string = string> = T | BaseTab<T>;

export interface GTabsProps<T extends string = string>
  extends Omit<HTMLAttributes<HTMLDivElement>, "onChange"> {
  tabs: GTabsItem<T>[];
  value: T;
  onChange: (next: T) => void;
}

function normalise<T extends string>(item: GTabsItem<T>): BaseTab<T> {
  if (typeof item === "string") return { value: item, label: item };
  return item;
}

export function GTabs<T extends string = string>({
  tabs,
  value,
  onChange,
  className,
  ...rest
}: GTabsProps<T>) {
  return (
    <div
      role="tablist"
      className={cn(
        // Outer + inner pills share the same `rounded-full` so the
        // active sticker sits cleanly concentric to the capsule.
        "inline-flex items-center gap-0.5 p-0.5 border-2 border-ink rounded-full shadow-ink-1 bg-bg-1",
        className,
      )}
      {...rest}
    >
      {tabs.map((raw) => {
        const t = normalise(raw);
        const isActive = t.value === value;
        return (
          <button
            key={t.value}
            type="button"
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(t.value)}
            className={cn(
              "px-3.5 py-1 rounded-full text-[12.5px] font-medium cursor-pointer transition-colors duration-[120ms]",
              "outline-none focus-visible:ring-2 focus-visible:ring-ai focus-visible:ring-offset-1 focus-visible:ring-offset-bg-1",
              isActive
                ? "bg-pop-sun text-on-bright border-[1.5px] border-ink font-semibold"
                : "text-text-2 hover:text-text-0",
            )}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}
