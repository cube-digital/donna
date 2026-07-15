// Top-level route gate.
//
// Flow:
//   not signed in            → <Auth/>
//   signed in, no workspace  → <WorkspacePicker/>
//   signed in, workspace set → <AppShell/> with nested routes
//
// Components are stubbed and filled in by per-vertical subtasks:
//   - views/Auth.tsx           (UI primitives + auth shell)
//   - views/WorkspacePicker.tsx + components/Shell/AppShell.tsx
//   - views/Channel.tsx, Personal.tsx, ComingSoon.tsx

import { lazy, Suspense, useEffect } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";

import { setUnauthorizedHandler } from "./api/client";
import { useAuth } from "./state/auth";
import { useWorkspace } from "./state/workspace";

import Auth from "./views/Auth";
import OAuthReturn from "./views/OAuthReturn";
import WorkspacePicker from "./views/WorkspacePicker";
import AppShell from "./components/Shell/AppShell";
import { ToastStack } from "./components/Shell/ToastStack";
import Channel from "./views/Channel";
import Files from "./views/Files";
import Personal from "./views/Personal";
import ComingSoon from "./views/ComingSoon";
import Integrations from "./views/Integrations";
import IntegrationDetail from "./views/IntegrationDetail";
import Settings from "./views/Settings";
import AcceptInvitation from "./views/AcceptInvitation";
import ResetPassword from "./views/ResetPassword";

// The Showcase route pulls in the entire Goofy library — split it out
// of the main chunk via React.lazy so users who never visit /showcase
// don't pay for the gallery. See Vercel rule `bundle-dynamic-imports`.
const Showcase = lazy(() => import("./views/Showcase"));

// Tiny placeholder rendered while the Showcase chunk streams in.
// Re-uses only the design tokens, no Goofy components, so the fallback
// itself stays inside the main bundle.
function ShowcaseFallback() {
  return (
    <div
      className="min-h-screen grid place-items-center bg-bg-0 text-text-2 font-display"
      style={{ fontSize: 16, fontWeight: 600 }}
    >
      loading…
    </div>
  );
}

function LazyShowcase() {
  return (
    <Suspense fallback={<ShowcaseFallback />}>
      <Showcase />
    </Suspense>
  );
}

export default function App() {
  const isAuthenticated = useAuth((s) => s.isAuthenticated);
  const signOut = useAuth((s) => s.signOut);
  const activeId = useWorkspace((s) => s.activeId);
  const navigate = useNavigate();

  // Wire global 401 → kick to auth.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      signOut();
      navigate("/auth", { replace: true });
    });
    return () => setUnauthorizedHandler(null);
  }, [signOut, navigate]);

  // `<ToastStack/>` is mounted once at the route root (outside the
  // Routes tree) so toasts fired from auth, picker, and signed-in
  // views all surface in the same stack and survive route changes.
  return (
    <>
      {renderRoutes()}
      <ToastStack />
    </>
  );

  function renderRoutes() {
    if (!isAuthenticated) {
      return (
        <Routes>
          <Route path="/showcase" element={<LazyShowcase />} />
          <Route path="/auth/*" element={<Auth />} />
          <Route path="/oauth/return" element={<OAuthReturn />} />
          <Route path="/password/reset" element={<ResetPassword />} />
          <Route path="/invitations/:token/accept" element={<AcceptInvitation />} />
          <Route path="*" element={<Navigate to="/auth" replace />} />
        </Routes>
      );
    }

    if (!activeId) {
      return (
        <Routes>
          <Route path="/showcase" element={<LazyShowcase />} />
          <Route path="/workspaces" element={<WorkspacePicker />} />
          <Route path="/oauth/return" element={<OAuthReturn />} />
          <Route path="/password/reset" element={<ResetPassword />} />
          <Route path="/invitations/:token/accept" element={<AcceptInvitation />} />
          <Route path="*" element={<Navigate to="/workspaces" replace />} />
        </Routes>
      );
    }

    return (
      <Routes>
        <Route path="/showcase" element={<LazyShowcase />} />
        <Route path="/oauth/return" element={<OAuthReturn />} />
        <Route path="/password/reset" element={<ResetPassword />} />
        <Route path="/invitations/:token/accept" element={<AcceptInvitation />} />
        <Route element={<AppShell />}>
          <Route index element={<Navigate to="/channels" replace />} />
          <Route path="/channels" element={<ComingSoon title="Pick a channel" />} />
          <Route path="/channels/:channelId" element={<Channel />} />
          <Route path="/personal" element={<Personal />} />
          <Route path="/personal/:channelId" element={<Personal />} />
          <Route path="/integrations" element={<Integrations />} />
          <Route path="/integrations/:slug" element={<IntegrationDetail />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/settings/:tab" element={<Settings />} />
          <Route path="/search" element={<ComingSoon title="Search & history" />} />
          <Route path="/cortex" element={<Files />} />
          <Route path="/files" element={<Navigate to="/cortex" replace />} />
          <Route path="/agents/:agentId" element={<ComingSoon title="Agent profile" />} />
          <Route path="/projects/:projectId" element={<ComingSoon title="Project overview" />} />
          <Route path="*" element={<Navigate to="/channels" replace />} />
        </Route>
      </Routes>
    );
  }
}
