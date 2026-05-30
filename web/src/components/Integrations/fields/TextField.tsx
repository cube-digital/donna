// JSON Schema `string` (no enum) → Input.

import { Field } from "../../Ui/Field";
import { Input } from "../../Ui/Input";

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
    <Field
      label={p.label}
      hint={p.hint}
      error={p.error}
      required={p.required}
      htmlFor={p.name}
    >
      <Input
        id={p.name}
        name={p.name}
        value={p.value ?? ""}
        placeholder={p.placeholder}
        disabled={p.disabled}
        maxLength={p.maxLength}
        onChange={(e) => p.onChange(e.target.value)}
      />
    </Field>
  );
}
