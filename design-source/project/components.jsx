// ════════════════════════════════════════════════════════════════
//  GOOFY UI — component library  🦔
//  Reusable React components for the bouncy sticker-book aesthetic.
//  Pair with goofy-ui.css. Render anything inside a <div className="gx">
//  (add "dark" for Midnight goofy). All components export to window.
// ════════════════════════════════════════════════════════════════

/* ── Self-contained icon set (stroke = currentColor) ─────────── */
const GIc = {
  hash:    (p={}) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" {...p}><line x1="4" y1="9" x2="20" y2="9"/><line x1="4" y1="15" x2="20" y2="15"/><line x1="10" y1="3" x2="8" y2="21"/><line x1="16" y1="3" x2="14" y2="21"/></svg>,
  search:  (p={}) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" {...p}><circle cx="11" cy="11" r="7"/><line x1="20" y1="20" x2="16.5" y2="16.5"/></svg>,
  plus:    (p={}) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" {...p}><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>,
  check:   (p={}) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" {...p}><polyline points="20 6 9 17 4 12"/></svg>,
  x:       (p={}) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" {...p}><line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/></svg>,
  send:    (p={}) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>,
  sparkle: (p={}) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M12 2l2 6 6 2-6 2-2 6-2-6-6-2 6-2z"/></svg>,
  bolt:    (p={}) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...p}><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>,
  brain:   (p={}) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15A2.5 2.5 0 0 1 7 19c-2 0-3.5-2-3.5-4 0-1 .5-2 1.5-2.5C4 11.5 4 9.5 5 8.5c-.5-1 0-3 2-3.5A2.5 2.5 0 0 1 9.5 2z"/><path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15A2.5 2.5 0 0 0 17 19c2 0 3.5-2 3.5-4 0-1-.5-2-1.5-2.5 1-1 1-3 0-4 .5-1 0-3-2-3.5A2.5 2.5 0 0 0 14.5 2z"/></svg>,
  doc:     (p={}) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="13" y2="17"/></svg>,
  smile:   (p={}) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" {...p}><circle cx="12" cy="12" r="9"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/></svg>,
  reply:   (p={}) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...p}><polyline points="9 17 4 12 9 7"/><path d="M20 18v-2a4 4 0 0 0-4-4H4"/></svg>,
  more:    (p={}) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" {...p}><circle cx="5" cy="12" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="19" cy="12" r="1.4"/></svg>,
  edit:    (p={}) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/></svg>,
  trash:   (p={}) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...p}><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/></svg>,
  pin:     (p={}) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M12 17v5"/><path d="M9 10.8V4h6v6.8l2 3.2H7z"/></svg>,
  share:   (p={}) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...p}><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.6" y1="13.5" x2="15.4" y2="17.5"/><line x1="15.4" y1="6.5" x2="8.6" y2="10.5"/></svg>,
  link:    (p={}) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7L12 19"/></svg>,
};
function GlyphSlot({ name, size = 16 }) {
  const fn = GIc[name];
  if (!fn) return null;
  return fn({ width: size, height: size });
}

/* ── Avatars ─────────────────────────────────────────────────── */
function GAvatar({ name = "??", color = "var(--pop-coral)", size = "", agent = false, pulsing = false }) {
  const cls = `gx-av ${size}${agent ? " agent" : ""}${pulsing ? " pulsing" : ""}`;
  const initials = name.length <= 2 ? name : name.split(/\s+/).map(w => w[0]).slice(0, 2).join("");
  return <div className={cls} style={agent ? {} : { background: color }}>{initials.toUpperCase()}</div>;
}
function GAvatarStack({ people = [] }) {
  return <div className="gx-av-stack">{people.map((p, i) => <GAvatar key={i} {...p} />)}</div>;
}

/* ── Buttons ─────────────────────────────────────────────────── */
function GButton({ variant = "", size = "", icon, iconRight, children, ...rest }) {
  return (
    <button className={`gx-btn ${variant ? "gx-btn--" + variant : ""} ${size ? "gx-btn--" + size : ""}`} {...rest}>
      {icon && <GlyphSlot name={icon} size={15} />}
      {children}
      {iconRight && <GlyphSlot name={iconRight} size={15} />}
    </button>
  );
}
function GIconButton({ icon, outlined = false, ...rest }) {
  return (
    <button className={`gx-btn-icon${outlined ? " gx-btn-icon--outlined" : ""}`} {...rest}>
      <GlyphSlot name={icon} size={17} />
    </button>
  );
}

/* ── Inputs ──────────────────────────────────────────────────── */
function GInput({ icon = "search", placeholder = "Search…", kbd, value, onChange }) {
  return (
    <label className="gx-input">
      {icon && <GlyphSlot name={icon} size={16} />}
      <input placeholder={placeholder} value={value} onChange={onChange} />
      {kbd && <kbd>{kbd}</kbd>}
    </label>
  );
}
function GField({ ai = false, placeholder = "Write something…", rows = 3, value, onChange, children }) {
  return (
    <div className={`gx-field${ai ? " gx-field--ai" : ""}`}>
      <textarea rows={rows} placeholder={placeholder} value={value} onChange={onChange} />
      {children}
    </div>
  );
}

/* ── Chips & tags ────────────────────────────────────────────── */
function GChip({ active = false, onRemove, onClick, children }) {
  return (
    <button className={`gx-chip${active ? " is-active" : ""}`} onClick={onClick}>
      {children}
      {onRemove && <span className="gx-chip-x" onClick={(e) => { e.stopPropagation(); onRemove(); }}><GlyphSlot name="x" size={11} /></span>}
    </button>
  );
}
function GTag({ variant = "", count, children }) {
  return (
    <span className={`gx-tag ${variant ? "gx-tag--" + variant : ""}`}>
      {children}
      {count != null && <span className="count">{count}</span>}
    </span>
  );
}

/* ── Badges ──────────────────────────────────────────────────── */
function GBadge({ mention = false, children }) {
  return <span className={`gx-badge${mention ? " gx-badge--mention" : ""}`}>{children}</span>;
}
function GRoleChip({ children = "AI" }) {
  return <span className="gx-role-chip">{children}</span>;
}

/* ── Cards ───────────────────────────────────────────────────── */
function GCard({ ai = false, hover = false, title, sub, children, ...rest }) {
  return (
    <div className={`gx-card${ai ? " gx-card--ai" : ""}${hover ? " gx-card--hover" : ""}`} {...rest}>
      {title && <div className="gx-card-title">{title}</div>}
      {sub && <div className="gx-card-sub">{sub}</div>}
      {children}
    </div>
  );
}
function GStat({ value, label }) {
  return <div className="gx-card gx-stat"><div className="v">{value}</div><div className="l">{label}</div></div>;
}

/* ── Lists ───────────────────────────────────────────────────── */
function GList({ children }) { return <div className="gx-list">{children}</div>; }
function GListItem({ active = false, hash, dot, badge, onClick, children }) {
  return (
    <div className={`gx-list-item${active ? " is-active" : ""}`} onClick={onClick}>
      {hash && <span className="hash">{hash}</span>}
      {dot && <span className={`dot ${dot}`} />}
      <span className="grow">{children}</span>
      {badge}
    </div>
  );
}
function GDoc({ icon = "doc", name, meta, onClick }) {
  return (
    <div className="gx-doc" onClick={onClick}>
      <span className="icon"><GlyphSlot name={icon} size={15} /></span>
      <span className="grow">{name}</span>
      {meta && <span className="meta">{meta}</span>}
    </div>
  );
}

/* ── Toggles ─────────────────────────────────────────────────── */
function GCheck({ checked = false, onChange }) {
  return (
    <span className={`gx-check${checked ? " is-checked" : ""}`} onClick={() => onChange && onChange(!checked)}>
      {checked && <GlyphSlot name="check" size={12} />}
    </span>
  );
}
function GTaskCheck({ state = "todo" }) {
  return (
    <span className={`gx-task-check${state === "done" ? " is-done" : ""}${state === "running" ? " is-running" : ""}`}>
      {state === "done" && <GlyphSlot name="check" size={11} />}
    </span>
  );
}
function GSwitch({ on = false, onChange }) {
  return <span className={`gx-switch${on ? " is-on" : ""}`} onClick={() => onChange && onChange(!on)} />;
}

/* ── Popovers / menus / toolbar ──────────────────────────────── */
function GPopover({ children }) { return <div className="gx-popover">{children}</div>; }
function GMenuItem({ icon, ai = false, danger = false, kbd, onClick, children }) {
  return (
    <div className={`gx-menu-item${ai ? " is-ai" : ""}${danger ? " is-danger" : ""}`} onClick={onClick}>
      {icon && <span className="icon"><GlyphSlot name={icon} size={15} /></span>}
      <span className="grow">{children}</span>
      {kbd && <kbd>{kbd}</kbd>}
    </div>
  );
}
function GMenuSep() { return <div className="gx-menu-sep" />; }
function GToolbar({ actions = [] }) {
  return (
    <div className="gx-toolbar">
      {actions.map((a, i) => (
        <button key={i} className={`tb${a.ai ? " ai" : ""}`} title={a.title} onClick={a.onClick}>
          <GlyphSlot name={a.icon} size={15} />
        </button>
      ))}
    </div>
  );
}
function GTooltip({ children }) { return <span className="gx-tooltip">{children}</span>; }

/* ── Tabs ────────────────────────────────────────────────────── */
function GTabs({ tabs = [], value, onChange }) {
  return (
    <div className="gx-tabs">
      {tabs.map(t => (
        <span key={t} className={`gx-tab${value === t ? " is-active" : ""}`} onClick={() => onChange && onChange(t)}>{t}</span>
      ))}
    </div>
  );
}

/* ── Chat bubbles ────────────────────────────────────────────── */
function GBubble({ from = "agent", avatar, children }) {
  if (from === "user") return <div className="gx-bubble user">{children}</div>;
  return (
    <div className="gx-bubble agent">
      {avatar || <GAvatar name="AG" agent />}
      <div className="text">{children}</div>
    </div>
  );
}

/* ── Agent run card (showpiece) ──────────────────────────────── */
function GRunStep({ icon = "bolt", label, meta, state }) {
  return (
    <div className="gx-run-step">
      <span className="step-icon"><GlyphSlot name={icon} size={13} /></span>
      <span className="label">{label}</span>
      {meta && <span className="meta">{meta}</span>}
      {state && <span className={`state${state === "running" ? " running" : ""}`}>{state}</span>}
    </div>
  );
}
function GRun({ label = "Agent run", summary, status = "done", thought, steps = [], output, memory, running = false }) {
  return (
    <div className="gx-run">
      <div className="gx-run-head">
        <span className="label">{label}</span>
        {summary && <span className="summary">{summary}</span>}
        <span className="grow" />
        <span className="status"><span className={`gx-led ${running ? "running" : "done"}`} />{status}</span>
      </div>
      <div className="gx-run-body">
        {thought && <div className="gx-run-thought"><span>{thought}{running && <span className="dots" />}</span></div>}
        {steps.map((s, i) => <GRunStep key={i} {...s} />)}
        {output && <div className="gx-run-output">{output}</div>}
      </div>
      {(memory || output) && (
        <div className="gx-run-foot">
          {memory && <span className="mem"><GlyphSlot name="brain" size={12} />{memory}</span>}
          <span className="grow" />
          <span className="act">Dismiss</span>
          <span className="act primary">Approve</span>
        </div>
      )}
    </div>
  );
}

/* ── Export everything to window for cross-file Babel use ────── */
Object.assign(window, {
  GIc, GlyphSlot,
  GAvatar, GAvatarStack,
  GButton, GIconButton,
  GInput, GField,
  GChip, GTag,
  GBadge, GRoleChip,
  GCard, GStat,
  GList, GListItem, GDoc,
  GCheck, GTaskCheck, GSwitch,
  GPopover, GMenuItem, GMenuSep, GToolbar, GTooltip,
  GTabs, GBubble,
  GRun, GRunStep,
});
