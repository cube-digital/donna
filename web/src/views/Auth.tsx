// Sign-in / sign-up screen.
//
// One sticker-card on the paper-dot background. Tab-toggles between the two
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
//
// Built entirely from the Goofy kit: `<GCard/>` body, `<GTabs/>` mode
// toggle, `<GFormField/>` + `<GInput/>` for every input, `<GButton/>`
// for both the primary submit and the Google fallback.

import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { googleStartUrl, signin, signup } from "../api/auth";
import { useAuth } from "../state/auth";
import {
  GButton,
  GCard,
  GFormField,
  GInput,
  GTabs,
  GoofyTheme,
  Sparkle,
} from "../components/Goofy";

type Mode = "signin" | "signup";

export default function Auth() {
  const setSignedIn = useAuth((s) => s.setSignedIn);
  const navigate = useNavigate();
  const [params] = useSearchParams();
  // Post-auth destination (e.g. an invitation accept page). Only honour a
  // same-origin path — never an absolute/protocol-relative URL — so ?return=
  // can't be used as an open redirect.
  const returnTo = params.get("return");
  const safeReturn =
    returnTo && returnTo.startsWith("/") && !returnTo.startsWith("//")
      ? returnTo
      : null;

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
      // Return to where the user came from (invitation accept, etc.). Without
      // this, App routing sends a workspace-less new user straight to
      // /workspaces and the pending invite is never accepted.
      if (safeReturn) navigate(safeReturn, { replace: true });
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
    <GoofyTheme paper className="min-h-screen grid place-items-center p-6 text-text-1">
      <div className="w-[420px] flex flex-col gap-5">
        {/* Brand mark + tagline — Fredoka name with a sticker sparkle medallion. */}
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

        <GCard className="flex flex-col gap-4">
          <GTabs<Mode>
            tabs={[
              { value: "signin", label: "Sign in" },
              { value: "signup", label: "Sign up" },
            ]}
            value={mode}
            onChange={setMode}
            className="self-start"
          />

          <form onSubmit={handleSubmit} className="flex flex-col gap-3" noValidate>
            {mode === "signup" && (
              <GFormField label="Full name">
                <GInput
                  type="text"
                  autoComplete="name"
                  required
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  placeholder="Jane Doe"
                  icon={null}
                />
              </GFormField>
            )}

            <GFormField label="Email">
              <GInput
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com"
                icon={null}
              />
            </GFormField>

            <GFormField label="Password">
              <GInput
                type="password"
                autoComplete={mode === "signin" ? "current-password" : "new-password"}
                required
                minLength={mode === "signup" ? 8 : undefined}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={mode === "signup" ? "At least 8 characters" : ""}
                icon={null}
              />
            </GFormField>

            {error && (
              // `role="alert"` + `aria-live="assertive"` announces auth
              // failures the moment they render so screen-reader users
              // know why the submit didn't go through.
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
              {submitting
                ? mode === "signup"
                  ? "Creating account…"
                  : "Signing in…"
                : mode === "signup"
                  ? "Create account"
                  : "Sign in"}
            </GButton>
          </form>

          {/* OR divider — dashed ink rule + hand-lettered "or" so the
              break reads as part of the goofy world, not generic chrome.
              Hidden from AT because the next button label ("Continue
              with Google") is already self-explanatory; announcing "or"
              between the two CTAs adds noise. */}
          <div aria-hidden="true" className="flex items-center gap-2.5 text-text-3">
            <span className="flex-1 border-t-2 border-dashed border-ink/40" />
            <span className="font-hand font-bold text-[18px] text-text-2 leading-none">
              or
            </span>
            <span className="flex-1 border-t-2 border-dashed border-ink/40" />
          </div>

          <GButton
            type="button"
            variant="default"
            size="lg"
            onClick={handleGoogle}
            disabled={submitting}
            className="w-full justify-center"
          >
            <GoogleGlyph />
            <span>Continue with Google</span>
          </GButton>
        </GCard>

        <div className="text-center text-[12.5px] text-text-2">
          {mode === "signin" ? (
            <>
              New to Donna?{" "}
              <button
                type="button"
                onClick={() => setMode("signup")}
                className="text-ai font-semibold underline-offset-2 hover:underline cursor-pointer"
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
                className="text-ai font-semibold underline-offset-2 hover:underline cursor-pointer"
              >
                Sign in
              </button>
            </>
          )}
        </div>
      </div>
    </GoofyTheme>
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
