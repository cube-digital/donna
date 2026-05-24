// Sidebar — workspace channels, DMs, projects
function Sidebar({ view, setView, channel, setChannel, currentAgent, setCurrentAgent }) {
  const d = window.DONNA_DATA;
  const [collapsed, setCollapsed] = React.useState({});

  const toggleProject = (id) => setCollapsed(c => ({ ...c, [id]: !c[id] }));

  return (
    <aside className="sidebar">
      <div className="ws-header">
        <div>
          <div className="ws-name">Cube</div>
          <div className="ws-sub">cube-digital.io</div>
        </div>
        <div className="ws-actions">
          <button className="icon-btn" title="New message"><Ic.edit/></button>
        </div>
      </div>

      {/* Top-level nav */}
      <div className="group" style={{ marginTop: 4 }}>
        <div className={"item " + (view === "search" ? "active" : "")} onClick={() => setView("search")}>
          <Ic.search style={{ color: "var(--text-3)" }}/>
          <span className="name">Search & history</span>
          <kbd style={{ fontSize: 10, fontFamily: "'Geist Mono'", color: "var(--text-3)", padding: "1px 4px", borderRadius: 3, background: "var(--bg-2)" }}>⌘K</kbd>
        </div>
        <div className={"item " + (view === "personal" ? "active" : "")} onClick={() => { setView("personal"); setCurrentAgent("donna"); }}>
          <span className="dot ai"/>
          <span className="name" style={{ color: "var(--text-0)" }}>Personal · Donna</span>
        </div>
        <div className="item">
          <Ic.bell style={{ color: "var(--text-3)" }}/>
          <span className="name">Activity</span>
          <span className="badge mention">3</span>
        </div>
        <div className="item">
          <Ic.thread style={{ color: "var(--text-3)" }}/>
          <span className="name">Threads</span>
        </div>
      </div>

      {/* Direct messages */}
      <div className="group">
        <div className="group-h">
          <span>Direct messages</span>
          <button className="add"><Ic.plus/></button>
        </div>
        {d.humans.filter(h => h.id !== "you").slice(0, 4).map(h => (
          <div key={h.id} className="item">
            <Av kind="human" who={h} size="sm"/>
            <span className="name">{h.name}</span>
            <span className="dot online"/>
          </div>
        ))}
        <div className="item">
          <Av kind="human" who={{ initials: "AT", color: "#7a8fd9" }} size="sm"/>
          <span className="name">Andreea I.</span>
        </div>
      </div>

      {/* AI Teammates */}
      <div className="group">
        <div className="group-h" style={{ color: "var(--ai)" }}>
          <span>AI Teammates</span>
          <button className="add"><Ic.plus/></button>
        </div>
        {d.agents.map(a => (
          <div
            key={a.id}
            className={"item " + (view === "profile" && currentAgent === a.id ? "active" : "")}
            onClick={() => { setView("profile"); setCurrentAgent(a.id); }}
          >
            <Av kind="agent" agent={a} size="sm"/>
            <span className="name">{a.name}</span>
            <span className="dot ai" title="Active"/>
          </div>
        ))}
      </div>

      {/* Projects */}
      {d.projects.map(p => {
        const isCollapsed = collapsed[p.id];
        return (
          <div key={p.id} className="group">
            <div
              className={"project-h " + (isCollapsed ? "collapsed" : "")}
              onClick={() => toggleProject(p.id)}
              style={{ cursor: "default" }}
            >
              <span className="glyph" style={{ background: p.color, color: "#fff" }}>{p.glyph}</span>
              <span>{p.name}</span>
              <span className="caret"><Ic.caret/></span>
            </div>
            {!isCollapsed && (
              <div className="sub">
                <div
                  className="item"
                  onClick={() => { setView("workspace"); setChannel(p.id + ":overview"); }}
                  style={{ color: "var(--text-2)" }}
                >
                  <Ic.folder style={{ color: "var(--text-3)" }}/>
                  <span className="name" style={{ fontSize: 12 }}>Overview</span>
                </div>
                {p.channels.map(c => {
                  const active = view === "channel" && channel === c;
                  const isUnread = c === "recist-protocol" || c === "launch-press";
                  const hasMention = c === "recist-protocol";
                  return (
                    <div
                      key={c}
                      className={"item " + (active ? "active" : "") + (isUnread ? " unread" : "")}
                      onClick={() => { setView("channel"); setChannel(c); }}
                    >
                      <span className="hash"><Ic.hash/></span>
                      <span className="name">{c}</span>
                      {hasMention && <span className="badge mention">2</span>}
                    </div>
                  );
                })}
                {p.id === "recist" && (
                  <div className="item" onClick={() => { setView("empty"); setChannel("recist-models"); }}>
                    <span className="hash"><Ic.hash/></span>
                    <span className="name" style={{ color: "var(--text-3)" }}>recist-models</span>
                    <span className="badge" style={{ fontSize: 9 }}>new</span>
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}

      <div className="group">
        <div className="group-h">
          <span>Apps</span>
          <button className="add"><Ic.plus/></button>
        </div>
        <div className="item">
          <span style={{ width: 14, color: "var(--text-3)" }}>⌘</span>
          <span className="name">Workflows</span>
        </div>
      </div>
    </aside>
  );
}

// Workspace rail (far left, icon-only)
function WsRail({ view, setView, openVault }) {
  return (
    <div className="wsrail">
      <div className="ws-pill active">C</div>
      <div className="ws-pill" style={{ background: "var(--bg-1)", color: "var(--text-3)" }}>+</div>
      <div className="ws-sep"/>
      <button className={"ws-icon " + (view === "channel" || view === "workspace" || view === "empty" ? "active" : "")} title="Workspace" onClick={() => setView("channel")}>
        <Ic.home/>
      </button>
      <button className="ws-icon" title="DMs">
        <Ic.msg/>
      </button>
      <button className={"ws-icon ai " + (view === "personal" ? "active" : "")} title="Personal AI" onClick={() => setView("personal")}>
        <Ic.sparkle width="20" height="20"/>
      </button>
      <button className={"ws-icon " + (view === "search" ? "active" : "")} title="Search" onClick={() => setView("search")}>
        <Ic.search width="18" height="18"/>
      </button>
      <button className="ws-icon" title="Files">
        <Ic.file width="18" height="18"/>
      </button>
      <button className="ws-icon" title="Vault" onClick={openVault}>
        <Ic.archive width="18" height="18"/>
      </button>
      <div className="ws-spacer"/>
      <button className="ws-icon" title="Theme">
        <Ic.sun/>
      </button>
      <div className="ws-pill" style={{ width: 30, height: 30, background: "var(--bg-2)", fontSize: 11 }}>YO</div>
    </div>
  );
}

// Top bar
function TopBar({ view, channel }) {
  let crumb = null;
  if (view === "channel") {
    crumb = <><Ic.hash style={{ color: "var(--text-3)" }}/><b>{channel}</b></>;
  } else if (view === "personal") {
    crumb = <><Ic.sparkle style={{ color: "var(--ai)" }}/><b>Personal · Donna</b></>;
  } else if (view === "profile") {
    crumb = <><Ic.sparkle style={{ color: "var(--ai)" }}/><b>Agent profile</b></>;
  } else if (view === "search") {
    crumb = <><Ic.search/><b>Search & history</b></>;
  } else if (view === "workspace") {
    crumb = <><Ic.folder style={{ color: "var(--text-3)" }}/><b>Project overview</b></>;
  } else if (view === "empty") {
    crumb = <><Ic.hash style={{ color: "var(--text-3)" }}/><b>{channel}</b></>;
  }

  return (
    <header className="topbar">
      <div className="crumbs">
        <button className="btn-i" title="Back"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="15 18 9 12 15 6"/></svg></button>
        <button className="btn-i" title="Forward"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 18 15 12 9 6"/></svg></button>
        <span style={{ width: 10 }}/>
        {crumb}
      </div>
      <div className="search">
        <Ic.search style={{ color: "var(--text-3)" }}/>
        <input placeholder="Search messages, files, agents, or ask Donna…" />
        <kbd>⌘K</kbd>
      </div>
      <div className="actions">
        <button className="btn-i" title="Notifications"><Ic.bell/></button>
        <button className="btn-i" title="More"><Ic.more/></button>
      </div>
    </header>
  );
}

Object.assign(window, { Sidebar, WsRail, TopBar });
