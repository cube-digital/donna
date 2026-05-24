// The signed-in shell — every authenticated route renders inside this.
// Grid mirrors donnaai/project/styles.css:96-110 exactly:
//
//     56px | 252px | 1fr | 320px       (columns)
//     44px |  1fr  |  36px             (rows)
//
//     ┌──────────────────────────────┐
//     │ rail │       topbar          │
//     │      ├──────────────────────┤
//     │      │sidebar│ main │ rrail │
//     │      ├──────────────────────┤
//     │      │       archive        │
//     └──────────────────────────────┘
//
// Right-rail content is published per-view via `useRightRail` (see
// RightRailSlot.tsx). On mount we kick off `useChannels.loadChannels`
// and — on a hard page reload — refetch the workspace list so the
// sidebar header has the real workspace name (WorkspacePicker is the
// only place that fetched it before; a deep-link refresh skips that
// view entirely).

import { useEffect } from "react";
import { Outlet } from "react-router-dom";

import { listWorkspaces } from "../../api/workspaces";
import { useChannels } from "../../state/channels";
import { useWorkspace } from "../../state/workspace";
import { NotificationsBootstrap } from "../RightRail/RightRail";
import ArchiveDock from "./ArchiveDock";
import {
  RightRailOutlet,
  RightRailProvider,
} from "./RightRailSlot";
import Sidebar from "./Sidebar";
import TopBar from "./TopBar";
import WsRail from "./WsRail";

function WorkspaceBootstrap() {
  const loadChannels = useChannels((s) => s.loadChannels);
  const workspaces = useWorkspace((s) => s.workspaces);
  const setWorkspaces = useWorkspace((s) => s.setWorkspaces);
  useEffect(() => {
    void loadChannels();
  }, [loadChannels]);
  useEffect(() => {
    // Re-hydrate the workspace list after a hard reload so the sidebar
    // header can resolve the active workspace name.
    if (workspaces.length > 0) return;
    let cancelled = false;
    void (async () => {
      try {
        const list = await listWorkspaces();
        if (!cancelled) setWorkspaces(list);
      } catch {
        /* leave list empty; sidebar falls back to "Workspace" label */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [workspaces.length, setWorkspaces]);
  return null;
}

export default function AppShell() {
  return (
    <RightRailProvider>
      <WorkspaceBootstrap />
      <NotificationsBootstrap />
      <div
        className="grid h-screen w-screen bg-bg-0
          grid-cols-[56px_252px_1fr_320px]
          grid-rows-[44px_1fr_36px]
          [grid-template-areas:'rail_topbar_topbar_topbar'_'rail_sidebar_main_rightrail'_'rail_archive_archive_archive']"
      >
        <WsRail />
        <TopBar />
        <Sidebar />
        <main className="[grid-area:main] flex flex-col bg-bg-0 min-w-0 overflow-hidden">
          <Outlet />
        </main>
        <RightRailOutlet />
        <ArchiveDock />
      </div>
    </RightRailProvider>
  );
}
