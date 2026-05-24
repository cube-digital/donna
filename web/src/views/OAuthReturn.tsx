// Landing page for backend OAuth callbacks that 302 to the frontend.
//
// Two flavours both arrive here:
//   1. Google login        → backend redirects with ?access=…&refresh=…
//      We persist tokens and bounce to /.
//   2. Provider connect    → backend redirects with ?status=ok|error&slug=<slug>
//      We close the window if we were opened as a popup; otherwise bounce.
//
// If you opened this in a popup (window.opener present), post a message
// to the opener and close — the opener listens for "donna.oauth.return".

import { useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../state/auth";

export default function OAuthReturn() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const setSignedIn = useAuth((s) => s.setSignedIn);

  useEffect(() => {
    const access = params.get("access");
    const refresh = params.get("refresh");

    if (access && refresh) {
      setSignedIn(access, refresh);
    }

    const payload = {
      kind: "donna.oauth.return",
      status: params.get("status") ?? (access ? "ok" : "unknown"),
      slug: params.get("slug"),
      error: params.get("error"),
    };

    if (window.opener && !window.opener.closed) {
      try {
        window.opener.postMessage(payload, window.location.origin);
      } catch {
        /* same-origin only; ignore */
      }
      window.close();
      return;
    }

    navigate(access ? "/" : "/auth", { replace: true });
  }, [navigate, params, setSignedIn]);

  return (
    <div className="min-h-screen grid place-items-center text-text-2 text-[13px]">
      Completing sign-in…
    </div>
  );
}
