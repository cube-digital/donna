// Lifts the OAuth popup + postMessage listener from the legacy
// IntegrationModal so multiple surfaces (detail page, future onboarding flow)
// can reuse it without duplicating state.
//
// Usage:
//   const { connect, busy, error } = useOAuthConnect(slug, () => reload());

import { useCallback, useEffect, useState } from "react";

import { connectIntegration } from "../../api/integrations";

interface OAuthReturnMessage {
  kind: "donna.oauth.return";
  status: "ok" | "error";
  slug?: string;
  detail?: string;
  error?: string;
}

export function useOAuthConnect(
  slug: string,
  onSuccess?: () => void | Promise<void>,
) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [popup, setPopup] = useState<Window | null>(null);

  // postMessage from the /oauth/return shim window
  useEffect(() => {
    function onMsg(e: MessageEvent) {
      if (e.origin !== window.location.origin) return;
      const payload = e.data as OAuthReturnMessage | undefined;
      if (payload?.kind !== "donna.oauth.return") return;
      setBusy(false);
      setPopup(null);
      if (payload.status === "ok") {
        void onSuccess?.();
      } else {
        setError(payload.detail || payload.error || "OAuth failed.");
      }
    }
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, [onSuccess]);

  // Detect popup-closed-without-completion so we re-enable the button.
  useEffect(() => {
    if (!popup) return;
    const t = setInterval(() => {
      if (popup.closed) {
        setBusy(false);
        setPopup(null);
        clearInterval(t);
      }
    }, 500);
    return () => clearInterval(t);
  }, [popup]);

  const connect = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const { authorize_url } = await connectIntegration(slug);
      const w = window.open(
        authorize_url,
        "_blank",
        "width=520,height=620,noopener=no",
      );
      if (!w) {
        setError("Couldn't open the OAuth popup — check your browser settings.");
        setBusy(false);
        return;
      }
      setPopup(w);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }, [slug]);

  return { connect, busy, error, setError };
}
