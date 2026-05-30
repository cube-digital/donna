// Per-(connector, field) custom widget registry.
//
// IntegrationForm's renderField checks this map FIRST before falling back to
// the generic schema-driven dispatcher. Add an entry here for any field that
// needs vendor-aware UX (label dropdown, folder tree, etc.).
//
// Keep this module light — heavy picker components import lazily inside the
// component implementation, not at module evaluation time.

import { lazy, type LazyExoticComponent } from "react";

import type { ConfigSchema } from "../../../types";

// Common props the form passes to every picker. Pickers may ignore most.
export interface PickerProps {
  name: string;
  value: unknown;
  onChange: (v: unknown) => void;
  schema: ConfigSchema | null | undefined;
  // The full Connection config — lets pickers branch on sibling field values
  // (e.g. only fetch labels when mode === "subscriptions").
  config: Record<string, unknown>;
  label?: string;
  hint?: string;
  disabled?: boolean;
}

export type PickerComponent = LazyExoticComponent<
  (p: PickerProps) => JSX.Element | null
>;

type Registry = Record<string, Record<string, PickerComponent>>;

export const PICKERS: Registry = {
  gmail: {
    labels: lazy(() =>
      import("./GmailLabelsPicker").then((m) => ({ default: m.GmailLabelsPicker })),
    ),
  },
  drive: {
    folders: lazy(() =>
      import("./DriveFoldersPicker").then((m) => ({ default: m.DriveFoldersPicker })),
    ),
  },
};

export function findPicker(slug: string, field: string): PickerComponent | null {
  return PICKERS[slug]?.[field] ?? null;
}
