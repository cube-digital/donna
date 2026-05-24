// Agent profile view
function ProfileView({ agentId }) {
  const a = window.lookup(agentId);
  return (
    <div className="profile">
      <aside className="pcol">
        <div className="phero">
          <Av kind="agent" agent={a} size="xl" pulsing/>
          <span className="prole">{a.role}</span>
          <div className="pname">{a.name}</div>
          <div className="pblurb">{a.blurb}</div>
        </div>
        <div className="pactions">
          <button className="btn primary">Start chat</button>
          <button className="btn">Invite to channel</button>
          <button className="btn" style={{ padding: "6px 10px" }}><Ic.more/></button>
        </div>
        <div className="stats">
          <div className="stat"><div className="v">{a.runs.toLocaleString()}</div><div className="l">Total runs</div></div>
          <div className="stat"><div className="v">{a.memory}</div><div className="l">Memory items</div></div>
          <div className="stat"><div className="v">96%</div><div className="l">Approved</div></div>
          <div className="stat"><div className="v">12s</div><div className="l">Avg latency</div></div>
        </div>
        <div className="block" style={{ marginTop: 24 }}>
          <h2 style={{ fontSize: 11, letterSpacing: 0.4, textTransform: "uppercase", color: "var(--text-3)", margin: "0 0 8px", fontWeight: 600 }}>Owner</h2>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Av kind="human" who={window.lookup("marius")} size="sm"/>
            <span style={{ fontSize: 13, color: "var(--text-1)" }}>Marius M.</span>
            <span style={{ fontSize: 11, color: "var(--text-3)", marginLeft: "auto" }}>Created Jan 14</span>
          </div>
        </div>
      </aside>

      <div className="pside">
        <div className="block">
          <h2>What {a.name} is good at</h2>
          <div className="chips">
            {a.skills.map(s => <span key={s} className="c">{s}</span>)}
          </div>
        </div>

        <div className="block">
          <h2>Tools & connectors</h2>
          <div className="chips">
            {a.tools.map(t => <span key={t} className="c" style={{ fontFamily: "Geist Mono", fontSize: 11.5 }}>{t}</span>)}
          </div>
        </div>

        <div className="block">
          <h2>How {a.name} thinks · system prompt</h2>
          <div style={{
            padding: "14px 16px",
            background: "var(--bg-1)",
            border: "1px solid var(--border)",
            borderRadius: 9,
            fontFamily: "Geist Mono",
            fontSize: 12,
            color: "var(--text-1)",
            lineHeight: 1.6,
            whiteSpace: "pre-wrap"
          }}>
{`You are ${a.name}, ${a.role.toLowerCase()} at Cube.
- Default to brevity. Surface trade-offs, not options.
- Cite sources when claims could be checked.
- Flag risks early; one-line summaries first.
- Memory: read before answering. Update after.
- Defer to humans on decisions; queue follow-ups.`}
          </div>
          <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
            <button style={{ fontSize: 12, padding: "5px 10px", borderRadius: 6, background: "var(--bg-2)", border: "1px solid var(--border)", color: "var(--text-0)" }}>Edit prompt</button>
            <button style={{ fontSize: 12, padding: "5px 10px", borderRadius: 6, color: "var(--text-2)" }}>Version history (4)</button>
          </div>
        </div>

        <div className="block">
          <h2>Channels & memberships</h2>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {["#recist-protocol", "#recist-data", "#launch-plan", "Personal · marius.milu", "Personal · alice.t"].map(ch => (
              <div key={ch} style={{
                display: "flex", alignItems: "center", gap: 8,
                padding: "8px 10px",
                background: "var(--bg-1)",
                border: "1px solid var(--border)",
                borderRadius: 7,
                fontSize: 12.5, color: "var(--text-1)"
              }}>
                {ch.startsWith("#") ? <Ic.hash/> : <Ic.sparkle style={{ color: "var(--ai)" }}/>}
                <span>{ch}</span>
                <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--text-3)", fontFamily: "Geist Mono" }}>
                  {Math.floor(Math.random() * 80 + 10)} runs
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="block">
          <h2>Permissions</h2>
          <div style={{
            padding: "12px 14px",
            background: "var(--bg-1)",
            border: "1px solid var(--border)",
            borderRadius: 9,
            display: "flex", flexDirection: "column", gap: 6
          }}>
            {[
              ["Read channel messages", true],
              ["Post replies & run cards", true],
              ["Read drive & GitHub", true],
              ["Write to drive", false],
              ["Spend money / make purchases", false],
              ["Email external contacts", false],
            ].map(([k, on]) => (
              <div key={k} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: 12.5 }}>
                <span style={{ color: "var(--text-1)" }}>{k}</span>
                <span style={{
                  width: 28, height: 16, borderRadius: 10,
                  background: on ? "var(--ai)" : "var(--bg-3)",
                  position: "relative",
                  flexShrink: 0
                }}>
                  <span style={{
                    position: "absolute", top: 2, left: on ? 14 : 2,
                    width: 12, height: 12, borderRadius: "50%", background: "#fff"
                  }}/>
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { ProfileView });
