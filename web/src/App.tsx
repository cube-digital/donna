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

import { useEffect } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";

import { setUnauthorizedHandler } from "./api/client";
import { useAuth } from "./state/auth";
import { useWorkspace } from "./state/workspace";

import Auth from "./views/Auth";
import OAuthReturn from "./views/OAuthReturn";
import WorkspacePicker from "./views/WorkspacePicker";
import AppShell from "./components/Shell/AppShell";
import Channel from "./views/Channel";
import Personal from "./views/Personal";
import ComingSoon from "./views/ComingSoon";

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

  if (!isAuthenticated) {
    return (
      <Routes>
        <Route path="/auth/*" element={<Auth />} />
        <Route path="/oauth/return" element={<OAuthReturn />} />
        <Route path="*" element={<Navigate to="/auth" replace />} />
      </Routes>
    );
  }

  if (!activeId) {
    return (
      <Routes>
        <Route path="/workspaces" element={<WorkspacePicker />} />
        <Route path="/oauth/return" element={<OAuthReturn />} />
        <Route path="*" element={<Navigate to="/workspaces" replace />} />
      </Routes>
    );
  }

  return (
    <Routes>
      <Route path="/oauth/return" element={<OAuthReturn />} />
      <Route element={<AppShell />}>
        <Route index element={<Navigate to="/channels" replace />} />
        <Route path="/channels" element={<ComingSoon title="Pick a channel" />} />
        <Route path="/channels/:channelId" element={<Channel />} />
        <Route path="/personal" element={<Personal />} />
        <Route path="/personal/:channelId" element={<Personal />} />
        <Route path="/search" element={<ComingSoon title="Search & history" />} />
        <Route path="/vault" element={<ComingSoon title="Vault" />} />
        <Route path="/agents/:agentId" element={<ComingSoon title="Agent profile" />} />
        <Route path="/projects/:projectId" element={<ComingSoon title="Project overview" />} />
        <Route path="*" element={<Navigate to="/channels" replace />} />
      </Route>
    </Routes>
  );
}
