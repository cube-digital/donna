// New message — Slack-style inline picker page. Ported from
// assets/donna-ui-kit/react/NewMessageView.jsx, wired to real data:
//   - people  = workspace members (minus self), with presence + status
//   - channels = public channels from the channels store
//   - onStart  = 1 id → DM, N → group DM, channelId → open channel
//   - onInvite = create a workspace invitation
// Mounted at /new-message (opened from the sidebar "+" next to DMs).

import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import "../styles/donna-kit.css";
import Icon from "../components/kit/Icon";
import { postMessage, startDM, startGroupDM } from "../api/chat";
import {
  createInvitation,
  listMembers,
  type WorkspaceMemberRow,
} from "../api/workspaces";
import { colorFrom, initialsFrom } from "../lib/kitAvatar";
import { useChannels } from "../state/channels";
import { useMe } from "../state/me";

interface KitPerson {
  id: string;
  name: string;
  email: string;
  initials: string;
  color: string;
  presence: "active" | "away";
  status: string;
  role: string;
}
interface KitChannel {
  id: string;
  name: string;
  private: boolean;
}

const isEmail = (s: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s.trim());

function presenceColor(p: "active" | "away"): string {
  return p === "active" ? "var(--dn-ok)" : "oklch(0.70 0.15 70)";
}

export default function NewMessage() {
  const navigate = useNavigate();
  const me = useMe((s) => s.me);
  const loadMe = useMe((s) => s.load);
  const channels = useChannels((s) => s.channels);

  const [members, setMembers] = useState<WorkspaceMemberRow[]>([]);
  const [tokens, setTokens] = useState<KitPerson[]>([]);
  const [q, setQ] = useState("");
  const [msg, setMsg] = useState("");
  const [sending, setSending] = useState(false);
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    void loadMe();
    void (async () => {
      try {
        setMembers(await listMembers());
      } catch {
        /* leave empty */
      }
    })();
  }, [loadMe]);

  const people: KitPerson[] = useMemo(
    () =>
      members
        .filter((m) => m.user.id !== me?.id)
        .map((m) => {
          const name = m.user.full_name || m.user.email;
          return {
            id: m.user.id,
            name,
            email: m.user.email,
            initials: initialsFrom(name),
            color: colorFrom(m.user.id),
            presence: m.user.is_away ? "away" : "active",
            status: m.user.status || "",
            role: m.role,
          } satisfies KitPerson;
        }),
    [members, me?.id],
  );

  const kitChannels: KitChannel[] = useMemo(
    () =>
      channels
        .filter((c) => c.kind === "channel")
        .map((c) => ({
          id: c.id,
          name: c.name,
          private: c.visibility === "private",
        })),
    [channels],
  );

  const picked = new Set(tokens.map((t) => t.id));
  const ql = q.trim().toLowerCase();

  const peopleMatches = useMemo(
    () =>
      people.filter(
        (p) =>
          !picked.has(p.id) &&
          (!ql ||
            `${p.name} ${p.email} ${p.status}`.toLowerCase().includes(ql)),
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [people, ql, tokens],
  );
  const channelMatches = useMemo(
    () => kitChannels.filter((c) => !ql || c.name.toLowerCase().includes(ql)),
    [kitChannels, ql],
  );
  const showInvite =
    isEmail(q) && !people.some((p) => p.email.toLowerCase() === ql);

  const addPerson = (p: KitPerson) => {
    setTokens((t) => [...t, p]);
    setQ("");
    inputRef.current?.focus();
  };
  const removeToken = (id: string) =>
    setTokens((t) => t.filter((x) => x.id !== id));

  const start = async () => {
    const ids = tokens.map((t) => t.id);
    if (ids.length === 0 || sending) return;
    setSending(true);
    try {
      const ch = ids.length === 1 ? await startDM(ids[0]) : await startGroupDM(ids);
      const text = msg.trim();
      if (text) await postMessage(ch.id, text);
      await useChannels.getState().loadChannels();
      navigate(`/channels/${ch.id}`);
    } catch {
      /* surfaced by the channel view */
    } finally {
      setSending(false);
    }
  };

  const openChannel = (channelId: string) => navigate(`/channels/${channelId}`);

  const invite = async (email: string) => {
    try {
      await createInvitation(email, "member");
    } catch {
      /* ignore */
    }
    navigate("/channels");
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Backspace" && q === "" && tokens.length) {
      removeToken(tokens[tokens.length - 1].id);
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (showInvite) return void invite(q.trim());
      if (peopleMatches[active]) addPerson(peopleMatches[active]);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => Math.min(i + 1, Math.max(peopleMatches.length - 1, 0)));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    }
  };

  const canStart = tokens.length > 0;

  return (
    <div className="h-full overflow-y-auto">
      <div className="dn-root dn-nm dn-paper">
        <div className="dn-nm-head">
          <Icon name="at" /> New message
        </div>

        <div className="dn-to">
          <span className="dn-to-label">To:</span>
          <div
            className="dn-token-field"
            onClick={() => inputRef.current?.focus()}
          >
            {tokens.map((t) => (
              <span className="dn-token" key={t.id}>
                <span className="dn-token-av" style={{ background: t.color }}>
                  {t.initials}
                </span>
                {t.name.split(" ")[0]}
                <button
                  className="dn-token-x"
                  onClick={(e) => {
                    e.stopPropagation();
                    removeToken(t.id);
                  }}
                >
                  <Icon name="x" size={8} />
                </button>
              </span>
            ))}
            <input
              ref={inputRef}
              value={q}
              placeholder={tokens.length ? "" : "#channel, @person, or name@email.com"}
              onChange={(e) => {
                setQ(e.target.value);
                setActive(0);
              }}
              onKeyDown={onKeyDown}
            />
          </div>
        </div>

        <div className="dn-nm-hint">
          <span className="dn-key">↑↓</span> navigate · <span className="dn-key">↵</span> add ·
          pick more than one for a group
        </div>

        <div className="dn-suggest">
          {peopleMatches.length > 0 && (
            <div className="dn-suggest-group">People</div>
          )}
          {peopleMatches.map((p, i) => (
            <div
              key={p.id}
              className={`dn-suggest-row ${i === active ? "is-active" : ""}`}
              onMouseEnter={() => setActive(i)}
              onClick={() => addPerson(p)}
            >
              <span
                className="dn-avatar"
                style={{ background: p.color, position: "relative" }}
              >
                {p.initials}
                <span
                  className="dn-presence"
                  style={{ background: presenceColor(p.presence) }}
                />
              </span>
              <div className="dn-suggest-name">
                {p.name}
                <span className="dn-suggest-sub">
                  {p.status ? p.status : p.email} · {p.presence}
                </span>
              </div>
              {p.role && <span className="dn-suggest-role">{p.role}</span>}
            </div>
          ))}

          {channelMatches.length > 0 && (
            <div className="dn-suggest-group">Channels</div>
          )}
          {channelMatches.map((c) => (
            <div
              key={c.id}
              className="dn-suggest-row"
              onClick={() => openChannel(c.id)}
            >
              <span className="dn-hashbox">
                <Icon name={c.private ? "lock" : "hash"} size={15} />
              </span>
              <div className="dn-suggest-name">
                {c.name}
                {c.private && <span className="dn-suggest-sub">private</span>}
              </div>
            </div>
          ))}

          {showInvite && (
            <>
              <div className="dn-suggest-rule" />
              <div
                className="dn-suggest-row"
                onClick={() => void invite(q.trim())}
              >
                <span className="dn-hashbox">
                  <Icon name="mail" size={15} />
                </span>
                <div className="dn-suggest-name dn-suggest-invite">
                  Invite{" "}
                  <span
                    className="dn-mono"
                    style={{ color: "var(--dn-grape-deep)" }}
                  >
                    {q.trim()}
                  </span>
                </div>
              </div>
            </>
          )}
        </div>

        <div className="dn-nm-composer">
          <textarea
            className="txt"
            rows={2}
            value={msg}
            disabled={!canStart}
            placeholder={
              canStart ? "Start a new message…" : "Add someone above to start…"
            }
            onChange={(e) => setMsg(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void start();
              }
            }}
            style={{
              width: "100%",
              border: "none",
              outline: "none",
              resize: "none",
              background: "transparent",
              font: "inherit",
              color: "var(--dn-t0)",
              padding: "13px 15px",
            }}
          />
          <div className="tools">
            <b>B</b>
            <i style={{ fontStyle: "italic" }}>I</i>
            <Icon name="link" />
            <Icon name="at" />
            <Icon name="smile" />
            <Icon name="plus" />
            <button
              className="dn-send"
              disabled={!canStart || sending}
              onClick={() => void start()}
              aria-label="Start chat"
            >
              <Icon name="send" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
