// Chip-style multi-select.
//
// Two modes:
//   1. Free-text — `options` omitted; user types + Enter to add a chip.
//   2. Constrained — `options` supplied; chips drawn from that list. Typing
//      filters the dropdown. Optional grouping via option.group.
//
// Selection is a string[] mirrored by `value`. `onChange` is called with the
// new array on add/remove. Backspace from empty input removes the last chip.

import { useEffect, useMemo, useRef, useState } from "react";

import { Ic } from "./Ic";

export interface MultiSelectOption {
  id: string;
  label: string;
  group?: string;
}

interface MultiSelectProps {
  value: string[];
  onChange: (v: string[]) => void;
  options?: MultiSelectOption[];
  placeholder?: string;
  disabled?: boolean;
  // If true, free-text additions allowed even when `options` is set.
  allowCustom?: boolean;
}

export function MultiSelect({
  value,
  onChange,
  options,
  placeholder = "Type to add…",
  disabled,
  allowCustom = false,
}: MultiSelectProps) {
  const [input, setInput] = useState("");
  const [open, setOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  const optionById = useMemo(() => {
    const m = new Map<string, MultiSelectOption>();
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

  // Close dropdown on outside click.
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
      if (options && !allowCustom) {
        // Constrained: only accept exact option matches via dropdown click.
        return;
      }
      add(v);
    } else if (e.key === "Backspace" && input === "" && value.length > 0) {
      remove(value[value.length - 1]);
    }
  }

  // Group filteredOptions by group label.
  const grouped = useMemo(() => {
    const out = new Map<string, MultiSelectOption[]>();
    for (const o of filteredOptions) {
      const k = o.group ?? "";
      const arr = out.get(k) ?? [];
      arr.push(o);
      out.set(k, arr);
    }
    return Array.from(out.entries());
  }, [filteredOptions]);

  return (
    <div ref={rootRef} className="relative">
      <div
        className={
          "min-h-7 flex flex-wrap items-center gap-1 px-1.5 py-1 " +
          "bg-bg-2 border border-border-soft rounded-md cursor-text " +
          (disabled ? "opacity-60 cursor-not-allowed" : "focus-within:border-border-strong")
        }
        onClick={() => inputRef.current?.focus()}
      >
        {value.map((id) => {
          const label = optionById.get(id)?.label ?? id;
          return (
            <span
              key={id}
              className="inline-flex items-center gap-1 h-5 px-1.5 text-[11px] text-text-0 bg-bg-3 border border-border-soft rounded-sm"
            >
              <span className="max-w-[160px] truncate">{label}</span>
              {!disabled && (
                <button
                  type="button"
                  className="text-text-3 hover:text-text-0"
                  aria-label={`Remove ${label}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    remove(id);
                  }}
                >
                  <Ic.plus className="rotate-45" />
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
          className="flex-1 min-w-[80px] h-5 bg-transparent outline-none text-[13px] text-text-0 placeholder:text-text-3"
        />
      </div>

      {open && options && filteredOptions.length > 0 && (
        <div className="absolute z-10 mt-1 w-full max-h-[220px] overflow-y-auto bg-bg-1 border border-border-soft rounded-md shadow-soft py-1">
          {grouped.map(([group, opts]) => (
            <div key={group}>
              {group && (
                <div className="px-2 pt-1.5 pb-0.5 text-[10px] uppercase tracking-[0.04em] text-text-3">
                  {group}
                </div>
              )}
              {opts.map((o) => (
                <button
                  key={o.id}
                  type="button"
                  className="w-full text-left px-2 py-1 text-[12.5px] text-text-1 hover:bg-bg-2 hover:text-text-0"
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
