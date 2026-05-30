// Gmail labels — async MultiSelect.
// Picker endpoint: GET /integrations/gmail/subscription/picker/labels
//   → { labels: [{ id, name, type: "system" | "user" }, ...] }
// Selected value persisted as `string[]` of label ids on `config.labels`.

import { useEffect, useState } from "react";

import { getPicker } from "../../../api/integrations";
import { MultiSelectField } from "../fields/MultiSelectField";
import type { PickerProps } from "./registry";

interface RawLabel {
  id: string;
  name: string;
  type?: "system" | "user";
}

export function GmailLabelsPicker(p: PickerProps) {
  const [options, setOptions] = useState<{ id: string; label: string; group?: string }[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getPicker("gmail", "labels")
      .then((data) => {
        if (cancelled) return;
        const labels = (data.labels as RawLabel[] | undefined) ?? [];
        setOptions(
          labels.map((l) => ({
            id: l.id,
            label: l.name,
            group: l.type === "system" ? "System" : "Your labels",
          })),
        );
      })
      .catch((e) => !cancelled && setErr(e?.message ?? "Failed to load labels"))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <MultiSelectField
      name={p.name}
      label={p.label}
      hint={loading ? "Loading labels…" : err ?? p.hint}
      value={Array.isArray(p.value) ? (p.value as string[]) : []}
      onChange={(v) => p.onChange(v)}
      options={options}
      placeholder="Pick labels…"
      disabled={p.disabled || loading}
    />
  );
}
