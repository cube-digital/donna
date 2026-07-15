// Channel details panel container — owns data + handlers, renders the ported
// ChannelPanel as a centered overlay. Mounted once by AppShell; shows nothing
// until useChannelPanel().open(channelId) is called.

import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import "../../../styles/donna-kit.css";
import {
  addChannelMember,
  deleteChannel,
  getChannel,
  listChannelMembers,
  removeChannelMember,
  updateChannel,
  updateChannelMemberRole,
  type ChannelMemberRow,
} from "../../../api/chat";
import {
  createInvitation,
  listMembers,
  type WorkspaceMemberRow,
} from "../../../api/workspaces";
import { colorFrom, initialsFrom } from "../../../lib/kitAvatar";
import { useChannelPanel } from "../../../state/channelPanel";
import { useMe } from "../../../state/me";
import type { Channel } from "../../../types";
import ChannelPanel from "./ChannelPanel";
import type { ChannelSettingsPatch } from "./ChannelSettingsTab";
import type {
  ChannelRole,
  KitCandidate,
  KitChannel,
  KitChannelMember,
} from "./types";

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export default function ChannelPanelContainer() {
  const channelId = useChannelPanel((s) => s.openChannelId);
  const close = useChannelPanel((s) => s.close);
  const me = useMe((s) => s.me);
  const loadMe = useMe((s) => s.load);
  const navigate = useNavigate();

  const [channel, setChannel] = useState<Channel | null>(null);
  const [roster, setRoster] = useState<ChannelMemberRow[]>([]);
  const [wsMembers, setWsMembers] = useState<WorkspaceMemberRow[]>([]);

  const refetchRoster = async () => {
    if (!channelId) return;
    setRoster(await listChannelMembers(channelId));
  };

  useEffect(() => {
    void loadMe();
  }, [loadMe]);

  useEffect(() => {
    if (!channelId) {
      setChannel(null);
      setRoster([]);
      setWsMembers([]);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const [ch, mem, ws] = await Promise.all([
          getChannel(channelId),
          listChannelMembers(channelId),
          listMembers(),
        ]);
        if (!cancelled) {
          setChannel(ch);
          setRoster(mem);
          setWsMembers(ws);
        }
      } catch {
        /* leave empty */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [channelId]);

  useEffect(() => {
    if (!channelId) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [channelId, close]);

  const kitChannel: KitChannel | null = useMemo(() => {
    if (!channel) return null;
    return {
      id: channel.id,
      name: channel.name,
      topic: channel.topic,
      visibility: channel.visibility,
      created_by: "—",
      created_at: fmtDate(channel.created_at),
    };
  }, [channel]);

  const kitMembers: KitChannelMember[] = useMemo(
    () =>
      roster.map((r) => {
        const name = r.user.full_name || r.user.email;
        return {
          id: r.user.id,
          name,
          email: r.user.email,
          initials: initialsFrom(name),
          color: colorFrom(r.user.id),
          role: r.role,
          is_you: !!me && r.user.id === me.id,
        };
      }),
    [roster, me],
  );

  const candidates: KitCandidate[] = useMemo(() => {
    const inChannel = new Set(roster.map((r) => r.user.id));
    return wsMembers
      .filter((m) => !inChannel.has(m.user.id))
      .map((m) => {
        const name = m.user.full_name || m.user.email;
        return {
          id: m.user.id,
          name,
          email: m.user.email,
          initials: initialsFrom(name),
          color: colorFrom(m.user.id),
        };
      });
  }, [wsMembers, roster]);

  const isChannelAdmin = useMemo(
    () => roster.some((r) => me && r.user.id === me.id && r.role === "admin"),
    [roster, me],
  );

  if (!channelId || !kitChannel) return null;

  const onAddMember = async (userId: string) => {
    await addChannelMember(channelId, userId);
    await refetchRoster();
  };
  const onRemoveMember = async (userId: string) => {
    await removeChannelMember(channelId, userId);
    await refetchRoster();
  };
  const onRoleChange = async (userId: string, role: ChannelRole) => {
    await updateChannelMemberRole(channelId, userId, role);
    await refetchRoster();
  };
  const onInviteByEmail = async (fd: FormData) => {
    const email = String(fd.get("email") ?? "").trim();
    if (!email) return;
    await createInvitation(email, "member");
  };
  const onSave = async (patch: ChannelSettingsPatch) => {
    if (Object.keys(patch).length === 0) return;
    const updated = await updateChannel(channelId, patch);
    setChannel(updated);
  };
  const onDelete = async () => {
    await deleteChannel(channelId);
    close();
    navigate("/channels");
  };
  const onOpenFiles = () => {
    close();
    navigate("/cortex");
  };

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center p-6"
      role="dialog"
      aria-modal="true"
    >
      <div
        className="absolute inset-0 bg-[oklch(0.26_0.03_285/0.30)]"
        onClick={close}
        aria-hidden
      />
      <div
        className="relative w-[860px] max-w-[94vw] max-h-[88vh] overflow-y-auto"
        style={{ boxShadow: "0 24px 60px oklch(0.26 0.03 285 / 0.28)" }}
      >
        <ChannelPanel
          channel={kitChannel}
          members={kitMembers}
          candidates={candidates}
          isChannelAdmin={isChannelAdmin}
          onAddMember={onAddMember}
          onRemoveMember={onRemoveMember}
          onRoleChange={onRoleChange}
          onInviteByEmail={onInviteByEmail}
          onSave={onSave}
          onDelete={onDelete}
          onOpenFiles={onOpenFiles}
          onNotifications={close}
        />
      </div>
    </div>
  );
}
