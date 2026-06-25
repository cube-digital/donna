// AcceptInvitation — public landing for ?/invitations/<token>/accept.
//
// Flow:
//   1. On mount, fetch preview (no auth).
//   2. If not logged in: redirect to /auth?return=<current url>.
//   3. If logged in with matching email: show "Accept" button.
//   4. If logged in with wrong email: show log-out + log-in-with prompt.

import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { acceptInvitation, inspectInvitation } from "../api/workspaces";
import { useAuth } from "../state/auth";
import type { WorkspaceInvitationPreview } from "../types";

export default function AcceptInvitation() {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const me = useAuth((s) => s.user);
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

  if (err) {
    return (
      <div className="min-h-screen grid place-items-center bg-bg-0 p-6">
        <div className="bg-bg-1 border-2 border-ink rounded-[14px] shadow-ink-2 p-6 max-w-md text-center">
          <div className="font-display font-semibold text-[18px] mb-2">
            Invitation invalid
          </div>
          <div className="text-[13px] text-text-2">{err}</div>
        </div>
      </div>
    );
  }

  if (!preview) {
    return (
      <div className="min-h-screen grid place-items-center bg-bg-0">
        <div className="text-[13px] text-text-2">Loading invitation…</div>
      </div>
    );
  }

  const isLoggedIn = !!me;
  const emailMatches =
    isLoggedIn && me.email.toLowerCase() === preview.email.toLowerCase();

  return (
    <div className="min-h-screen grid place-items-center bg-bg-0 p-6">
      <div className="bg-bg-1 border-2 border-ink rounded-[14px] shadow-ink-2 p-6 max-w-md w-full">
        <div className="font-display font-semibold text-[20px] mb-1">
          Join {preview.workspace_name}
        </div>
        <div className="text-[13px] text-text-2 mb-5">
          {preview.invited_by} invited you to join {preview.workspace_name} on
          Donna.
        </div>

        {!isLoggedIn && (
          <>
            <div className="text-[13px] mb-3">
              Sign in as <strong>{preview.email}</strong> to accept.
            </div>
            <button
              type="button"
              onClick={loginRedirect}
              className="w-full px-4 py-2 text-[14px] border-2 border-ink rounded-[8px] bg-ai text-white"
            >
              Continue to sign in
            </button>
          </>
        )}

        {isLoggedIn && emailMatches && (
          <button
            type="button"
            onClick={accept}
            disabled={busy}
            className="w-full px-4 py-2 text-[14px] border-2 border-ink rounded-[8px] bg-ai text-white disabled:opacity-50"
          >
            {busy ? "Accepting…" : "Accept invitation"}
          </button>
        )}

        {isLoggedIn && !emailMatches && (
          <div className="text-[13px] text-danger">
            This invitation is for <strong>{preview.email}</strong>, but you're
            signed in as <strong>{me.email}</strong>. Sign out and sign back in
            with the invited email.
          </div>
        )}

        <div className="mt-4 text-[11px] text-text-2 text-center">
          Expires {new Date(preview.expires_at).toLocaleDateString()}
        </div>
      </div>
    </div>
  );
}
