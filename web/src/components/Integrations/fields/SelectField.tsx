// JSON Schema `string` with `enum` → Select.
//
// `enumLabels` is optional. When supplied, used to render human-friendly text
// in lieu of the raw enum value. Falls back to a humanize() of the value.

import { Field } from "../../Ui/Field";
import { Select } from "../../Ui/Select";

function humanize(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

interface SelectFieldProps {
  name: string;
  label?: string;
  value: string;
  options: string[];
  onChange: (v: string) => void;
  enumLabels?: Record<string, string>;
  hint?: string;
  error?: string | null;
  required?: boolean;
  disabled?: boolean;
}

export function SelectField(p: SelectFieldProps) {
  return (
    <Field
      label={p.label}
      hint={p.hint}
      error={p.error}
      required={p.required}
      htmlFor={p.name}
    >
      <Select
        id={p.name}
        name={p.name}
        value={p.value ?? ""}
        disabled={p.disabled}
        onChange={(e) => p.onChange(e.target.value)}
      >
        {p.options.map((opt) => (
          <option key={opt} value={opt}>
            {p.enumLabels?.[opt] ?? humanize(opt)}
          </option>
        ))}
      </Select>
    </Field>
  );
}
