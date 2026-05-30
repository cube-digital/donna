// JSON Schema `array<string>` → MultiSelect. Free-text by default; pass
// `options` for constrained selection (used by Gmail labels picker).

import { Field } from "../../Ui/Field";
import { MultiSelect, type MultiSelectOption } from "../../Ui/MultiSelect";

interface MultiSelectFieldProps {
  name: string;
  label?: string;
  value: string[];
  onChange: (v: string[]) => void;
  options?: MultiSelectOption[];
  placeholder?: string;
  hint?: string;
  error?: string | null;
  disabled?: boolean;
  allowCustom?: boolean;
}

export function MultiSelectField(p: MultiSelectFieldProps) {
  return (
    <Field label={p.label} hint={p.hint} error={p.error}>
      <MultiSelect
        value={p.value ?? []}
        onChange={p.onChange}
        options={p.options}
        placeholder={p.placeholder}
        disabled={p.disabled}
        allowCustom={p.allowCustom}
      />
    </Field>
  );
}
