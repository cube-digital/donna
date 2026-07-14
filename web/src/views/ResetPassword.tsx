// ResetPassword — public page for /password/reset?token=<key>.
//
// The recover email links here. Enter a new password → POST
// /api/auth/password/confirm → on success, back to sign in.

import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { confirmPasswordReset } from "../api/auth";
import { GButton, GCard, GFormField, GInput, GoofyTheme, Sparkle } from "../components/Goofy";

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

export default function ResetPassword() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get("token") ?? "";

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    if (password !== confirm) {
      setError("Passwords don't match.");
      return;
    }
    setSubmitting(true);
    try {
      await confirmPasswordReset(token, password);
      setDone(true);
    } catch (err) {
      setError(
        err instanceof ApiError || err instanceof Error
          ? err.message
          : "Couldn't reset your password. The link may have expired.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <GoofyTheme paper className="min-h-screen grid place-items-center p-6 text-text-1">
      <div className="w-[420px] flex flex-col gap-5">
        <BrandMark />
        <GCard className="flex flex-col gap-4">
          {!token ? (
            <div>
              <div className="font-display font-semibold text-[20px] text-text-0 mb-1">
                Invalid reset link
              </div>
              <div className="text-[13px] text-text-2">
                This link is missing its token. Request a new one from the sign-in
                page.
              </div>
            </div>
          ) : done ? (
            <>
              <div>
                <div className="font-display font-semibold text-[20px] text-text-0 mb-1">
                  Password updated
                </div>
                <div className="text-[13px] text-text-2">
                  Your password has been changed. You can sign in with it now.
                </div>
              </div>
              <GButton
                variant="ai"
                size="lg"
                onClick={() => navigate("/auth")}
                className="w-full justify-center"
              >
                Go to sign in
              </GButton>
            </>
          ) : (
            <>
              <div>
                <div className="font-display font-semibold text-[20px] text-text-0 mb-1">
                  Set a new password
                </div>
                <div className="text-[13px] text-text-2">
                  Choose a new password for your Donna account.
                </div>
              </div>
              <form onSubmit={handleSubmit} className="flex flex-col gap-3" noValidate>
                <GFormField label="New password">
                  <GInput
                    type="password"
                    autoComplete="new-password"
                    required
                    minLength={8}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="At least 8 characters"
                    icon={null}
                  />
                </GFormField>
                <GFormField label="Confirm password">
                  <GInput
                    type="password"
                    autoComplete="new-password"
                    required
                    value={confirm}
                    onChange={(e) => setConfirm(e.target.value)}
                    placeholder="Re-enter your password"
                    icon={null}
                  />
                </GFormField>
                {error && (
                  <div
                    role="alert"
                    aria-live="assertive"
                    className="text-danger text-[12.5px] leading-[1.45]"
                  >
                    {error}
                  </div>
                )}
                <GButton
                  type="submit"
                  variant="ai"
                  size="lg"
                  disabled={submitting}
                  className="w-full justify-center mt-1"
                >
                  {submitting ? "Updating…" : "Update password"}
                </GButton>
              </form>
            </>
          )}
        </GCard>
      </div>
    </GoofyTheme>
  );
}
