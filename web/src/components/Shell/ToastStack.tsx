// Global toast outlet.
//
// Renders the stack of active toasts pulled from the `useToasts` store.
// Mounted exactly once at the app shell level (under the route gate so
// auth-gated views can fire toasts the same way as signed-in surfaces).
//
// Layout: bottom-right of the viewport, stacked top-to-bottom, with a
// safe-area inset so notched devices don't crop the latest toast.

import { useToasts } from "../../state/toasts";
import { GToast } from "../Goofy";

export function ToastStack() {
  const toasts = useToasts((s) => s.toasts);
  const dismiss = useToasts((s) => s.dismiss);

  if (toasts.length === 0) return null;

  return (
    <div
      // `pointer-events-none` on the wrapper lets clicks pass through
      // the empty space; individual toast cards re-enable pointer
      // events on themselves.
      className="pointer-events-none fixed z-[60] right-4 bottom-4 flex flex-col gap-2 max-w-[420px] w-full"
      style={{
        right: "max(1rem, env(safe-area-inset-right))",
        bottom: "max(1rem, env(safe-area-inset-bottom))",
      }}
    >
      {toasts.map((t) => (
        <div key={t.id} className="pointer-events-auto">
          <GToast
            tone={t.tone}
            title={t.title}
            sub={t.sub}
            onDismiss={() => dismiss(t.id)}
          />
        </div>
      ))}
    </div>
  );
}
