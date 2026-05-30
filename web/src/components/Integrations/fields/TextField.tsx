// JSON Schema `string` (no enum) → Input.

import { GFormField, GInput } from "../../Goofy";

interface TextFieldProps {
  name: string;
  label?: string;
  value: string;
  onChange: (v: string) => void;
  hint?: string;
  error?: string | null;
  required?: boolean;
  placeholder?: string;
  disabled?: boolean;
  maxLength?: number;
}

export function TextField(p: TextFieldProps) {
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
        icon={null}
        value={p.value ?? ""}
        placeholder={p.placeholder}
        disabled={p.disabled}
        maxLength={p.maxLength}
        onChange={(e) => p.onChange(e.target.value)}
      />
    </GFormField>
  );
}
