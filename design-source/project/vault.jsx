// Full-screen Vault workspace
function Vault({ onClose }) {
  const items = window.VAULT_DATA.items;
  const resurfaced = window.VAULT_DATA.resurfaced;
  const [selectedId, setSelectedId] = React.useState(items[0].id);
  const [filter, setFilter] = React.useState("all");
  const [mode, setMode] = React.useState("list"); // list | timeline
  const [q, setQ] = React.useState("");

  const filteredItems = React.useMemo(() => {
    let arr = items;
    if (filter !== "all") arr = arr.filter(i => i.type === filter);
    if (q.trim()) {
      const lq = q.toLowerCase();
      arr = arr.filter(i =>
        i.title.toLowerCase().includes(lq) ||
        (i.summary || "").toLowerCase().includes(lq) ||
        (i.tags || []).some(t => t.toLowerCase().includes(lq))
      );
    }
    return arr;
  }, [items, filter, q]);

  const selected = items.find(i => i.id === selectedId);

  const typeCounts = items.reduce((acc, i) => {
    acc[i.type] = (acc[i.type] || 0) + 1;
    return acc;
  }, {});

  return (
    <div className="vault-fullscreen">
      <div className="vh">
        <div className="glyph"><Ic.archive width="18" height="18"/></div>
        <div>
          <div className="title">Vault</div>
          <div className="sub">{items.length.toLocaleString()} of 5,931 items shown · indexed by Donna · last updated 2 min ago</div>
        </div>
        <div className="spacer"/>
        <div className="vmodes">
          <button className={"vmode " + (mode === "list" ? "active" : "")} onClick={() => setMode("list")}>List</button>
          <button className={"vmode " + (mode === "timeline" ? "active" : "")} onClick={() => setMode("timeline")}>Timeline</button>
        </div>
        <button className="close" onClick={onClose} title="Close vault">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/></svg>
        </button>
      </div>

      <div className="vault-ask">
        <Ic.sparkle className="icon"/>
        <input
          placeholder="Ask the vault: 'why did we pick v3?' · 'what did Q1 review find?' · 'show every decision from Atlas this quarter'"
          value={q} onChange={e => setQ(e.target.value)}
        />
        <span className="hint">⌘ + return</span>
        <button className="ask-btn">Ask Donna</button>
      </div>

      <div style={{ display: mode === "list" ? "contents" : "none" }}>
        <div className="vault-resurface">
          <div className="rh">
            <Ic.sparkle/>
            <span>Resurfaced for you · because of what you're working on right now</span>
          </div>
          <div className="rcards">
            {resurfaced.map(r => {
              const it = items.find(i => i.id === r.itemId);
              if (!it) return null;
              return (
                <div key={r.id} className="rc" onClick={() => setSelectedId(it.id)} style={{ cursor: "default" }}>
                  <div className="type-row">{it.type}</div>
                  <div className="rtitle">{it.title}</div>
                  <div className="reason">{r.reason}</div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="vault-grid3">
          <VaultFilters filter={filter} setFilter={setFilter} typeCounts={typeCounts} total={items.length}/>
          <div className="vault-list">
            <div className="vault-list-head">
              <span className="label">{filteredItems.length} items</span>
              <span className="spacer"/>
              <span className="sort">Newest <Ic.caret/></span>
            </div>
            {filteredItems.map(item => (
              <VaultListItem
                key={item.id}
                item={item}
                active={item.id === selectedId}
                onClick={() => setSelectedId(item.id)}
              />
            ))}
          </div>
          <div className="vault-detail">
            {selected ? <VaultDetail item={selected}/> : <VaultEmpty/>}
          </div>
        </div>
      </div>

      {mode === "timeline" && <VaultTimeline items={filteredItems} onSelect={(id) => { setSelectedId(id); setMode("list"); }}/>}
    </div>
  );
}

function VaultFilters({ filter, setFilter, typeCounts, total }) {
  const types = [
    { id: "all", name: "Everything", icon: <Ic.archive/>, count: total },
    { id: "decision", name: "Decisions", icon: "✓", count: typeCounts.decision || 0, color: "oklch(0.78 0.18 32)" },
    { id: "run", name: "Past agent runs", icon: <Ic.sparkle/>, count: typeCounts.run || 0, color: "var(--ai)" },
    { id: "doc", name: "Documents", icon: <Ic.doc/>, count: typeCounts.doc || 0, color: "oklch(0.78 0.14 220)" },
    { id: "link", name: "Links", icon: <Ic.link/>, count: typeCounts.link || 0, color: "oklch(0.78 0.16 145)" },
    { id: "channel", name: "Archived channels", icon: <Ic.hash/>, count: typeCounts.channel || 0 },
  ];
  return (
    <aside className="vault-filters">
      <h3>By type</h3>
      {types.map(t => (
        <div key={t.id} className={"vf " + (filter === t.id ? "active" : "")} onClick={() => setFilter(t.id)}>
          <span style={{ color: t.color || "var(--text-2)", width: 14, display: "inline-grid", placeItems: "center" }}>{t.icon}</span>
          <span>{t.name}</span>
          <span className="count">{t.count.toLocaleString()}</span>
        </div>
      ))}

      <h3>By project</h3>
      {window.DONNA_DATA.projects.map(p => (
        <div key={p.id} className="vf">
          <span className="glyph" style={{ background: p.color }}>{p.glyph}</span>
          <span>{p.name}</span>
          <span className="count">{Math.floor(Math.random() * 80 + 20)}</span>
        </div>
      ))}

      <h3>By teammate</h3>
      {["donna", "mira", "kai", "atlas"].map(id => {
        const a = window.lookup(id);
        return (
          <div key={id} className="vf">
            <Av kind="agent" agent={a} size="sm"/>
            <span>{a.name}</span>
            <span className="count">{Math.floor(Math.random() * 200 + 50)}</span>
          </div>
        );
      })}
      {["marius", "rebeca"].map(id => {
        const h = window.lookup(id);
        return (
          <div key={id} className="vf">
            <Av kind="human" who={h} size="sm"/>
            <span>{h.name}</span>
            <span className="count">{Math.floor(Math.random() * 40 + 10)}</span>
          </div>
        );
      })}

      <h3>Tags</h3>
      {["strategic", "research", "competitive", "protocol", "brand", "launch", "Q2"].map(tag => (
        <div key={tag} className="vf" style={{ fontSize: 12 }}>
          <span style={{ color: "var(--text-3)", fontFamily: "Geist Mono", fontSize: 11, width: 14, textAlign: "center" }}>#</span>
          <span>{tag}</span>
        </div>
      ))}
    </aside>
  );
}

function typeIcon(type) {
  if (type === "decision") return <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><polyline points="5 12 10 17 19 7"/></svg>;
  if (type === "run") return <Ic.sparkle/>;
  if (type === "doc") return <Ic.doc/>;
  if (type === "link") return <Ic.link/>;
  if (type === "channel") return <Ic.hash/>;
  return <Ic.file/>;
}

function VaultListItem({ item, active, onClick }) {
  const who = window.lookup(item.who);
  return (
    <div className={"vault-item " + (active ? "active" : "")} onClick={onClick}>
      <div className={"type-icon " + item.type}>{typeIcon(item.type)}</div>
      <div className="body">
        <div className="vmeta">
          <span className={"type " + item.type}>{item.type}</span>
          <span style={{ color: "var(--text-3)" }}>·</span>
          <span style={{ textTransform: "none", letterSpacing: 0, fontWeight: 400, color: "var(--text-3)", fontFamily: "Geist Mono" }}>{item.ago}</span>
        </div>
        <div className="vtitle">{item.title}</div>
        <div className="vsub">
          <Av kind={who.kind} who={who} agent={who} size="sm"/>
          <span>{who.name}</span>
          <span style={{ color: "var(--text-3)" }}>·</span>
          <span className="where">{item.where}</span>
        </div>
      </div>
    </div>
  );
}

function VaultEmpty() {
  return (
    <div className="empty-state">
      <div className="icon"><Ic.archive width="22" height="22"/></div>
      <div className="et">Pick an item to inspect</div>
      <div className="es">Decisions show what was chosen, why, and who decided. Past agent runs replay the full thinking process and outputs.</div>
    </div>
  );
}

function VaultDetail({ item }) {
  if (item.type === "decision") return <VaultDecision item={item}/>;
  if (item.type === "run") return <VaultRun item={item}/>;
  if (item.type === "doc") return <VaultDoc item={item}/>;
  if (item.type === "link") return <VaultLink item={item}/>;
  if (item.type === "channel") return <VaultChannel item={item}/>;
  return null;
}

function DetailHead({ item, badge }) {
  const who = window.lookup(item.who);
  return (
    <div className="vd-head">
      <div className="badge-row">
        <span className={"type-badge " + item.type}>{typeIcon(item.type)} {badge || item.type}</span>
        <span className="ago">{item.when} · {item.where}</span>
      </div>
      <h1>{item.title}</h1>
      <div className="summary">{item.summary}</div>
      <div className="actions">
        <button className="a primary">Open in channel</button>
        <button className="a ai"><Ic.sparkle/> Continue with Donna</button>
        <button className="a">Pin to channel</button>
        <button className="a">Share</button>
        <button className="a" style={{ padding: "6px 10px" }}><Ic.more/></button>
      </div>
      <div style={{
        display: "flex", alignItems: "center", gap: 6, marginTop: 14,
        fontSize: 11.5, color: "var(--text-3)"
      }}>
        Created by
        <Av kind={who.kind} who={who} agent={who} size="sm"/>
        <span style={{ color: "var(--text-1)" }}>{who.name}</span>
        <span>·</span>
        <span>{item.ago}</span>
      </div>
    </div>
  );
}

function VaultDecision({ item }) {
  return (
    <>
      <DetailHead item={item} badge="Decision"/>
      <div className="vd-block">
        <h3>Options considered</h3>
        <div className="vd-considered">
          {item.considered.map((opt, i) => (
            <div key={i} className={"opt " + (opt.chosen ? "chosen" : "")}>
              <div className="marker">
                {opt.chosen && <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round"><polyline points="5 12 10 17 19 7"/></svg>}
              </div>
              <div className="body">
                <div className="name">{opt.option}</div>
                <div className="verdict">{opt.verdict}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="vd-block">
        <h3>Rationale</h3>
        <div className="vd-rationale">{item.rationale}</div>
      </div>

      <div className="vd-block">
        <h3>People</h3>
        <div className="vd-people">
          <div className="pr">
            <span className="role">Decided by</span>
            <div className="avs">
              {item.decided_by.map(id => {
                const w = window.lookup(id);
                return <Av key={id} kind={w.kind} who={w} agent={w} size="sm"/>;
              })}
            </div>
            <span className="name">{item.decided_by.map(id => window.lookup(id).name).join(", ")}</span>
          </div>
          <div className="pr">
            <span className="role">Consulted</span>
            <div className="avs">
              {item.consulted.map(id => {
                const w = window.lookup(id);
                return <Av key={id} kind={w.kind} who={w} agent={w} size="sm"/>;
              })}
            </div>
            <span className="name">{item.consulted.map(id => window.lookup(id).name).join(", ")}</span>
          </div>
        </div>
      </div>

      <div className="vd-block">
        <h3>Affects</h3>
        <div className="vd-affects">
          {item.affected.map(c => (
            <span key={c} className="c"><Ic.hash/>{c.replace("#", "")}</span>
          ))}
        </div>
      </div>

      <div className="vd-block">
        <h3>Follow-ups & provenance</h3>
        <div className="vd-prov">
          <span className="step">
            <Ic.thread style={{ color: "var(--text-3)" }}/>
            <span>{item.thread || 24} msg thread</span>
          </span>
          <span className="arrow">→</span>
          <span className="step now">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><polyline points="5 12 10 17 19 7"/></svg>
            <span>Decision (this)</span>
          </span>
          <span className="arrow">→</span>
          <span className="step">
            <Ic.bolt style={{ color: "var(--text-3)" }}/>
            <span>{item.followups} follow-up tasks created</span>
          </span>
          {item.runs > 0 && (
            <>
              <span className="arrow">→</span>
              <span className="step" style={{ color: "var(--ai)" }}>
                <Ic.sparkle/>
                <span>{item.runs} downstream agent run</span>
              </span>
            </>
          )}
        </div>
      </div>
    </>
  );
}

function VaultRun({ item }) {
  return (
    <>
      <DetailHead item={item} badge="Past agent run"/>
      <div className="vd-block">
        <h3>Run metadata</h3>
        <div className="vd-meta-grid">
          <div className="mi"><div className="l">Duration</div><div className="v">{item.duration}</div></div>
          <div className="mi"><div className="l">Tokens</div><div className="v">{item.tokens}</div></div>
          <div className="mi"><div className="l">Tool calls</div><div className="v">{item.tools.reduce((a, t) => a + t.calls, 0)}</div></div>
        </div>
      </div>

      <div className="vd-block">
        <h3>Tools used</h3>
        <div className="vd-run-steps">
          {item.tools.map((t, i) => (
            <div key={i} className="rs">
              <span className="tool">{t.name}</span>
              <span style={{ color: "var(--text-2)", fontSize: 12.5 }}>{t.calls} calls</span>
              <span className="calls">→</span>
            </div>
          ))}
        </div>
      </div>

      <div className="vd-block">
        <h3>Output</h3>
        <div className="vd-output">{item.output_preview}</div>
      </div>

      <div className="vd-block">
        <h3>What was added to memory</h3>
        <div className="vd-learned">
          {item.learned && item.learned.map((l, i) => (
            <div key={i} className="li">{l}</div>
          ))}
        </div>
      </div>

      <div className="vd-block">
        <div style={{ display: "flex", gap: 8 }}>
          <button className="a" style={{ fontSize: 12, padding: "8px 14px", borderRadius: 7, background: "var(--ai-bg)", color: "var(--ai)", border: "1px solid var(--ai-glow)" }}>
            ↻ Replay this run
          </button>
          <button className="a" style={{ fontSize: 12, padding: "8px 14px", borderRadius: 7, background: "var(--bg-2)", color: "var(--text-1)", border: "1px solid var(--border)" }}>
            Fork as new prompt
          </button>
        </div>
      </div>
    </>
  );
}

function VaultDoc({ item }) {
  return (
    <>
      <DetailHead item={item} badge="Document"/>
      <div className="vd-block">
        <h3>Metadata</h3>
        <div className="vd-meta-grid">
          <div className="mi"><div className="l">Pages</div><div className="v">{item.pages}</div></div>
          <div className="mi"><div className="l">Size</div><div className="v">{item.size}</div></div>
          <div className="mi"><div className="l">Cited in</div><div className="v">{item.cited_in} convos</div></div>
        </div>
      </div>
      <div className="vd-block">
        <h3>Excerpt</h3>
        <div className="vd-excerpt">"{item.excerpt}"</div>
      </div>
      <div className="vd-block">
        <h3>Readers</h3>
        <div className="vd-readers">
          <div className="stack">
            {item.readers.map(id => {
              const w = window.lookup(id);
              return <Av key={id} kind={w.kind} who={w} agent={w} size="sm"/>;
            })}
          </div>
          <span style={{ fontSize: 12, color: "var(--text-2)", marginLeft: 6 }}>{item.readers.length} of 12 members</span>
          {item.ai_indexed && (
            <span style={{ marginLeft: "auto", fontSize: 11.5, color: "var(--ai)", display: "flex", alignItems: "center", gap: 6, padding: "3px 8px", background: "var(--ai-bg)", border: "1px solid var(--ai-glow)", borderRadius: 5 }}>
              <Ic.brain/> Indexed for agents
            </span>
          )}
        </div>
      </div>
    </>
  );
}

function VaultLink({ item }) {
  return (
    <>
      <DetailHead item={item} badge="Link"/>
      <div className="vd-block">
        <h3>Source</h3>
        <div className="vd-prov">
          <span className="step"><Ic.link style={{ color: "var(--text-3)" }}/><span style={{ fontFamily: "Geist Mono", color: "var(--text-1)" }}>{item.domain}</span></span>
        </div>
      </div>
      <div className="vd-block">
        <h3>Mira's note</h3>
        <div className="vd-excerpt" style={{ borderLeftColor: "var(--ai)" }}>{item.notes}</div>
      </div>
      <div className="vd-block">
        <h3>Shared in</h3>
        <div className="vd-affects">
          {item.shared_in.map(c => <span key={c} className="c"><Ic.hash/>{c.replace("#", "")}</span>)}
        </div>
      </div>
    </>
  );
}

function VaultChannel({ item }) {
  return (
    <>
      <DetailHead item={item} badge="Archived channel"/>
      <div className="vd-block">
        <h3>Channel snapshot</h3>
        <div className="vd-meta-grid">
          <div className="mi"><div className="l">Messages</div><div className="v">{item.messages.toLocaleString()}</div></div>
          <div className="mi"><div className="l">Members</div><div className="v">{item.members}</div></div>
          <div className="mi"><div className="l">Span</div><div className="v">18 mo</div></div>
        </div>
      </div>
      <div className="vd-block">
        <div style={{ display: "flex", gap: 8 }}>
          <button className="a" style={{ fontSize: 12, padding: "8px 14px", borderRadius: 7, background: "var(--bg-2)", color: "var(--text-0)", border: "1px solid var(--border)" }}>
            Browse read-only
          </button>
          <button className="a" style={{ fontSize: 12, padding: "8px 14px", borderRadius: 7, background: "var(--ai-bg)", color: "var(--ai)", border: "1px solid var(--ai-glow)" }}>
            ✦ Have Donna summarize
          </button>
        </div>
      </div>
    </>
  );
}

function VaultTimeline({ items, onSelect }) {
  // Group by month
  const byDate = {};
  items.forEach(it => {
    const day = it.when.split(",")[0]; // e.g. "Apr 8"
    byDate[day] = byDate[day] || [];
    byDate[day].push(it);
  });
  const days = Object.keys(byDate);
  return (
    <div className="vault-timeline">
      {days.map(d => (
        <div key={d}>
          <div className="day">
            <span className="d">{d}</span>
            <span className="line"/>
            <span className="d" style={{ color: "var(--text-3)" }}>{byDate[d].length} items</span>
          </div>
          {byDate[d].map(item => {
            const who = window.lookup(item.who);
            return (
              <div key={item.id} className="tl-item" onClick={() => onSelect(item.id)}>
                <span className="when">{item.when.split("·")[1] || item.when.split(",")[1]}</span>
                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                    <span className={"type-badge " + item.type} style={{
                      display: "inline-flex", alignItems: "center", gap: 5,
                      padding: "2px 8px", borderRadius: 5,
                      fontSize: 10, letterSpacing: 0.5, textTransform: "uppercase", fontWeight: 600,
                    }}>{typeIcon(item.type)} {item.type}</span>
                    <Av kind={who.kind} who={who} agent={who} size="sm"/>
                    <span style={{ fontSize: 12, color: "var(--text-2)" }}>{who.name}</span>
                    <span style={{ fontSize: 11.5, color: "var(--ai-dim)", fontFamily: "Geist Mono", marginLeft: "auto" }}>{item.where}</span>
                  </div>
                  <div style={{ fontSize: 13.5, color: "var(--text-0)", fontWeight: 500 }}>{item.title}</div>
                  <div style={{ fontSize: 12.5, color: "var(--text-2)", marginTop: 3, lineHeight: 1.5 }}>{item.summary}</div>
                </div>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

Object.assign(window, { Vault });
