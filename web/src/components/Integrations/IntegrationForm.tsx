// Schema-driven config form for one connector.
//
// Reads `provider.config_schema` (JSON Schema, shipped by the backend retrieve
// endpoint), walks `properties`, and dispatches each field to:
//
//   1. A connector-specific picker from `pickers/registry` if registered.
//   2. The closest generic primitive (Select/Number/Toggle/MultiSelect/Text).
//
// Conditional fields (`allOf` with `if`/`then` clauses, used by Gmail/Drive)
// are evaluated minimally: if the predicate matches the current value, the
// `then.properties` keys are surfaced; otherwise they're hidden AND stripped
// from the submitted payload to avoid sending stale state.

import { useEffect, useMemo, useState } from "react";

import { updateSubscription } from "../../api/integrations";
import type {
  Connection,
  ConfigSchema,
  IntegrationProvider,
} from "../../types";
import { GButton } from "../Goofy";

import { MultiSelectField } from "./fields/MultiSelectField";
import { NumberField } from "./fields/NumberField";
import { PickerField } from "./fields/PickerField";
import { SelectField } from "./fields/SelectField";
import { TextField } from "./fields/TextField";
import { ToggleField } from "./fields/ToggleField";
import { findPicker } from "./pickers/registry";

// ── Schema helpers ───────────────────────────────────────────────────────────

interface SchemaNode {
  type?: string | string[];
  enum?: string[];
  items?: SchemaNode;
  properties?: Record<string, SchemaNode>;
  required?: string[];
  minimum?: number;
  maximum?: number;
  description?: string;
  default?: unknown;
}

interface RootSchema extends SchemaNode {
  allOf?: Array<{
    if?: { properties?: Record<string, { const?: unknown; enum?: unknown[] }> };
    then?: { required?: string[] };
    else?: { required?: string[] };
  }>;
}

function humanize(s: string): string {
  return s
    .replace(/[_.]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

// Evaluate which keys are visible given the conditional clauses + current value.
// Heuristic: a property is hidden if it appears in a `then.required` whose
// `if` predicate does NOT match the current value. Keys with no clause are
// always visible.
function visibleKeys(
  schema: RootSchema,
  value: Record<string, unknown>,
): Set<string> {
  const all = new Set<string>(Object.keys(schema.properties ?? {}));
  const gated = new Map<string, boolean>();

  for (const clause of schema.allOf ?? []) {
    const predicate = clause.if?.properties ?? {};
    let matches = true;
    for (const [pkey, pcond] of Object.entries(predicate)) {
      const v = value[pkey];
      if ("const" in pcond && pcond.const !== v) matches = false;
      if (Array.isArray(pcond.enum) && !pcond.enum.includes(v as never)) {
        matches = false;
      }
    }
    for (const key of clause.then?.required ?? []) {
      // Visible iff some clause matches it; remember the OR.
      gated.set(key, gated.get(key) === true || matches);
    }
  }

  for (const [key, isVisible] of gated) {
    if (!isVisible) all.delete(key);
  }
  return all;
}

// Drop keys that are conditionally hidden so we don't PATCH stale data.
function prune(
  value: Record<string, unknown>,
  visible: Set<string>,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(value)) {
    if (visible.has(k)) out[k] = v;
  }
  return out;
}

// ── Component ────────────────────────────────────────────────────────────────

interface IntegrationFormProps {
  provider: IntegrationProvider;
  connection: Connection;
  onSaved?: (next: Connection) => void;
}

export function IntegrationForm({ provider, connection, onSaved }: IntegrationFormProps) {
  const schema = (provider.config_schema ?? null) as RootSchema | null;

  // Hydrate from existing config, falling back to provider defaults.
  const initial = useMemo<Record<string, unknown>>(
    () => ({
      ...(provider.default_config ?? {}),
      ...(connection.config ?? {}),
    }),
    [connection.config, provider.default_config],
  );
  const [value, setValue] = useState(initial);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset when the underlying connection changes (e.g. after disconnect/reconnect).
  useEffect(() => {
    setValue(initial);
    setDirty(false);
    setError(null);
  }, [initial]);

  if (!schema || !schema.properties) {
    return (
      <div className="text-[12.5px] text-text-3 italic">
        This integration has no user-editable configuration.
      </div>
    );
  }

  const visible = visibleKeys(schema, value);
  const requiredTop = new Set(schema.required ?? []);

  function patch(key: string, v: unknown) {
    setValue((prev) => ({ ...prev, [key]: v }));
    setDirty(true);
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const payload = prune(value, visible);
      const next = await updateSubscription(provider.slug, payload);
      setDirty(false);
      onSaved?.(next);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={save} className="flex flex-col gap-4 max-w-[520px]">
      {error && (
        <div className="py-1.5 px-2 rounded-md border border-danger text-danger text-[12px] bg-[color-mix(in_oklch,var(--danger)_8%,transparent)]">
          {error}
        </div>
      )}

      {Object.entries(schema.properties).map(([key, sub]) => {
        if (!visible.has(key)) return null;

        const label = humanize(key);
        const hint = (sub as SchemaNode).description;
        const required = requiredTop.has(key);
        const current = value[key];

        // 1. Connector-specific picker?
        if (findPicker(provider.slug, key)) {
          return (
            <PickerField
              key={key}
              slug={provider.slug}
              name={key}
              value={current}
              onChange={(v) => patch(key, v)}
              schema={sub as ConfigSchema}
              config={value}
              label={label}
              hint={hint}
            />
          );
        }

        // 2. Enum → Select
        if (Array.isArray(sub.enum)) {
          return (
            <SelectField
              key={key}
              name={key}
              label={label}
              value={(current as string) ?? ""}
              options={sub.enum}
              onChange={(v) => patch(key, v)}
              hint={hint}
              required={required}
            />
          );
        }

        const type = Array.isArray(sub.type) ? sub.type[0] : sub.type;

        // 3. Boolean → Toggle
        if (type === "boolean") {
          return (
            <ToggleField
              key={key}
              name={key}
              label={label}
              value={!!current}
              onChange={(v) => patch(key, v)}
              hint={hint}
            />
          );
        }

        // 4. Integer / number → NumberField
        if (type === "integer" || type === "number") {
          return (
            <NumberField
              key={key}
              name={key}
              label={label}
              value={typeof current === "number" ? current : undefined}
              min={sub.minimum}
              max={sub.maximum}
              step={type === "integer" ? 1 : undefined}
              onChange={(v) => patch(key, v)}
              hint={hint}
              required={required}
            />
          );
        }

        // 5. Array of strings → MultiSelect (free text)
        if (type === "array" && sub.items?.type === "string") {
          return (
            <MultiSelectField
              key={key}
              name={key}
              label={label}
              value={Array.isArray(current) ? (current as string[]) : []}
              onChange={(v) => patch(key, v)}
              hint={hint}
              allowCustom
              placeholder="Type and press Enter"
            />
          );
        }

        // 6. String → TextField
        if (type === "string") {
          return (
            <TextField
              key={key}
              name={key}
              label={label}
              value={(current as string) ?? ""}
              onChange={(v) => patch(key, v)}
              hint={hint}
              required={required}
            />
          );
        }

        // 7. Fallback — unknown shape. Render as read-only JSON so the user
        //    can still inspect it without breaking the form.
        return (
          <div key={key} className="flex flex-col gap-1.5">
            <div className="text-[11px] uppercase tracking-[0.04em] text-text-3 font-medium">
              {label}
            </div>
            <pre className="text-[12px] text-text-2 bg-bg-2 border border-border-soft rounded-md p-2 overflow-x-auto">
              {JSON.stringify(current, null, 2)}
            </pre>
          </div>
        );
      })}

      <div className="flex items-center gap-2 pt-2 border-t border-border-soft">
        <GButton type="submit" variant="blue" disabled={!dirty || saving}>
          {saving ? "Saving…" : "Save changes"}
        </GButton>
        {dirty && (
          <GButton
            type="button"
            variant="ghost"
            onClick={() => {
              setValue(initial);
              setDirty(false);
              setError(null);
            }}
          >
            Discard
          </GButton>
        )}
      </div>
    </form>
  );
}
