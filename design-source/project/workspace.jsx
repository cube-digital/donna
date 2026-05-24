// Project workspace overview — channels + agents + docs grouped
function WorkspaceView({ channel }) {
  const projectId = (channel || "").split(":")[0] || "recist";
  const project = window.DONNA_DATA.projects.find(p => p.id === projectId) || window.DONNA_DATA.projects[0];

  return (
    <div className="wsview">
      <h1>
        <span className="wsglyph" style={{ background: project.color, color: "#fff" }}>{project.glyph}</span>
        <span>{project.name}</span>
        <span style={{ fontSize: 12, color: "var(--text-3)", letterSpacing: 0, fontWeight: 400, marginLeft: 8 }}>
          {project.members} people · {project.agents.length} AI teammates · 3 channels
        </span>
      </h1>
      <div className="subtitle">
        Standardizing how lesion measurements are extracted from radiology PDFs into the labeling pipeline.
      </div>

      <div className="grid">
        <div className="col">
          <h2>Channels</h2>
          {project.channels.map(c => (
            <div key={c} className="channel-card">
              <Ic.hash style={{ color: "var(--text-3)" }}/>
              <div>
                <div className="name">{c}</div>
                <div className="desc">
                  {c === "recist-protocol" && "Working channel — protocol, taxonomy, agent runs"}
                  {c === "recist-data" && "Pipeline, parsers, labeled samples"}
                  {c === "recist-clinicians" && "Clinician walkthroughs, sign-offs"}
                  {c === "launch-plan" && "Press, comms, milestones"}
                  {c === "launch-press" && "Outreach, embargo, FAQs"}
                  {c === "launch-metrics" && "Funnel, activation, retention"}
                  {c === "brand-site" && "Site, copy, components"}
                  {c === "brand-copy" && "Voice, taglines, microcopy"}
                </div>
              </div>
              <div className="activity">{Math.floor(Math.random() * 50 + 5)} msgs today</div>
            </div>
          ))}
          <button style={{
            width: "100%", padding: "12px",
            background: "transparent", border: "1px dashed var(--border-strong)",
            borderRadius: 10, color: "var(--text-2)", fontSize: 12.5,
            display: "flex", alignItems: "center", justifyContent: "center", gap: 8
          }}>
            <Ic.plus/> New channel
          </button>

          <h2 style={{ marginTop: 28 }}>Pinned docs</h2>
          <div style={{ background: "var(--bg-1)", border: "1px solid var(--border)", borderRadius: 10 }}>
            {[
              { name: "RECIST_v3_protocol.pdf", who: "Rebeca", size: "2.1 MB" },
              { name: "lesion_taxonomy_v0.4.md", who: "Marko", size: "12 KB" },
              { name: "labeling_rubric.md", who: "Rebeca", size: "8 KB" },
              { name: "Clinician interview notes", who: "Alice", size: "drive" },
              { name: "PR #284 — column detection fix", who: "Kai", size: "github" },
            ].map((d, i) => (
              <div key={i} className="docrow">
                <Ic.doc style={{ color: "var(--text-3)" }}/>
                <span className="name">{d.name}</span>
                <span className="who">{d.who}</span>
                <span style={{ fontSize: 11, color: "var(--text-3)", fontFamily: "Geist Mono", minWidth: 60, textAlign: "right" }}>{d.size}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="col">
          <h2>AI teammates · this project</h2>
          {project.agents.map(id => {
            const a = window.lookup(id);
            return (
              <div key={id} className="agent-card">
                <Av kind="agent" agent={a}/>
                <div style={{ flex: 1 }}>
                  <div className="name">{a.name}</div>
                  <div className="role">{a.role}</div>
                </div>
                <span style={{ fontSize: 11, color: "var(--ai)", fontFamily: "Geist Mono", padding: "2px 6px", background: "var(--ai-bg)", borderRadius: 4, border: "1px solid var(--ai-glow)" }}>
                  {Math.floor(Math.random() * 200 + 50)} runs
                </span>
              </div>
            );
          })}
          <button style={{
            width: "100%", padding: "10px",
            background: "var(--ai-bg)", border: "1px dashed var(--ai-glow)",
            borderRadius: 9, color: "var(--ai)", fontSize: 12.5,
            display: "flex", alignItems: "center", justifyContent: "center", gap: 6
          }}>
            <Ic.sparkle/> Add an AI teammate
          </button>

          <h2 style={{ marginTop: 28 }}>People</h2>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {window.DONNA_DATA.humans.filter(h => h.id !== "you").map(h => (
              <div key={h.id} style={{
                display: "flex", alignItems: "center", gap: 10,
                padding: "8px 10px",
                background: "var(--bg-1)", border: "1px solid var(--border)",
                borderRadius: 7
              }}>
                <Av kind="human" who={h} size="sm"/>
                <span style={{ fontSize: 12.5, color: "var(--text-0)" }}>{h.name}</span>
                <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--text-3)" }}>online</span>
              </div>
            ))}
          </div>

          <h2 style={{ marginTop: 28 }}>This week</h2>
          <div style={{
            padding: "14px 16px",
            background: "var(--ai-bg)", border: "1px solid var(--ai-glow)", borderRadius: 10
          }}>
            <div style={{ fontSize: 11, letterSpacing: 0.4, textTransform: "uppercase", color: "var(--ai)", fontWeight: 600, marginBottom: 6 }}>
              ✦ Donna's recap
            </div>
            <div style={{ fontSize: 12.5, color: "var(--text-1)", lineHeight: 1.55 }}>
              Taxonomy v3 locked Mon. Parser fix in review (Kai → Rebeca). Mira's literature scan still running — preliminary signal: 4 highly comparable trials. Risk: clinician walkthrough not scheduled yet.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// Empty channel onboarding
function EmptyChannelView({ channel }) {
  const [selected, setSelected] = React.useState(["mira", "kai"]);
  const toggle = (id) => {
    setSelected(s => s.includes(id) ? s.filter(x => x !== id) : [...s, id]);
  };
  return (
    <div className="empty" style={{ overflowY: "auto", height: "100%" }}>
      <div className="hero">
        <div className="glyph"><Ic.hash width="22" height="22"/></div>
        <div>
          <h1>#{channel || "recist-models"}</h1>
          <div className="sub">
            You created this channel today. Set it up — invite people, drop a brief, and pick AI teammates. Donna can do most of this for you.
          </div>
        </div>
      </div>

      <div className="step-section">
        <h3>Quick start</h3>
        <div className="step ai">
          <span className="num">✦</span>
          <div className="body">
            <div className="title">Have Donna set this up</div>
            <div className="desc">Drop a model card or one-liner brief. Donna will write the channel description, invite the right people based on past projects, and create a 3-task plan.</div>
          </div>
          <button className="cta">Run setup</button>
        </div>
        <div className="step">
          <span className="num">1</span>
          <div className="body">
            <div className="title">Write a topic</div>
            <div className="desc">One line — what is this channel for?</div>
          </div>
          <button className="cta">Add topic</button>
        </div>
        <div className="step">
          <span className="num">2</span>
          <div className="body">
            <div className="title">Drop a brief or doc</div>
            <div className="desc">PDF, link, or paste. Agents will use it as starting context.</div>
          </div>
          <button className="cta">Add doc</button>
        </div>
        <div className="step">
          <span className="num">3</span>
          <div className="body">
            <div className="title">Invite people</div>
            <div className="desc">Pick from the workspace — Donna suggests based on the brief.</div>
          </div>
          <button className="cta">Invite</button>
        </div>
      </div>

      <div className="step-section">
        <h3>Pick AI teammates · suggested for this channel</h3>
        <div className="agent-grid">
          {window.DONNA_DATA.agents.map(a => (
            <div
              key={a.id}
              className={"agent-pick " + (selected.includes(a.id) ? "selected" : "")}
              onClick={() => toggle(a.id)}
            >
              <Av kind="agent" agent={a}/>
              <div>
                <div className="name">{a.name}</div>
                <div className="role">{a.role}</div>
              </div>
              <span className="pick">
                {selected.includes(a.id) && <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3.5" strokeLinecap="round" style={{ margin: 2 }}><polyline points="5 12 10 17 19 7"/></svg>}
              </span>
            </div>
          ))}
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 14, alignItems: "center" }}>
          <span style={{ fontSize: 12, color: "var(--text-2)" }}>{selected.length} selected</span>
          <span style={{ flex: 1 }}/>
          <button style={{ fontSize: 12.5, padding: "7px 14px", borderRadius: 7, background: "var(--text-0)", color: "var(--bg-0)", fontWeight: 500 }}>
            Add teammates & continue
          </button>
        </div>
      </div>

      <div className="step-section">
        <h3>Or start with a template</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 8 }}>
          {[
            { title: "Research sprint", desc: "Mira leads literature + competitive scan", icon: "📚" },
            { title: "Code review room", desc: "Kai watches PRs, drafts reviews", icon: "{ }" },
            { title: "Launch war room", desc: "Donna + Atlas + Nova coordinate", icon: "◆" },
            { title: "Blank channel", desc: "No agents, just people", icon: "·" },
          ].map((t, i) => (
            <div key={i} style={{
              padding: "12px 14px",
              background: "var(--bg-1)",
              border: "1px solid var(--border)",
              borderRadius: 9,
            }}>
              <div style={{ fontSize: 16, marginBottom: 6, fontFamily: "Geist Mono", color: "var(--ai)" }}>{t.icon}</div>
              <div style={{ fontSize: 13, color: "var(--text-0)", fontWeight: 500 }}>{t.title}</div>
              <div style={{ fontSize: 11.5, color: "var(--text-3)", marginTop: 2 }}>{t.desc}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { WorkspaceView, EmptyChannelView });
