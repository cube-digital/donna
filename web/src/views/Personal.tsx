// Personal AI chat — port of `donnaai/project/personal.jsx:1-90`.
//
// Two columns inside the main pane:
//   - 240px history sidebar (recent personal chats)
//   - 1fr chat pane (reuses Channel-view's Message + Composer)
//
// Backing model for v1
// ────────────────────
// The backend doesn't represent an "agent peer" as a real User, so we
// can't open a DM with Donna via `/chat/dms`. We therefore reuse any
// existing direct-kind channel the user is in — the first one becomes
// the active personal chat. If none exist, show an instructional empty
// state. When the backend exposes an agent-peer endpoint or a
// dedicated PersonalChannel, swap this in.
//
// Right rail
// ──────────
// Publishes `<DonnaToday/>` + `<MemoryStub scope="personal"/>` into
// the shell's right-rail slot via `useRightRail`. The slot clears on
// unmount.

import { useEffect, useMemo, useRef, useLayoutEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";

import Composer from "../components/Channel/Composer";
import MessageRow from "../components/Channel/Message";
import {
  DonnaToday,
  MemoryStub,
} from "../components/RightRail/RightRail";
import { useRightRail } from "../components/Shell/RightRailSlot";
import { Av } from "../components/Ui/Av";
import { Ic } from "../components/Ui/Ic";
import { hueForAgent } from "../lib/hueForAgent";
import { getChatWs } from "../lib/ws";
import { useChannels } from "../state/channels";
import { useMessages } from "../state/messages";

const NEAR_BOTTOM_PX = 80;

// Reusable Tailwind fragments — kept as constants so the JSX stays terse.
const HIST_ITEM_BASE =
  "block w-full text-left bg-transparent border-0 cursor-pointer py-2 px-2.5 rounded-[7px] mx-0.5 my-px hover:bg-bg-2";
const HIST_ITEM_ACTIVE = "bg-bg-3";

// Chat-head pill (Memory · N, Switch agent) — disclosure-style chip.
// The design's `.channel-header .pill` rule isn't scoped to `.personal`,
// so we replicate the matching look with utilities.
const PILL_CLS =
  "flex items-center gap-1.5 h-7 px-3 rounded-[7px] border border-border-soft bg-bg-2 text-[12px] text-text-1 cursor-pointer hover:bg-bg-3";

export default function Personal() {
  const navigate = useNavigate();
  const { channelId: routeChannelId } = useParams<{ channelId?: string }>();

  const channels = useChannels((s) => s.channels);
  const loadChannels = useChannels((s) => s.loadChannels);
  const directChannels = useMemo(
    () => channels.filter((c) => c.kind === "direct"),
    [channels],
  );

  // Pick the active personal chat: route param wins; else first direct
  // channel; else nothing.
  const active =
    (routeChannelId && channels.find((c) => c.id === routeChannelId)) ||
    directChannels[0] ||
    null;

  // Bootstrap the channels list if AppShell hasn't loaded yet (deep link).
  useEffect(() => {
    if (channels.length === 0) void loadChannels();
  }, [channels.length, loadChannels]);

  // Right-rail registration — only re-fire when scope toggles, which is
  // never inside this view, so the memoized element is stable.
  const rrNode = useMemo(
    () => (
      <>
        <DonnaToday />
        <MemoryStub scope="personal" />
      </>
    ),
    [],
  );
  useRightRail(rrNode);

  // Messages list + WS wiring for the active personal channel.
  const messages = useMessages((s) =>
    active ? s.byChannel[active.id] : undefined,
  );
  const loading = useMessages((s) =>
    active ? !!s.loading[active.id] : false,
  );
  const loadInitial = useMessages((s) => s.loadInitial);
  const appendFromEvent = useMessages((s) => s.appendFromEvent);
  const updateFromEvent = useMessages((s) => s.updateFromEvent);
  const removeFromEvent = useMessages((s) => s.removeFromEvent);

  useEffect(() => {
    if (!active) return;
    void loadInitial(active.id);
  }, [active, loadInitial]);

  useEffect(() => {
    if (!active) return;
    const ws = getChatWs();
    ws.subscribe(active.id);
    const offC = ws.on("message.created", (p) => {
      if (p.channel_id !== active.id) return;
      appendFromEvent(active.id, p);
    });
    const offU = ws.on("message.updated", (p) => {
      if (p.channel_id !== active.id) return;
      updateFromEvent(active.id, p);
    });
    const offD = ws.on("message.deleted", (p) => {
      if (p.channel_id !== active.id) return;
      removeFromEvent(active.id, p.message_id);
    });
    return () => {
      offC();
      offU();
      offD();
      ws.unsubscribe(active.id);
    };
  }, [active, appendFromEvent, updateFromEvent, removeFromEvent]);

  // Auto-scroll near-bottom on growth.
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const wasAtBottomRef = useRef(true);
  const prevLenRef = useRef(0);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const handler = () => {
      const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
      wasAtBottomRef.current = distance < NEAR_BOTTOM_PX;
    };
    handler();
    el.addEventListener("scroll", handler, { passive: true });
    return () => el.removeEventListener("scroll", handler);
  }, [active?.id]);

  const list = messages ?? [];
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const grew = list.length > prevLenRef.current;
    prevLenRef.current = list.length;
    if (grew && wasAtBottomRef.current) el.scrollTop = el.scrollHeight;
  }, [list]);

  // Derive the active agent identity from the first observed agent
  // message in this channel. We don't have a real agent-peer concept
  // server-side yet, so this is a best-effort proxy: when a real
  // PersonalChannel + agent FK lands, lift this off `messages`.
  const agentIdentity = useMemo(() => {
    for (const m of list) {
      const a = m.author_agent;
      if (a && a.name) return { name: a.name, hue: hueForAgent(a.id) };
    }
    return { name: "Donna", hue: 282 };
  }, [list]);

  return (
    <div className="grid grid-cols-[240px_1fr] h-full min-h-0">
      <aside className="border-r border-border-soft overflow-y-auto py-2 px-1.5">
        <button
          type="button"
          className="flex items-center gap-2 py-2 px-2.5 bg-ai-bg border border-ai-glow rounded-lg text-ai text-[12.5px] font-medium mt-1 mb-2.5 mx-1 cursor-pointer hover:bg-ai-glow"
          onClick={() =>
            alert(
              "Personal chats with Donna will get their own backing model soon. For now, open any direct-message channel from the sidebar.",
            )
          }
        >
          <Ic.plus />
          <span>New chat with Donna</span>
        </button>

        {directChannels.length === 0 ? (
          <div className="py-5 px-3 text-[12px] text-text-3 leading-[1.55]">
            No personal chats yet. Direct messages will appear here when
            you start one from the workspace sidebar.
          </div>
        ) : (
          <>
            <div className="text-[10.5px] tracking-[0.06em] uppercase text-text-3 pt-1.5 pb-1 px-2.5 font-semibold">
              Recent
            </div>
            {directChannels.map((c) => {
              const isActive = active?.id === c.id;
              return (
                <button
                  key={c.id}
                  type="button"
                  className={`${HIST_ITEM_BASE}${isActive ? ` ${HIST_ITEM_ACTIVE}` : ""}`}
                  onClick={() => navigate(`/personal/${c.id}`)}
                >
                  <div className="text-[12.5px] text-text-0 font-medium">
                    {c.name || "Direct message"}
                  </div>
                  <div className="text-[11.5px] text-text-2 mt-px overflow-hidden text-ellipsis whitespace-nowrap">
                    {c.topic || "—"}
                  </div>
                  <div className="text-[10.5px] text-text-3 mt-0.5 flex gap-1.5 items-center">
                    <Av kind="agent" agent={agentIdentity} size="sm" />
                    <span>{agentIdentity.name}</span>
                  </div>
                </button>
              );
            })}
          </>
        )}
      </aside>

      <div className="flex flex-col min-w-0 min-h-0">
        {active ? (
          <>
            <header className="flex items-center gap-3 px-[22px] py-3 border-b border-border-soft">
              <Av kind="agent" agent={agentIdentity} pulsing />
              <div>
                <div className="font-semibold text-text-0 text-[14px]">
                  {agentIdentity.name}
                </div>
                <div className="text-text-3 text-[12px]">
                  Personal AI · {active.name}
                </div>
              </div>
              <div className="flex-1" />
              <button
                type="button"
                className={PILL_CLS}
                title="Coming soon"
                onClick={() => alert("Memory inspector coming soon.")}
              >
                <Ic.brain />
                <span>Memory · 0 items</span>
              </button>
              <button
                type="button"
                className={PILL_CLS}
                onClick={() => alert("Agent switcher coming soon.")}
              >
                <span>Switch agent</span>
                <Ic.caret />
              </button>
            </header>

            <div
              className="flex-1 overflow-y-auto py-6 px-[22px] flex flex-col gap-4 items-stretch"
              ref={scrollRef}
            >
              {loading && list.length === 0 ? (
                <div className="self-center text-text-3 text-[12px]">
                  Loading…
                </div>
              ) : null}
              {list.map((m) => (
                <MessageRow key={m.id} msg={m} />
              ))}
            </div>

            <Composer
              channelId={active.id}
              placeholder="Ask Donna anything · drop a file · /command"
            />
          </>
        ) : (
          <div className="flex-1 grid place-items-center p-10 text-text-2 text-center">
            <div className="max-w-[360px]">
              <div className="text-[15px] text-text-0 font-medium mb-1.5">
                No personal chat yet
              </div>
              <div className="text-[13px] leading-[1.55]">
                Open a direct-message channel from the workspace sidebar to
                start. Personal chats with Donna will get their own backing
                model soon.
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
