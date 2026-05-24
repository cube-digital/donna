// DonnaAI — Tailwind theme.
//
// Every colour is an OKLCH CSS variable defined in `src/styles/tokens.css`.
// The single `--ai-h` variable controls the AI hue; the rest cascade from it.
// Theme switching is class-based: `.theme-light` on <body> swaps the var
// values. Tailwind's `dark:*` prefix is NOT used — light is the named
// variant so the dark default reads as the design's primary mode.
//
// Naming convention:
//   bg-bg-0 … bg-bg-4         layered backgrounds (darkest → lightest in dark mode)
//   text-text-0 … text-text-4 layered text (most prominent → most muted)
//   border-border-soft        default border
//   border-border-strong      emphasis border
//   bg-ai / text-ai / etc.    AI hue family
//   text-ok / warn / danger   semantic statuses

import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Surfaces
        "bg-0": "var(--bg-0)",
        "bg-1": "var(--bg-1)",
        "bg-2": "var(--bg-2)",
        "bg-3": "var(--bg-3)",
        "bg-4": "var(--bg-4)",
        // Text
        "text-0": "var(--text-0)",
        "text-1": "var(--text-1)",
        "text-2": "var(--text-2)",
        "text-3": "var(--text-3)",
        "text-4": "var(--text-4)",
        // Borders
        "border-soft": "var(--border)",
        "border-strong": "var(--border-strong)",
        // AI hue family — single hue gated by --ai-h, reserved exclusively
        // for agent presence, thinking states, memory chrome.
        ai: "var(--ai)",
        "ai-dim": "var(--ai-dim)",
        "ai-deep": "var(--ai-deep)",
        "ai-bg": "var(--ai-bg)",
        "ai-glow": "var(--ai-glow)",
        // Status
        ok: "var(--ok)",
        warn: "var(--warn)",
        danger: "var(--danger)",
      },
      fontFamily: {
        sans: [
          "Geist",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "sans-serif",
        ],
        mono: [
          '"Geist Mono"',
          "ui-monospace",
          "SFMono-Regular",
          "monospace",
        ],
      },
      borderRadius: {
        DEFAULT: "var(--r)",
        sm: "var(--r-sm)",
        lg: "var(--r-lg)",
        xl: "var(--r-xl)",
      },
      boxShadow: {
        soft: "var(--shadow-1)",
        elevated: "var(--shadow-2)",
      },
      keyframes: {
        "pulse-ring": {
          "0%": { transform: "scale(0.95)", opacity: "0.7" },
          "100%": { transform: "scale(1.25)", opacity: "0" },
        },
        "led-blink": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.35" },
        },
        "dots-pulse": {
          "0%, 100%": { opacity: "0.3" },
          "50%": { opacity: "1" },
        },
        "spin-360": {
          to: { transform: "rotate(360deg)" },
        },
      },
      animation: {
        "pulse-ring": "pulse-ring 1.6s ease-out infinite",
        "led-blink": "led-blink 1.2s ease-in-out infinite",
        "dots-pulse": "dots-pulse 1s steps(3, end) infinite",
        "spin-360": "spin-360 1s linear infinite",
      },
    },
  },
  plugins: [],
};

export default config;
