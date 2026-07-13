// Starts an integration OAuth connect via a FULL-PAGE redirect — the same
// model as Google login in Auth.tsx (window.location.assign).
//
// Why not a popup (the previous approach):
//   - `window.open` called after an `await` loses the browser's user-activation
//     token, so Chrome/Safari block it ("Couldn't open the OAuth popup").
//   - The popup's completion signal was a same-origin `postMessage` from an
//     /oauth/return shim. That breaks whenever the API host differs from the
//     SPA host (e.g. local dev: SPA on :5173, API on the cluster) — the popup
//     lands on the API host and can't message back.
//
// We pass our own origin as `redirect_to` so the backend callback 302s back to
// THIS frontend: `${origin}/integrations/<slug>?status=connected|error`. The
// IntegrationDetail route reloads on mount and reflects the connected state.

import { useCallback, useState } from "react";

import { connectIntegration } from "../../api/integrations";

export function useOAuthConnect(
  slug: string,
  // Kept for call-site compatibility. With a full-page redirect the page
  // remounts on return and reloads its own state, so no callback is needed.
  _onSuccess?: () => void | Promise<void>,
) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const connect = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const returnTo = `${window.location.origin}/integrations`;
      const { authorize_url } = await connectIntegration(slug, returnTo);
      // Full-page navigation to the provider's consent screen.
      window.location.assign(authorize_url);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }, [slug]);

  return { connect, busy, error, setError };
}
