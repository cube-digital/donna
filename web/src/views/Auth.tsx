// Sign-in / sign-up screen.
//
// One centered dark card on a `--bg-0` page. Tab-toggles between the two
// modes — no router-nested routes; the App route gate gives us `/auth/*`
// and we own the inside.
//
// On signup we automatically sign in with the same credentials so the
// user lands in the workspace picker instead of being asked to type the
// password again — typical SaaS flow.
//
// Google OAuth: GET /api/auth/google/login returns an authorization_url;
// we full-page redirect (no popup) so the cookie scope and CSRF state
// stays simple. The backend OAuth callback eventually 302s back to
// /oauth/return?access=…&refresh=… which OAuthReturn.tsx persists.

import { useState, type FormEvent } from "react";
import { ApiError } from "../api/client";
import { googleStartUrl, signin, signup } from "../api/auth";
import { useAuth } from "../state/auth";
import { Sparkle } from "../components/Goofy";

type Mode = "signin" | "signup";

// Class fragments reused below — hoisted to keep the JSX readable.
const TAB_BASE =
  "h-8 rounded-md text-[13px] font-medium text-text-2 cursor-pointer";
const TAB_ACTIVE = "bg-bg-4 text-text-0 shadow-soft";
const INPUT_CLASS =
  "h-10 w-full bg-bg-2 border border-border-soft rounded-md px-3 text-sm text-text-0";
const LABEL_CLASS =
  "text-[11px] tracking-[0.04em] uppercase text-text-3 font-semibold";

export default function Auth() {
  const setSignedIn = useAuth((s) => s.setSignedIn);

  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      if (mode === "signup") {
        await signup({ email, full_name: fullName, password });
      }
      const tokens = await signin({ email, password });
      setSignedIn(tokens.access, tokens.refresh);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Something went wrong";
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleGoogle() {
    setError(null);
    try {
      const url = await googleStartUrl();
      window.location.assign(url);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Couldn't start Google sign-in";
      setError(msg);
    }
  }

  return (
    <div className="min-h-screen bg-bg-0 text-text-1 grid place-items-center p-6">
      <div className="w-[360px] bg-bg-1 border border-border-strong rounded-2xl p-7 shadow-elevated flex flex-col gap-[18px]">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-md grid place-items-center bg-ai-bg text-ai border border-ai-glow">
            <Sparkle width={18} height={18} />
          </div>
          <div>
            <div className="text-lg font-semibold text-text-0 tracking-[-0.01em] leading-[1.1]">
              Donna
            </div>
            <div className="text-[12px] text-text-3 mt-0.5">
              Team chat with AI teammates
            </div>
          </div>
        </div>

        <div
          className="grid grid-cols-2 gap-0.5 bg-bg-2 border border-border-soft rounded-md p-[3px]"
          role="tablist"
        >
          <button
            type="button"
            role="tab"
            aria-selected={mode === "signin"}
            onClick={() => setMode("signin")}
            className={`${TAB_BASE}${mode === "signin" ? ` ${TAB_ACTIVE}` : ""}`}
          >
            Sign in
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "signup"}
            onClick={() => setMode("signup")}
            className={`${TAB_BASE}${mode === "signup" ? ` ${TAB_ACTIVE}` : ""}`}
          >
            Sign up
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-3" noValidate>
          {mode === "signup" && (
            <label className="flex flex-col gap-1.5">
              <span className={LABEL_CLASS}>Full name</span>
              <input
                type="text"
                autoComplete="name"
                required
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                className={INPUT_CLASS}
                placeholder="Jane Doe"
              />
            </label>
          )}

          <label className="flex flex-col gap-1.5">
            <span className={LABEL_CLASS}>Email</span>
            <input
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className={INPUT_CLASS}
              placeholder="you@company.com"
            />
          </label>

          <label className="flex flex-col gap-1.5">
            <span className={LABEL_CLASS}>Password</span>
            <input
              type="password"
              autoComplete={mode === "signin" ? "current-password" : "new-password"}
              required
              minLength={mode === "signup" ? 8 : undefined}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={INPUT_CLASS}
              placeholder={mode === "signup" ? "At least 8 characters" : ""}
            />
          </label>

          {error && (
            <div className="text-danger text-[12.5px] leading-[1.45]">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="mt-0.5 h-10 rounded-md bg-text-0 text-bg-0 font-semibold text-[13px] cursor-pointer border border-text-0 disabled:opacity-70"
          >
            {submitting
              ? mode === "signup"
                ? "Creating account…"
                : "Signing in…"
              : mode === "signup"
                ? "Create account"
                : "Sign in"}
          </button>
        </form>

        <div className="flex items-center gap-2.5 text-text-3 text-[11px]">
          <span className="flex-1 h-px bg-border-soft" />
          <span className="tracking-[0.05em] uppercase">or</span>
          <span className="flex-1 h-px bg-border-soft" />
        </div>

        <button
          type="button"
          onClick={handleGoogle}
          disabled={submitting}
          className="h-10 rounded-md bg-bg-2 text-text-0 text-[13px] font-medium border border-border-strong flex items-center justify-center gap-2.5 cursor-pointer disabled:opacity-70"
        >
          <GoogleGlyph />
          <span>Continue with Google</span>
        </button>

        <div className="text-center text-[12.5px] text-text-3 mt-0.5">
          {mode === "signin" ? (
            <>
              New to Donna?{" "}
              <button
                type="button"
                onClick={() => setMode("signup")}
                className="text-ai font-medium text-[12.5px] cursor-pointer"
              >
                Create an account
              </button>
            </>
          ) : (
            <>
              Already have an account?{" "}
              <button
                type="button"
                onClick={() => setMode("signin")}
                className="text-ai font-medium text-[12.5px] cursor-pointer"
              >
                Sign in
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function GoogleGlyph() {
  // Multicolour brand mark — fixed colours so it reads as Google regardless
  // of the surrounding `color` token.
  return (
    <svg width={16} height={16} viewBox="0 0 48 48" aria-hidden="true">
      <path
        fill="#FFC107"
        d="M43.6 20.5H42V20H24v8h11.3c-1.7 4.7-6.2 8-11.3 8-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.1 7.9 3l5.7-5.7C34.4 6.4 29.5 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.2-.1-2.3-.4-3.5z"
      />
      <path
        fill="#FF3D00"
        d="M6.3 14.7l6.6 4.8C14.7 16 19 13 24 13c3.1 0 5.8 1.1 7.9 3l5.7-5.7C34.4 6.4 29.5 4 24 4 16.3 4 9.7 8.4 6.3 14.7z"
      />
      <path
        fill="#4CAF50"
        d="M24 44c5.4 0 10.3-2.1 14-5.5l-6.4-5.4c-2 1.5-4.6 2.4-7.6 2.4-5.1 0-9.5-3.3-11.2-7.9l-6.5 5C9.6 39.6 16.2 44 24 44z"
      />
      <path
        fill="#1976D2"
        d="M43.6 20.5H42V20H24v8h11.3c-.8 2.3-2.3 4.3-4.3 5.7l6.4 5.4C40.9 35.7 44 30.2 44 24c0-1.2-.1-2.3-.4-3.5z"
      />
    </svg>
  );
}
