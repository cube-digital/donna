// AcceptInvitation — public landing for /invitations/<token>/accept.
//
// Flow:
//   1. On mount, fetch preview (no auth).
//   2. If not logged in: prompt to sign in as the invited email.
//   3. If logged in with matching email: show "Accept" button.
//   4. If logged in with wrong email: show sign-out + sign-in-with prompt.

import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { acceptInvitation, inspectInvitation } from "../api/workspaces";
import { GButton, GCard, GoofyTheme, Sparkle } from "../components/Goofy";
import { useAuth } from "../state/auth";
import type { WorkspaceInvitationPreview } from "../types";

/** Donna brand mark — gold sparkle medallion + Fredoka wordmark + Caveat tagline.
 *  Matches the Auth screen so the invite flow feels first-party. */
function BrandMark() {
  return (
    <div className="flex items-center gap-3">
      <div className="w-12 h-12 grid place-items-center bg-pop-sun border-2 border-ink rounded-[12px] shadow-ink-2 text-on-bright">
        <Sparkle width={26} height={26} />
      </div>
      <div>
        <div className="font-display font-semibold text-[30px] text-text-0 leading-none tracking-[-0.01em]">
          Donna
        </div>
        <div className="font-hand font-bold text-[19px] text-ai-deep mt-1 leading-none">
          team chat with AI teammates
        </div>
      </div>
    </div>
  );
}

export default function AcceptInvitation() {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const me = useAuth((s) => s.user);
  const signOut = useAuth((s) => s.signOut);
  const [preview, setPreview] = useState<WorkspaceInvitationPreview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!token) return;
    inspectInvitation(token)
      .then(setPreview)
      .catch((e: unknown) =>
        setErr(e instanceof Error ? e.message : "Invitation invalid."),
      );
  }, [token]);

  const accept = async () => {
    if (!token) return;
    setBusy(true);
    setErr(null);
    try {
      const { workspace_id } = await acceptInvitation(token);
      navigate(`/?workspace=${workspace_id}`);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Failed to accept invitation.");
    } finally {
      setBusy(false);
    }
  };

  const loginRedirect = () => {
    const ret = window.location.pathname;
    navigate(`/auth?return=${encodeURIComponent(ret)}`);
  };

  // Sign out, then bounce to sign-in with a return to this page so the invitee
  // lands back here after logging in with the invited email.
  const switchAccount = () => {
    signOut();
    loginRedirect();
  };

  if (err) {
    return (
      <GoofyTheme paper className="min-h-screen grid place-items-center p-6 text-text-1">
        <div className="w-[420px] flex flex-col gap-5">
          <BrandMark />
          <GCard className="text-center">
            <div className="font-display font-semibold text-[18px] mb-2">
              Invitation invalid
            </div>
            <div className="text-[13px] text-text-2">{err}</div>
          </GCard>
        </div>
      </GoofyTheme>
    );
  }

  if (!preview) {
    return (
      <GoofyTheme paper className="min-h-screen grid place-items-center p-6 text-text-1">
        <div className="text-[13px] text-text-2">Loading invitation…</div>
      </GoofyTheme>
    );
  }

  const isLoggedIn = !!me;
  const emailMatches =
    isLoggedIn && me.email.toLowerCase() === preview.email.toLowerCase();

  return (
    <GoofyTheme paper className="min-h-screen grid place-items-center p-6 text-text-1">
      <div className="w-[420px] flex flex-col gap-5">
        <BrandMark />
        <GCard className="flex flex-col gap-4">
          <div>
            <div className="font-display font-semibold text-[20px] text-text-0 mb-1">
              Join {preview.workspace_name}
            </div>
            <div className="text-[13px] text-text-2">
              {preview.invited_by} invited you to join {preview.workspace_name} on
              Donna.
            </div>
          </div>

          {!isLoggedIn && (
            <>
              <div className="text-[13px] text-text-1">
                Sign in as <strong>{preview.email}</strong> to accept.
              </div>
              <GButton variant="ai" onClick={loginRedirect}>
                Continue to sign in
              </GButton>
            </>
          )}

          {isLoggedIn && emailMatches && (
            <GButton variant="ai" onClick={accept} disabled={busy}>
              {busy ? "Accepting…" : "Accept invitation"}
            </GButton>
          )}

          {isLoggedIn && !emailMatches && (
            <>
              <div className="text-[13px] text-danger">
                This invitation is for <strong>{preview.email}</strong>, but
                you're signed in as{" "}
                <strong>{me.email || "a different account"}</strong>. Sign out
                and sign back in with the invited email.
              </div>
              <GButton variant="default" onClick={switchAccount}>
                Sign out &amp; switch account
              </GButton>
            </>
          )}

          <div className="text-[11px] text-text-3 text-center">
            Expires {new Date(preview.expires_at).toLocaleDateString()}
          </div>
        </GCard>
      </div>
    </GoofyTheme>
  );
}
