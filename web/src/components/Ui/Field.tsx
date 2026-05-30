// Form field wrapper. Label above, control(s) below, hint + error beneath.
// Standard row spacing matches VIBE.md.

interface FieldProps {
  label?: string;
  hint?: string;
  error?: string | null;
  htmlFor?: string;
  required?: boolean;
  children: React.ReactNode;
}

export function Field({ label, hint, error, htmlFor, required, children }: FieldProps) {
  return (
    <div className="flex flex-col gap-1.5">
      {label && (
        <label
          htmlFor={htmlFor}
          className="text-[11px] uppercase tracking-[0.04em] text-text-3 font-medium"
        >
          {label}
          {required ? <span className="text-danger ml-1">*</span> : null}
        </label>
      )}
      {children}
      {error ? (
        <div className="text-[12px] text-danger">{error}</div>
      ) : hint ? (
        <div className="text-[12px] text-text-3">{hint}</div>
      ) : null}
    </div>
  );
}
