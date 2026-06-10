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

  // Subscribe to channel lifecycle events from the chat WS so other tabs /
  // teammates' mutations show up without a hard refresh. Two flavours:
  //
  // - ``workspace-{wid}-events`` (auto-subscribed by ChatConsumer for every
  //   workspace the user belongs to): channel.created / updated / deleted.
  // - ``presence-user-{uid}`` (always-on subscription): channel.added.to_you
  //   when an admin invites the caller; channel.removed.from_you when
  //   kicked or self-leave.
  //
  // The invitee channels carry the full Channel payload server-side
  // (see ChannelService.add_member) so the sidebar can upsert without
  // a follow-up GET.
  useEffect(() => {
    // Lazy import to avoid pulling ws into the bootstrap during SSR.
    let cleanup: (() => void) | undefined;
    void import("../../lib/ws").then(({ getChatWs }) => {
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
      const offAddedToYou = ws.on("channel.added.to_you", (p) => {
        // Backend serializes ``workspace_id`` as a separate top-level field
        // (not nested) — normalize to the REST shape the store expects.
        const ch = p.channel as never as {
          id: string;
          kind: "channel" | "direct";
          name: string;
          slug: string;
          topic: string;
          visibility: "public" | "private";
          workspace_id: string;
        };
        upsertFromEvent({
          id: ch.id,
          kind: ch.kind,
          name: ch.name,
          slug: ch.slug,
          topic: ch.topic,
          visibility: ch.visibility,
          workspace: ch.workspace_id,
          // The serializer pre-Phase-1.0 doesn't ship created_at /
          // updated_at on the dict-broadcast path. The sidebar sorts by
          // name; missing timestamps are harmless until a downstream
          // view reads them.
          created_at: "",
          updated_at: "",
        } as never);
      });
      const offRemovedFromYou = ws.on(
        "channel.removed.from_you",
        (p: { channel_id: string }) => removeFromEvent(p.channel_id),
      );
      cleanup = () => {
        offCreated();
        offUpdated();
        offDeleted();
        offAddedToYou();
        offRemovedFromYou();
      };
    });
    return () => cleanup?.();
  }, [upsertFromEvent, removeFromEvent]);

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
        className="app-shell-root grid h-screen w-screen bg-bg-0
          grid-cols-[56px_252px_1fr_320px]
          grid-rows-[56px_1fr]
          [grid-template-areas:'rail_topbar_topbar_topbar'_'rail_sidebar_main_rightrail']"
      >
        <WsRail />
        <TopBar />
        <Sidebar />
        <main className="[grid-area:main] flex flex-col bg-bg-0 min-w-0 overflow-hidden">
          <Outlet />
        </main>
        <RightRailOutlet />
      </div>
    </RightRailProvider>
  );
}
