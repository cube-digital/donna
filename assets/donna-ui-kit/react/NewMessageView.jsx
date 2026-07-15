// NewMessageView — Slack-style "New message" as an INLINE page (not a modal).
// The whole pane is the picker: a To: token field, suggestions flowing on the
// page (People + Channels + email-invite), and the composer pinned at bottom.
//
//   <NewMessageView people={...} channels={...} onStart={...} onInvite={...} />
//
// Multi-select: one recipient -> 1:1 DM, several -> group DM.
// Presentational + local state only; data + submit are props.
import { useMemo, useRef, useState } from "react";
import Icon from "./Icon";

const isEmail = (s) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s.trim());

export default function NewMessageView({
  people = [],        // [{ id, name, handle, email, initials, color, presence, role }]
  channels = [],      // [{ id, name, private }]
  recents = [],       // optional [personId] ordered
  onStart,            // ({ userIds:[], channelId:null }) -> open the DM / group / channel
  onInvite,           // (email) -> create workspace invitation + queue into DM
}) {
  const [tokens, setTokens] = useState([]);        // selected recipients
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef(null);

  const picked = new Set(tokens.map((t) => t.id));
  const ql = q.trim().toLowerCase();

  const peopleMatches = useMemo(
    () => people.filter((p) =>
      !picked.has(p.id) &&
      (!ql || `${p.name} ${p.handle ?? ""} ${p.email ?? ""}`.toLowerCase().includes(ql))
    ),
    [people, ql, tokens]
  );
  const channelMatches = useMemo(
    () => channels.filter((c) => !ql || c.name.toLowerCase().includes(ql)),
    [channels, ql]
  );
  const showInvite = isEmail(q) && !people.some((p) => p.email?.toLowerCase() === ql);

  const addPerson = (p) => { setTokens((t) => [...t, p]); setQ(""); inputRef.current?.focus(); };
  const removeToken = (id) => setTokens((t) => t.filter((x) => x.id !== id));

  const onKeyDown = (e) => {
    if (e.key === "Backspace" && q === "" && tokens.length) {
      removeToken(tokens[tokens.length - 1].id);
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (showInvite) return onInvite?.(q.trim());
      if (peopleMatches[active]) addPerson(peopleMatches[active]);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => Math.min(i + 1, Math.max(peopleMatches.length - 1, 0)));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    }
  };

  const start = () => onStart?.({ userIds: tokens.map((t) => t.id), channelId: null });
  const canStart = tokens.length > 0;

  return (
    <div className="dn-root dn-nm dn-paper">
      <div className="dn-nm-head">
        <Icon name="at" /> New message
      </div>

      <div className="dn-to">
        <span className="dn-to-label">To:</span>
        <div className="dn-token-field" onClick={() => inputRef.current?.focus()}>
          {tokens.map((t) => (
            <span className="dn-token" key={t.id}>
              <span className="dn-token-av" style={{ background: t.color }}>{t.initials}</span>
              {t.name.split(" ")[0]}
              <button className="dn-token-x" onClick={(e) => { e.stopPropagation(); removeToken(t.id); }}>
                <Icon name="x" size={8} />
              </button>
            </span>
          ))}
          <input
            ref={inputRef}
            value={q}
            placeholder={tokens.length ? "" : "#channel, @person, or name@email.com"}
            onChange={(e) => { setQ(e.target.value); setActive(0); }}
            onKeyDown={onKeyDown}
          />
        </div>
      </div>

      <div className="dn-nm-hint">
        <span className="dn-key">↑↓</span> navigate · <span className="dn-key">↵</span> add ·
        pick more than one for a group
      </div>

      {/* INLINE suggestions — plain rows on the page, no dropdown box */}
      <div className="dn-suggest">
        {peopleMatches.length > 0 && <div className="dn-suggest-group">People</div>}
        {peopleMatches.map((p, i) => (
          <div key={p.id}
               className={`dn-suggest-row ${i === active ? "is-active" : ""}`}
               onMouseEnter={() => setActive(i)}
               onClick={() => addPerson(p)}>
            <span className="dn-avatar" style={{ background: p.color, position: "relative" }}>
              {p.initials}
              {p.presence && <span className="dn-presence" style={{ background: presenceColor(p.presence) }} />}
            </span>
            <div className="dn-suggest-name">
              {p.name}
              <span className="dn-suggest-sub">
                {p.handle ? `@${p.handle}` : p.email}{p.presence ? ` · ${p.presence}` : ""}
              </span>
            </div>
            {p.role && <span className="dn-suggest-role">{p.role}</span>}
          </div>
        ))}

        {channelMatches.length > 0 && <div className="dn-suggest-group">Channels</div>}
        {channelMatches.map((c) => (
          <div key={c.id} className="dn-suggest-row"
               onClick={() => onStart?.({ userIds: [], channelId: c.id })}>
            <span className="dn-hashbox"><Icon name={c.private ? "lock" : "hash"} size={15} /></span>
            <div className="dn-suggest-name">
              {c.name}{c.private && <span className="dn-suggest-sub">private</span>}
            </div>
          </div>
        ))}

        {showInvite && (
          <>
            <div className="dn-suggest-rule" />
            <div className="dn-suggest-row" onClick={() => onInvite?.(q.trim())}>
              <span className="dn-hashbox"><Icon name="mail" size={15} /></span>
              <div className="dn-suggest-name dn-suggest-invite">
                Invite <span className="dn-mono" style={{ color: "var(--dn-grape-deep)" }}>{q.trim()}</span>
              </div>
            </div>
          </>
        )}
      </div>

      <div className="dn-nm-composer">
        <div className="txt">
          {canStart ? "Start a new message…" : "Add someone above to start…"}
        </div>
        <div className="tools">
          <b>B</b><i style={{ fontStyle: "italic" }}>I</i>
          <Icon name="link" /><Icon name="at" /><Icon name="smile" /><Icon name="plus" />
          <button className="dn-send" disabled={!canStart} onClick={start} aria-label="Start chat">
            <Icon name="send" />
          </button>
        </div>
      </div>
    </div>
  );
}

function presenceColor(p) {
  if (p === "active" || p === "active now") return "var(--dn-ok)";
  if (p === "away") return "oklch(0.70 0.15 70)";
  return "var(--dn-t4)"; // offline
}
