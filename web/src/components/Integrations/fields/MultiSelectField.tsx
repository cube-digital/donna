// JSON Schema `array<string>` → MultiSelect. Free-text by default; pass
// `options` for constrained selection (used by Gmail labels picker).

import { GFormField, GMultiSelect, type GMultiSelectOption } from "../../Goofy";

interface MultiSelectFieldProps {
  name: string;
  label?: string;
  value: string[];
  onChange: (v: string[]) => void;
  options?: GMultiSelectOption[];
  placeholder?: string;
  hint?: string;
  error?: string | null;
  disabled?: boolean;
  allowCustom?: boolean;
}

export function MultiSelectField(p: MultiSelectFieldProps) {
  return (
    <GFormField label={p.label} hint={p.hint} error={p.error}>
      <GMultiSelect
        value={p.value ?? []}
        onChange={p.onChange}
        options={p.options}
        placeholder={p.placeholder}
        disabled={p.disabled}
        allowCustom={p.allowCustom}
      />
    </GFormField>
  );
}
