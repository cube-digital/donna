// Goofy selects.
//
//   <GSelect/>       native <select> wearing the same pill chrome as
//                    `<GInput/>` — chevron is an inline SVG painted with
//                    `currentColor` so it follows the text colour.
//   <GMultiSelect/>  chip-style multi-pick. Free-text or constrained-to-
//                    `options`. Pure controlled — `value` + `onChange`.

import {
  forwardRef,
  useEffect,
  useMemo,
  useRef,
  useState,
  type SelectHTMLAttributes,
} from "react";

import { cn } from "../../lib/cn";
import { GlyphSlot } from "./GIcons";

// ── Single-select ──────────────────────────────────────────────────────

const SELECT_SHELL =
  "relative inline-flex items-center h-[38px] " +
  "border-2 border-ink rounded-full shadow-ink-1 bg-bg-1 text-text-0 " +
  "transition-[box-shadow,border-color] duration-[120ms] " +
  "focus-within:border-ai focus-within:shadow-ai-stamp";

const SELECT_CONTROL =
  "appearance-none bg-transparent pl-[14px] pr-9 py-1 text-[13.5px] " +
  "text-text-0 outline-none cursor-pointer disabled:cursor-not-allowed disabled:opacity-60 " +
  // The chevron lives in a sibling `<span>` rendered as an absolutely-
  // positioned overlay; we just reserve the space here.
  "min-w-[140px]";

export interface GSelectProps
  extends SelectHTMLAttributes<HTMLSelectElement> {
  /** Replace the outer pill className entirely. */
  shellClassName?: string;
}

/**
 * Pill-shaped Goofy select. Wraps a native `<select/>` so callers get
 * all the right semantics (form submission, keyboard, screen readers)
 * with none of the cross-browser dropdown styling pain.
 */
export const GSelect = forwardRef<HTMLSelectElement, GSelectProps>(
  function GSelect({ shellClassName, className, children, ...rest }, ref) {
    return (
      <span className={cn(SELECT_SHELL, shellClassName)}>
        <select
          ref={ref}
          className={cn(SELECT_CONTROL, className)}
          {...rest}
        >
          {children}
        </select>
        <span
          aria-hidden
          className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-text-3"
        >
          <GlyphSlot name="caret" size={14} />
        </span>
      </span>
    );
  },
);

// ── Multi-select ───────────────────────────────────────────────────────

export interface GMultiSelectOption {
  id: string;
  label: string;
  /** Optional grouping label rendered as a small uppercase divider. */
  group?: string;
}

export interface GMultiSelectProps {
  value: string[];
  onChange: (next: string[]) => void;
  /** Constrain picks to this list. Omit for free-text-only mode. */
  options?: GMultiSelectOption[];
  placeholder?: string;
  disabled?: boolean;
  /** When `options` is set, allow Enter to add a value not in the list. */
  allowCustom?: boolean;
  className?: string;
}

const MS_SHELL =
  "min-h-[38px] flex flex-wrap items-center gap-1.5 px-2 py-1 " +
  "border-2 border-ink rounded-[14px] shadow-ink-1 bg-bg-1 cursor-text " +
  "transition-[box-shadow,border-color] duration-[120ms] " +
  "focus-within:border-ai focus-within:shadow-ai-stamp";

const MS_CHIP =
  "inline-flex items-center gap-1.5 h-[22px] px-2 rounded-full " +
  "border-[1.5px] border-ink bg-bg-2 text-text-1 text-[11.5px] font-medium";

const MS_DROPDOWN =
  "absolute z-20 mt-1.5 w-full max-h-[240px] overflow-y-auto " +
  "border-2 border-ink rounded-[12px] shadow-ink-2 bg-bg-1 p-1.5";

const MS_OPTION =
  "w-full text-left px-2.5 py-1.5 rounded-[9px] text-[13px] text-text-1 cursor-pointer " +
  "transition-colors duration-[100ms] hover:bg-bg-3 hover:text-text-0";

/**
 * Chip-style multi-pick. Two modes:
 *   - Free-text (no `options`)         — Enter adds the typed value
 *   - Constrained (`options` provided) — typing filters the dropdown;
 *                                        Enter only adds if `allowCustom`
 */
export function GMultiSelect({
  value,
  onChange,
  options,
  placeholder = "Type to add…",
  disabled,
  allowCustom = false,
  className,
}: GMultiSelectProps) {
  const [input, setInput] = useState("");
  const [open, setOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  const optionById = useMemo(() => {
    const m = new Map<string, GMultiSelectOption>();
    for (const o of options ?? []) m.set(o.id, o);
    return m;
  }, [options]);

  const filteredOptions = useMemo(() => {
    if (!options) return [];
    const q = input.trim().toLowerCase();
    const inSet = new Set(value);
    return options.filter(
      (o) => !inSet.has(o.id) && (q === "" || o.label.toLowerCase().includes(q)),
    );
  }, [options, input, value]);

  // Group filtered options by their `group` label.
  const grouped = useMemo(() => {
    const out = new Map<string, GMultiSelectOption[]>();
    for (const o of filteredOptions) {
      const k = o.group ?? "";
      const arr = out.get(k) ?? [];
      arr.push(o);
      out.set(k, arr);
    }
    return Array.from(out.entries());
  }, [filteredOptions]);

  // Close on outside click.
  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  function add(id: string) {
    if (value.includes(id)) return;
    onChange([...value, id]);
    setInput("");
  }

  function remove(id: string) {
    onChange(value.filter((v) => v !== id));
  }

  function onKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      e.preventDefault();
      const v = input.trim();
      if (!v) return;
      if (options && !allowCustom) return;
      add(v);
    } else if (e.key === "Backspace" && input === "" && value.length > 0) {
      remove(value[value.length - 1]);
    }
  }

  return (
    <div ref={rootRef} className={cn("relative", className)}>
      <div
        className={cn(
          MS_SHELL,
          disabled && "opacity-60 cursor-not-allowed",
        )}
        onClick={() => inputRef.current?.focus()}
      >
        {value.map((id) => {
          const label = optionById.get(id)?.label ?? id;
          return (
            <span key={id} className={MS_CHIP}>
              <span className="max-w-[160px] truncate">{label}</span>
              {!disabled && (
                <button
                  type="button"
                  className="text-text-3 hover:text-text-0 cursor-pointer"
                  aria-label={`Remove ${label}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    remove(id);
                  }}
                >
                  <GlyphSlot name="x" size={11} />
                </button>
              )}
            </span>
          );
        })}
        <input
          ref={inputRef}
          value={input}
          disabled={disabled}
          onChange={(e) => {
            setInput(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKey}
          placeholder={value.length === 0 ? placeholder : ""}
          className="flex-1 min-w-[80px] h-6 bg-transparent outline-none text-[13.5px] text-text-0 placeholder:text-text-3"
        />
      </div>

      {open && options && filteredOptions.length > 0 && (
        <div className={MS_DROPDOWN} role="listbox">
          {grouped.map(([group, opts]) => (
            <div key={group}>
              {group && (
                <div className="px-2 pt-1.5 pb-0.5 text-[10px] uppercase tracking-[0.04em] text-text-3 font-mono">
                  {group}
                </div>
              )}
              {opts.map((o) => (
                <button
                  key={o.id}
                  type="button"
                  className={MS_OPTION}
                  // onMouseDown.preventDefault stops the input from
                  // losing focus on the click — which would close the
                  // dropdown before `onClick` fires.
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => add(o.id)}
                >
                  {o.label}
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
