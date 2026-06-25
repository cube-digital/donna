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
  sm: "w-[26px] h-[26px] rounded-[8px] text-[11px]",
  md: "w-[30px] h-[30px] rounded-[9px] text-[12px]",
  lg: "w-[46px] h-[46px] rounded-[13px] text-[17px]",
  xl: "w-[72px] h-[72px] rounded-[20px] text-[26px]",
};

const BASE =
  "relative shrink-0 inline-grid place-items-center font-semibold text-white";

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

// Avatar-specific DOM attributes that we always strip from the spread
// rest (they would otherwise leak onto the underlying <div>):
type AvatarDomBase = Omit<HTMLAttributes<HTMLDivElement>, "color">;

export interface GAvatarHumanProps extends AvatarDomBase {
  kind?: "human";
  name?: string;
  /** Solid background colour (any CSS value, e.g. `var(--pop-coral)`). */
  color?: string;
  /** Pulsing ring while mid-stream. Visually only useful on agent avatars
   * but accepted on human too for symmetry. */
  pulsing?: boolean;
  size?: GAvatarSize;
}

export interface GAvatarAgentProps extends AvatarDomBase {
  kind: "agent";
  name?: string;
  /** Per-instance hue (degrees, 0–360). Defaults to the global AI hue. */
  hue?: number;
  pulsing?: boolean;
  size?: GAvatarSize;
}

export type GAvatarProps = GAvatarHumanProps | GAvatarAgentProps;

/**
 * Sticker avatar with an ink outline. `kind="agent"` swaps the flat fill
 * for the AI gradient + permanent inset ring; `pulsing` overlays an
 * outward pulse ring driven by the `gx-pulse-ring` keyframes.
 *
 * Implementation note: we branch on the `kind` discriminator and
 * destructure inside each branch so TypeScript narrows the union
 * cleanly (no `as` casts), and so variant-only props (`hue` on agent,
 * `color` on human) never spread onto the DOM as unknown HTML attrs.
 */
export const GAvatar = forwardRef<HTMLDivElement, GAvatarProps>(function GAvatar(
  props,
  ref,
) {
  if (props.kind === "agent") {
    const {
      kind: _kind,
      name = "??",
      hue,
      size = "md",
      pulsing = false,
      className,
      style,
      "aria-label": ariaLabel,
      ...rest
    } = props;
    void _kind;
    const letter = (name?.trim()?.[0] ?? "?").toUpperCase();
    return (
      <div
        ref={ref}
        aria-label={ariaLabel ?? name}
        className={cn(
          BASE,
          SIZE_CLS[size],
          "bg-ai",
          pulsing && "av-pulse-ring",
          className,
        )}
        style={{ "--hue": hue ?? 288, ...style } as CSSProperties}
        {...rest}
      >
        <span aria-hidden="true">{letter}</span>
      </div>
    );
  }
  const {
    kind: _kind,
    name = "??",
    color,
    size = "md",
    pulsing = false,
    className,
    style,
    "aria-label": ariaLabel,
    ...rest
  } = props;
  void _kind;
  return (
    <div
      ref={ref}
      aria-label={ariaLabel ?? name}
      className={cn(BASE, SIZE_CLS[size], pulsing && "av-pulse-ring", className)}
      style={{ background: color ?? "var(--pop-coral)", ...style }}
      {...rest}
    >
      <span aria-hidden="true">{makeInitials(name)}</span>
    </div>
  );
});

// ── Stack ──────────────────────────────────────────────────────────────

/** One entry in a `<GAvatarStack/>`. Use `kind: "agent"` for AI faces;
 * default (`kind: "human"` or omitted) is the flat-colour human variant. */
export type GAvatarStackPerson =
  | { kind?: "human"; name?: string; color?: string }
  | { kind: "agent"; name?: string; hue?: number };

export interface GAvatarStackProps extends HTMLAttributes<HTMLDivElement> {
  people: GAvatarStackPerson[];
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
          // Stable key: combine kind + name + slot index. Names alone
          // would collide when two people share initials; index alone
          // forces re-mount on re-order. The triple is good enough for
          // a non-keyed inbound list and survives the common churn.
          const key = `${p.kind ?? "human"}:${p.name ?? "??"}:${i}`;
          if (p.kind === "agent") {
            return (
              <GAvatar
                key={key}
                kind="agent"
                name={p.name}
                hue={p.hue}
                size={size}
              />
            );
          }
          return (
            <GAvatar
              key={key}
              name={p.name}
              color={p.color}
              size={size}
            />
          );
        })}
      </div>
    );
  },
);
