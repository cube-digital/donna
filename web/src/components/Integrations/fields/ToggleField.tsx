// JSON Schema `boolean` → Toggle.

import { GFormField, GSwitch } from "../../Goofy";

interface ToggleFieldProps {
  name: string;
  label?: string;
  value: boolean;
  onChange: (v: boolean) => void;
  hint?: string;
  error?: string | null;
  disabled?: boolean;
}

export function ToggleField(p: ToggleFieldProps) {
  return (
    <GFormField label={p.label} hint={p.hint} error={p.error}>
      <div className="flex items-center gap-2">
        <GSwitch
          on={!!p.value}
          disabled={p.disabled}
          onChange={p.onChange}
          aria-label={p.label || p.name}
        />
        <span className="text-[13px] text-text-1">
          {p.value ? "On" : "Off"}
        </span>
      </div>
    </GFormField>
  );
}
