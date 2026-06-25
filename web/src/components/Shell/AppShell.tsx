// The signed-in shell — every authenticated route renders inside this.
// Two-row grid (top bar + body); the columns are the design's
// 56 / 252 / 1fr / 320 split.
//
//     56px | 252px | 1fr | 320px       (columns)
//     44px |  1fr                       (rows)
//
//     ┌──────────────────────────────┐
//     │ rail │       topbar          │
//     │      ├──────────────────────┤
//     │      │sidebar│ main │ rrail │
//     └──────────────────────────────┘
//
// The original design carried a third 36px archive-dock row at the
// bottom, but the Vault surface was removed from this build; the dock
// went with it.
//
// Right-rail content is published per-view via `useRightRail` (see
// RightRailSlot.tsx). On mount we kick off `useChannels.loadChannels`
// and — on a hard page reload — refetch the workspace list so the
// sidebar header has the real workspace name (WorkspacePicker is the
// only place that fetched it before; a deep-link refresh skips that
// view entirely).

import { useEffect } from "react";
import { Outlet } from "react-router-dom";
import { Group, Panel, Separator } from "react-resizable-panels";

import { listWorkspaces } from "../../api/workspaces";
import { useChannels } from "../../state/channels";
import { useWorkspace } from "../../state/workspace";
import { NotificationsBootstrap } from "../RightRail/RightRail";
import {
  RightRailOutlet,
  RightRailProvider,
} from "./RightRailSlot";
import Sidebar from "./Sidebar";
import TopBar from "./TopBar";
import WsRail from "./WsRail";

function WorkspaceBootstrap() {
  const loadChannels = useChannels((s) => s.loadChannels);
  const upsertFromEvent = useChannels((s) => s.upsertFromEvent);
  const removeFromEvent = useChannels((s) => s.removeFromEvent);
  const workspaces = useWorkspace((s) => s.workspaces);
  const setWorkspaces = useWorkspace((s) => s.setWorkspaces);
  useEffect(() => {
    void loadChannels();
  }, [loadChannels]);

  const markPinned = useChannels((s) => s.markPinned);

  // Subscribe to channel lifecycle events from the chat WS so other tabs /
  // teammates' mutations show up without a hard refresh.
  useEffect(() => {
    // Lazy import to avoid pulling ws into the bootstrap during SSR.
    let cleanup: (() => void) | undefined;
    void Promise.all([
      import("../../lib/ws"),
      import("../../state/messages"),
      import("../../state/documents"),
      import("../../state/auth"),
    ]).then(([{ getChatWs }, { useMessages }, { useDocuments }, { useAuth }]) => {
      const ws = getChatWs();
      const offCreated = ws.on("channel.created", (p) =>
        upsertFromEvent(p as never),
      );
      const offUpdated = ws.on("channel.updated", (p) =>
        upsertFromEvent(p as never),
      );
      const offDeleted = ws.on("channel.deleted", (p: { channel_id: string }) =>
        removeFromEvent(p.channel_id),
      );
      // Pin/unpin (per-user; payload only carries channel_id).
      const offPinned = ws.on("channel.pinned", (p) =>
        markPinned(p.channel_id, true),
      );
      const offUnpinned = ws.on("channel.unpinned", (p) =>
        markPinned(p.channel_id, false),
      );
      // Reactions — route to messages store.
      const offReactionAdded = ws.on("reaction.added", (p) => {
        const me = useAuth.getState().user;
        useMessages
          .getState()
          .applyReactionAdded(p.channel_id, p.message_id, p.emoji, me?.id === p.user_id);
      });
      const offReactionRemoved = ws.on("reaction.removed", (p) => {
        const me = useAuth.getState().user;
        useMessages
          .getState()
          .applyReactionRemoved(p.channel_id, p.message_id, p.emoji, me?.id === p.user_id);
      });
      // Live doc updates from the agent's UpdateDraftSectionTool / Finalize.
      const offDocUpdated = ws.on("document.updated", (p) => {
        useDocuments.getState().upsertFromEvent(p.channel_id, p.document as never);
      });
      cleanup = () => {
        offCreated();
        offUpdated();
        offDeleted();
        offPinned();
        offUnpinned();
        offReactionAdded();
        offReactionRemoved();
        offDocUpdated();
      };
    });
    return () => cleanup?.();
  }, [upsertFromEvent, removeFromEvent, markPinned]);

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
      <div className="app-shell-root flex h-screen w-screen bg-bg-0 paper-dots overflow-hidden">
        <div className="w-[60px] shrink-0">
          <WsRail />
        </div>
        <Group
          orientation="horizontal"
          id="donna-shell-panels"
          className="flex-1 min-w-0 flex"
        >
          <Panel id="sidebar" defaultSize="17%" minSize="12%" maxSize="32%">
            <Sidebar />
          </Panel>
          <Separator className="w-px bg-border-soft hover:bg-ai/40 hover:w-[3px] transition-[width,background-color] duration-100" />
          <Panel id="main" minSize="30%">
            <main className="h-full flex flex-col min-w-0 overflow-hidden">
              <div className="h-[56px] shrink-0">
                <TopBar />
              </div>
              <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
                <Outlet />
              </div>
            </main>
          </Panel>
          <Separator className="w-px bg-border-soft hover:bg-ai/40 hover:w-[3px] transition-[width,background-color] duration-100" />
          <Panel id="rightrail" defaultSize="17%" minSize="12%" maxSize="32%">
            <RightRailOutlet />
          </Panel>
        </Group>
      </div>
    </RightRailProvider>
  );
}
