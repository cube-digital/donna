// Sliding-pill toggle, Linear-style. 28x16 outer, 12x12 thumb.
//
// Uncontrolled with onChange via the parent. Rendered as a real <button>
// so keyboard space/enter activate it; aria-pressed reflects state.

interface ToggleProps {
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  "aria-label"?: string;
}

export function Toggle({ checked, onChange, disabled, ...aria }: ToggleProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={aria["aria-label"]}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={
        "relative w-7 h-4 rounded-full transition-colors " +
        (checked ? "bg-text-0" : "bg-bg-3") +
        " disabled:opacity-50 disabled:cursor-not-allowed"
      }
    >
      <span
        className={
          "absolute top-0.5 left-0.5 w-3 h-3 rounded-full bg-bg-0 transition-transform " +
          (checked ? "translate-x-3" : "translate-x-0")
        }
      />
    </button>
  );
}
