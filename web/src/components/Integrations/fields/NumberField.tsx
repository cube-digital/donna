// JSON Schema `integer` / `number` → Input type=number.
//
// Empty string parses to undefined so optional ints can be cleared cleanly.

import { GFormField, GInput } from "../../Goofy";

interface NumberFieldProps {
  name: string;
  label?: string;
  value: number | undefined;
  onChange: (v: number | undefined) => void;
  hint?: string;
  error?: string | null;
  required?: boolean;
  disabled?: boolean;
  min?: number;
  max?: number;
  step?: number;
}

export function NumberField(p: NumberFieldProps) {
  return (
    <GFormField
      label={p.label}
      hint={p.hint}
      error={p.error}
      required={p.required}
      htmlFor={p.name}
    >
      <GInput
        id={p.name}
        name={p.name}
        type="number"
        icon={null}
        value={p.value === undefined || Number.isNaN(p.value) ? "" : p.value}
        min={p.min}
        max={p.max}
        step={p.step ?? 1}
        disabled={p.disabled}
        onChange={(e) => {
          const raw = e.target.value;
          if (raw === "") return p.onChange(undefined);
          const n = Number(raw);
          p.onChange(Number.isNaN(n) ? undefined : n);
        }}
        className="max-w-[180px]"
      />
    </GFormField>
  );
}
