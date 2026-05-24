// Avatar — port of `donnaai/project/ui.jsx` lines 132-145.
//
// Two flavours discriminated by `kind`:
//   - "human" — solid background (`who.color`) with initials (or first letter
//      of `who.name`).
//   - "agent" — radial-gradient + glow driven by `--hue` CSS custom prop
//      defined inline. The `av-agent-gradient` helper class in
//      `global.css` (`@layer components`) reads `var(--hue, 282)` for the
//      gradient + box-shadow — we just set that one variable per agent.
//
// `pulsing` adds `av-pulse-ring` which animates a 1px ring around the
// avatar via `::after` + `@keyframes pulse-ring` — no JS animation
// required.
//
// Tailwind migration note
// ───────────────────────
// The old `.av` / `.av.sm` / `.av.lg` / `.av.xl` cascade has been
// dropped; sizing is now picked off the local `SIZE_CLASSES` map
// directly at the call site. Everything else stays in lockstep with
// the design CSS via the `@layer components` helpers in global.css.

import type { CSSProperties } from "react";

export type AvatarSize = "sm" | "" | "lg" | "xl";

interface BaseProps {
  size?: AvatarSize;
  pulsing?: boolean;
}

export interface HumanAv extends BaseProps {
  kind: "human";
  who: { name?: string; initials?: string; color?: string };
}

export interface AgentAv extends BaseProps {
  kind: "agent";
  agent: { name: string; hue: number };
}

export type AvProps = HumanAv | AgentAv;

// Size → sizing utility classes. The default (`""`) is the 28×28
// chip used inline in chat rows; `sm` is the member-stack thumbnail;
// `lg` / `xl` show up in the agent profile hero.
const SIZE_CLASSES: Record<AvatarSize, string> = {
  sm: "w-5 h-5 text-[9px] rounded-[5px]",
  "": "w-7 h-7 text-[11px] rounded-[7px]",
  lg: "w-11 h-11 text-base rounded-[10px]",
  xl: "w-[72px] h-[72px] text-2xl rounded-2xl",
};

// Agent-specific gradient glow class — the larger sizes need a beefier
// outer glow so the avatar still reads as "AI-lit".
const AGENT_GLOW: Record<AvatarSize, string> = {
  sm: "av-agent-gradient",
  "": "av-agent-gradient",
  lg: "av-agent-gradient av-agent-gradient-lg",
  xl: "av-agent-gradient av-agent-gradient-xl",
};

// Layout shared by both variants.
const BASE =
  "inline-grid place-items-center font-semibold text-bg-0 shrink-0 relative";

export function Av(props: AvProps) {
  const size = props.size ?? "";
  const sizeCls = SIZE_CLASSES[size];
  const pulseCls = props.pulsing ? " av-pulse-ring" : "";

  if (props.kind === "agent") {
    const { agent } = props;
    const style: CSSProperties = {
      // CSS custom prop consumed by the `av-agent-gradient` helper in
      // global.css.
      ["--hue" as keyof CSSProperties]: agent.hue,
    } as CSSProperties;
    return (
      <div
        className={`${BASE} ${sizeCls} ${AGENT_GLOW[size]}${pulseCls}`}
        style={style}
      >
        <span>{agent.name[0] ?? ""}</span>
      </div>
    );
  }

  const { who } = props;
  const label = who.initials ?? who.name?.[0] ?? "?";
  const style: CSSProperties | undefined = who.color
    ? { background: who.color }
    : undefined;
  return (
    <div className={`${BASE} ${sizeCls}${pulseCls}`} style={style}>
      {label}
    </div>
  );
}

export default Av;
