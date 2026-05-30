// Custom-widget host. Renders the connector-specific picker from the registry
// if one exists for `(slug, name)`; otherwise the caller is responsible for
// falling back to a generic field.

import { Suspense } from "react";

import type { ConfigSchema } from "../../../types";
import { findPicker } from "../pickers/registry";

interface PickerFieldProps {
  slug: string;
  name: string;
  value: unknown;
  onChange: (v: unknown) => void;
  schema: ConfigSchema | null | undefined;
  config: Record<string, unknown>;
  label?: string;
  hint?: string;
  disabled?: boolean;
}

export function PickerField(p: PickerFieldProps) {
  const Picker = findPicker(p.slug, p.name);
  if (!Picker) return null;
  return (
    <Suspense
      fallback={
        <div className="text-[12.5px] text-text-3 py-2">Loading {p.label ?? p.name}…</div>
      }
    >
      <Picker
        name={p.name}
        value={p.value}
        onChange={p.onChange}
        schema={p.schema}
        config={p.config}
        label={p.label}
        hint={p.hint}
        disabled={p.disabled}
      />
    </Suspense>
  );
}
