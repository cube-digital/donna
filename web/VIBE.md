# Donna web vibe rules

A short, enforceable design baseline. Source of truth: the **Connections** section in `src/components/Shell/Sidebar.tsx`. Everything else aligns to it.

Feel: **dense, monochrome chrome, brand-only color, hairline borders**. Think Linear × PostHog × Slack — nerdy, business, restrained.

---

## 1. Type scale

| Role | Size | Class |
|---|---|---|
| Primary body / label | 13px | `text-[13px]` |
| Secondary | 12.5px | `text-[12.5px]` |
| Tertiary / meta | 12px | `text-[12px]` |
| Micro (uppercase group label, kbd, badges) | 10–11px | `text-[10px]` / `text-[11px]` |
| Headings | 15px | `text-[15px]` |

**Never use `text-[13.5px]`** — round down to 13.

## 2. Spacing

Rows: `py-1 px-2.5`. Implied `h-6` (24px). Use `h-7` (28px) only for toolbars / heavier interactive bars (composer, search input).

Stack gaps: `gap-2` or `gap-2.5` for icon-text rows.

## 3. Radius

Lock to Tailwind presets — **no custom pixel values**.

| Use | Class | Pixels |
|---|---|---|
| Tiny chips, kbd, micro badges | `rounded-sm` | 3 |
| Default buttons, rows | `rounded-md` | 6 |
| Cards, modals body | `rounded-lg` | 8 |
| Modal shells | `rounded-xl` | 12 |
| Status dots only | `rounded-full` | ∞ |

Forbidden in new code: `rounded-[5px]`, `rounded-[7px]`, `rounded-[9px]`, `rounded-[10px]`, `rounded-[14px]`.

## 4. Color

Chrome is monochrome via tokens:

- Surfaces: `bg-0` (darkest) → `bg-4` (lightest)
- Text: `text-0` (strongest) → `text-3` (faintest)
- Borders: `border-soft` (default), `border-strong` (emphasis)

Brand color reserved for:
- AI surfaces (`bg-ai`, `border-ai-glow`, `text-ai`) — Donna chrome only
- Status dots (`bg-ok`, `bg-warn`, `bg-danger`)
- Brand glyphs in `BrandIc.tsx` (Gmail / Drive / Fathom logos)

**Do not** colorize buttons, links, or rows. Use weight + hover state.

## 5. Status indicators

- Live/error/idle → `1.5×1.5 rounded-full` dot, right-aligned in the row.
- Pills/badges only when the status word itself is informative (`LIVE`, `READ-ONLY`) — `text-[10px] uppercase tracking-[0.04em] px-1.5 py-px rounded-sm border border-<color>`.
- **Never** use `rounded-full` for badges, only for dots.

## 6. Hover

Universal: `hover:bg-bg-2 hover:text-text-0`. Active row: `bg-bg-3 text-text-0`.

Reserve `hover:bg-[oklch(...)]` translucent overlays for AI-glow surfaces only.

## 7. Group headers

```
text-[10px] uppercase tracking-[0.04em] text-text-3 px-2.5 mt-2.5 mb-0.5
```

Optional `+` add-button on the right: `rounded-sm w-4 h-4 grid place-items-center text-text-3 hover:text-text-0`.

## 8. Borders

Hairline `border-soft` by default. Solid only; **no `border-dashed`** — too visually loud against the dense field.

## 9. Icons

- Generic UI → inline SVG components in `components/Ui/Ic.tsx`, sized 14–16px, stroke-based, inherit `currentColor`.
- Brand glyphs (Gmail, Drive, Fathom, future) → `components/Ui/BrandIc.tsx`, sized 18px, official-ish brand color.
- Fallback for unknown connectors → `InitialsIc` (two letters in a square).

## 10. Empty states

One line, `text-[12.5px] text-text-3`, inside a `ROW_DISABLED` row. No emojis, no marketing copy.

```tsx
<div className={cls(ROW_BASE, ROW_DISABLED)}>
  <span className={cls(NAME_SLOT, "text-[12px]")}>No X yet</span>
</div>
```

---

## Enforcement

When editing any view component:

1. Open `Sidebar.tsx` in a split — copy class fragments verbatim where the row pattern applies.
2. Grep before merging: `rg "rounded-\[" src/` — should not flag your file.
3. Grep: `rg "text-\[13.5" src/` — should be empty.
4. Visually: row heights line up across the shell when sections share `py-1`.

Update this doc when a new pattern wins; otherwise hold the line.
