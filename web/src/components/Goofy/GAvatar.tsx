// Goofy avatars — every face wears a chunky ink outline. Human avatars
// take a flat colour fill; agent avatars get the AI radial gradient
// driven by a per-instance `--hue` so different agents stay
// distinguishable inside the AI family.
//
// `pulsing` adds the gx-pulse-ring animation around an avatar mid-stream.

import { forwardRef, type CSSProperties, type HTMLAttributes } from "react";

import { cn } from "../../lib/cn";

export type GAvatarSize = "sm" | "md" | "lg" | "xl";

const SIZE_CLS: Record<GAvatarSize, string> = {
  sm: "w-[22px] h-[22px] border-[1.5px] rounded-md text-[10px]",
  md: "w-[30px] h-[30px] border-2 rounded-[9px] text-[12px]",
  lg: "w-[46px] h-[46px] border-2 rounded-[13px] text-[17px]",
  xl: "w-[72px] h-[72px] border-[2.5px] rounded-[20px] text-[26px]",
};

const BASE =
  "gx-wiggle-target relative shrink-0 inline-grid place-items-center border-ink font-display font-semibold text-white";

function makeInitials(name: string): string {
  if (!name) return "??";
  if (name.length <= 2) return name.toUpperCase();
  return name
    .split(/\s+/)
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

export interface GAvatarHumanProps {
  kind?: "human";
  name?: string;
  /** Solid background colour (any CSS value, e.g. `var(--pop-coral)`). */
  color?: string;
  /** Pulsing ring while mid-stream. Visually only useful on agent avatars
   * but accepted on human too for symmetry. */
  pulsing?: boolean;
}

export interface GAvatarAgentProps {
  kind: "agent";
  name?: string;
  /** Per-instance hue (degrees, 0–360). Defaults to the global AI hue. */
  hue?: number;
  pulsing?: boolean;
}

export type GAvatarProps = (GAvatarHumanProps | GAvatarAgentProps) & {
  size?: GAvatarSize;
} & Omit<HTMLAttributes<HTMLDivElement>, "color">;

/**
 * Sticker avatar with an ink outline. `kind="agent"` swaps the flat fill
 * for the AI gradient + permanent inset ring; `pulsing` overlays an
 * outward pulse ring driven by the `gx-pulse-ring` keyframes.
 */
export const GAvatar = forwardRef<HTMLDivElement, GAvatarProps>(function GAvatar(
  props,
  ref,
) {
  const { name = "??", size = "md", pulsing = false, className, style, ...rest } = props;
  const isAgent = props.kind === "agent";
  const initials = makeInitials(name);

  const colorStyle: CSSProperties = isAgent
    ? ({ "--hue": (props as GAvatarAgentProps).hue ?? 288 } as CSSProperties)
    : { background: (props as GAvatarHumanProps).color ?? "var(--pop-coral)" };

  return (
    <div
      ref={ref}
      className={cn(
        BASE,
        SIZE_CLS[size],
        isAgent && "av-agent-gradient",
        pulsing && "av-pulse-ring",
        className,
      )}
      style={{ ...colorStyle, ...style }}
      {...rest}
    >
      <span>{initials}</span>
    </div>
  );
});

// ── Stack ──────────────────────────────────────────────────────────────

export interface GAvatarStackProps extends HTMLAttributes<HTMLDivElement> {
  people: Array<
    | ({ kind?: "human"; name?: string; color?: string } & { agent?: false })
    | ({ kind: "agent"; name?: string; hue?: number } & { agent?: true })
  >;
  size?: GAvatarSize;
}

/**
 * Overlapping group of avatars. Each child gets an additional ring of
 * the page background so the stack reads cleanly even on busy surfaces.
 */
export const GAvatarStack = forwardRef<HTMLDivElement, GAvatarStackProps>(
  function GAvatarStack({ people, size = "md", className, ...rest }, ref) {
    return (
      <div
        ref={ref}
        className={cn(
          "flex [&>*]:-ml-2 [&>*:first-child]:ml-0 [&>*]:shadow-[0_0_0_2px_var(--bg-0)]",
          className,
        )}
        {...rest}
      >
        {people.map((p, i) => {
          // Normalise the shorthand `agent: true` flag into the discriminated union.
          if (p.agent || p.kind === "agent") {
            return (
              <GAvatar
                key={i}
                kind="agent"
                name={p.name}
                hue={"hue" in p ? p.hue : undefined}
                size={size}
              />
            );
          }
          return (
            <GAvatar
              key={i}
              name={p.name}
              color={"color" in p ? p.color : undefined}
              size={size}
            />
          );
        })}
      </div>
    );
  },
);
