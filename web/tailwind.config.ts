// DonnaAI · Goofy theme — Tailwind config.
//
// Every colour is an OKLCH CSS variable defined in `src/styles/tokens.css`.
// The single `--ai-h` variable controls the AI hue (grape, 288°); the rest
// cascade. Theme switching is class-based via `body.theme-dark` (or
// `.gx.dark` on a Goofy subtree).
//
// Naming convention:
//   bg-bg-0..bg-bg-4                       layered paper surfaces
//   text-text-0..text-text-4               layered text
//   border-ink                             chunky 2 px sticker border (ink)
//   border-border-soft / -strong           softer borders for split rules
//   bg-ai / text-ai / border-ai            AI grape family
//   bg-pop-blue / -coral / -sun / -mint    crayon-box accents
//   text-on-bright                         body colour to lay on bright fills
//   text-ok / warn / danger                semantic statuses
//   font-display / font-hand / font-mono   Fredoka, Caveat, Geist Mono
//   shadow-ink-1 / shadow-ink-2            hard offset sticker shadows
//   shadow-ai-stamp                        offset shadow in AI grape

import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        "bg-0": "var(--bg-0)",
        "bg-1": "var(--bg-1)",
        "bg-2": "var(--bg-2)",
        "bg-3": "var(--bg-3)",
        "bg-4": "var(--bg-4)",
        "text-0": "var(--text-0)",
        "text-1": "var(--text-1)",
        "text-2": "var(--text-2)",
        "text-3": "var(--text-3)",
        "text-4": "var(--text-4)",
        ink: "var(--ink)",
        "border-soft": "var(--border)",
        "border-strong": "var(--border-strong)",
        ai: "var(--ai)",
        "ai-dim": "var(--ai-dim)",
        "ai-deep": "var(--ai-deep)",
        "ai-bg": "var(--ai-bg)",
        "ai-glow": "var(--ai-glow)",
        // Crayon accents — used in buttons, chips, tags, list states, etc.
        "pop-blue": "var(--pop-blue)",
        "pop-coral": "var(--pop-coral)",
        "pop-sun": "var(--pop-sun)",
        "pop-mint": "var(--pop-mint)",
        "on-bright": "var(--on-bright)",
        ok: "var(--ok)",
        warn: "var(--warn)",
        danger: "var(--danger)",
      },
      fontFamily: {
        // Inter is the primary typeface across the app (matches the docs
        // site). Body, display headings, and the former hand-lettered
        // accents all resolve to Inter now — the playful Fredoka/Caveat
        // faces were retired as part of the clean refresh.
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "sans-serif"],
        mono: ['"Geist Mono"', "ui-monospace", "SFMono-Regular", "monospace"],
        display: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "sans-serif"],
        hand: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      borderRadius: {
        DEFAULT: "var(--r)",
        sm: "var(--r-sm)",
        lg: "var(--r-lg)",
        xl: "var(--r-xl)",
      },
      borderWidth: {
        ink: "2px",
      },
      boxShadow: {
        "ink-1": "var(--shadow-1)",
        "ink-2": "var(--shadow-2)",
        "ai-stamp": "var(--shadow-ai)",
        // Refined hover-lift shadows (was a hard-offset press-down stamp).
        "ink-3": "0 3px 8px oklch(0.26 0.03 285 / 0.12), 0 6px 16px oklch(0.26 0.03 285 / 0.10)",
        "ink-4": "0 6px 16px oklch(0.26 0.03 285 / 0.14), 0 14px 30px oklch(0.26 0.03 285 / 0.10)",
      },
      keyframes: {
        "gx-pulse-ring": {
          "0%": { transform: "scale(0.95)", opacity: "0.7" },
          "100%": { transform: "scale(1.3)", opacity: "0" },
        },
        "gx-spin": { to: { transform: "rotate(360deg)" } },
        "gx-blink": { "0%, 100%": { opacity: "1" }, "50%": { opacity: "0.35" } },
        "gx-dots": {
          "0%, 100%": { opacity: "0.3" },
          "50%": { opacity: "1" },
        },
        "gx-wiggle": {
          "0%, 100%": { transform: "rotate(-3deg)" },
          "50%": { transform: "rotate(3deg)" },
        },
        // Smaller, single-shot tilt for row-shaped molecules (menu items,
        // list rows, docs, stat cards). Starts and ends at 0° so the
        // element snaps cleanly back to neutral when the animation
        // finishes — unlike `gx-wiggle` which loops between ±3°.
        "gx-mini-wiggle": {
          "0%": { transform: "rotate(0deg)" },
          "25%": { transform: "rotate(-1.5deg)" },
          "75%": { transform: "rotate(1.5deg)" },
          "100%": { transform: "rotate(0deg)" },
        },
        "gx-bob": {
          "0%, 100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-5px)" },
        },
        "gx-pop-in": {
          "0%": { transform: "scale(0.6) rotate(-8deg)", opacity: "0" },
          "70%": { transform: "scale(1.08) rotate(2deg)" },
          "100%": { transform: "scale(1) rotate(0)", opacity: "1" },
        },
      },
      animation: {
        "pulse-ring": "gx-pulse-ring 1.6s ease-out infinite",
        "led-blink": "gx-blink 1.2s ease-in-out infinite",
        "dots-pulse": "gx-dots 1s steps(3, end) infinite",
        // Refined: hover wiggles removed for a calmer, more professional
        // feel. Mapped to `none` so existing `animate-wiggle` /
        // `animate-mini-wiggle` utilities become no-ops.
        wiggle: "none",
        "mini-wiggle": "none",
        bob: "gx-bob 1.6s ease-in-out infinite",
        "pop-in": "gx-pop-in 0.4s cubic-bezier(.34,1.56,.64,1) both",
        "spin-360": "gx-spin 1.2s linear infinite",
      },
      transitionTimingFunction: {
        spring: "cubic-bezier(.34, 1.56, .64, 1)",
      },
    },
  },
  plugins: [],
};

export default config;
