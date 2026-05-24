// Search & history view
function SearchView() {
  const d = window.DONNA_DATA;
  const [q, setQ] = React.useState("recist parser");
  const [filter, setFilter] = React.useState("all");

  return (
    <div className="search-view">
      <h1>Search & history</h1>
      <div className="subtitle">Across channels, DMs, agent runs, and the vault.</div>
      <div className="search-input">
        <Ic.search style={{ color: "var(--text-3)" }}/>
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search anything…"/>
        <kbd style={{ fontFamily: "Geist Mono", fontSize: 11, color: "var(--text-3)", padding: "2px 6px", borderRadius: 4, background: "var(--bg-1)", border: "1px solid var(--border)" }}>⌘K</kbd>
        <button className="clear">Clear</button>
      </div>
      <div className="search-filters">
        {["all", "messages", "agent runs", "files", "channels", "people"].map(f => (
          <button key={f} className={"chip " + (filter === f ? "active" : "")} onClick={() => setFilter(f)}>{f}</button>
        ))}
        <span style={{ marginLeft: "auto", color: "var(--text-3)", fontSize: 11.5, alignSelf: "center" }}>342 results · 0.12s</span>
      </div>

      <div className="search-section">
        <h3>✦ Best match — synthesized by Donna</h3>
        <div className="search-result" style={{ borderColor: "var(--ai-glow)", background: "var(--ai-bg)" }}>
          <Av kind="agent" agent={window.lookup("donna")} pulsing/>
          <div style={{ flex: 1 }}>
            <div className="head">
              <span className="who">Donna · synthesis</span>
              <span className="when">just now</span>
            </div>
            <div className="preview">
              The <mark>parser</mark> fix for multi-column tables (Kai, Mon) addresses a recurring bug — also hit in March (#261). The fix changes <mark>column threshold</mark> from 60px to data-driven detection. PR <mark>#284</mark> is up, awaiting Rebeca's review. The bug surfaces in <mark>RECIST</mark> protocol PDFs with narrow side-bar tables. 4 related conversations across 3 channels.
            </div>
            <div style={{ marginTop: 8, display: "flex", gap: 6 }}>
              <button style={{ fontSize: 11.5, padding: "3px 8px", borderRadius: 5, background: "var(--ai)", color: "var(--bg-0)", fontWeight: 500 }}>Continue this conversation</button>
              <button style={{ fontSize: 11.5, padding: "3px 8px", borderRadius: 5, color: "var(--text-1)" }}>See 4 sources</button>
            </div>
          </div>
        </div>
      </div>

      <div className="search-section">
        <h3>Recent · this week</h3>
        {d.searchResults.map((r, i) => {
          const who = window.lookup(r.who);
          const isAgent = who.kind === "agent";
          return (
            <div key={i} className="search-result">
              <Av kind={who.kind} agent={who} who={who} />
              <div style={{ flex: 1 }}>
                <div className="head">
                  <span className="who">{who.name}{isAgent && <span style={{ fontSize: 9.5, fontWeight: 600, marginLeft: 8, color: "var(--ai)", padding: "1px 5px", borderRadius: 3, background: "var(--ai-bg)", border: "1px solid var(--ai-glow)", letterSpacing: 0.5, textTransform: "uppercase" }}>Agent</span>}</span>
                  <span className="where">{r.where}</span>
                  <span className="when">{r.when}</span>
                </div>
                <div className="preview">
                  {highlight(r.text, q)}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div className="search-section">
        <h3>From the vault</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 8 }}>
          {[
            { title: "Decision: standardize lesion taxonomy v3", who: "Marko", when: "Apr 8" },
            { title: "RECIST v2 archived protocol notes", who: "Vault", when: "Mar 14" },
            { title: "Bug #261 — earlier column-detection issue", who: "Kai", when: "Mar 4" },
          ].map((t, i) => (
            <div key={i} style={{
              padding: "12px 14px",
              background: "var(--bg-1)",
              border: "1px solid var(--border)",
              borderRadius: 9,
            }}>
              <div style={{ fontSize: 12.5, color: "var(--text-0)", fontWeight: 500 }}>{t.title}</div>
              <div style={{ fontSize: 11, color: "var(--text-3)", marginTop: 4, fontFamily: "Geist Mono" }}>{t.who} · {t.when}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function highlight(text, q) {
  if (!q) return text;
  const words = q.split(/\s+/).filter(Boolean);
  if (!words.length) return text;
  const re = new RegExp("(" + words.map(w => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|") + ")", "gi");
  const parts = text.split(re);
  return parts.map((p, i) => re.test(p) ? <mark key={i}>{p}</mark> : <span key={i}>{p}</span>);
}

Object.assign(window, { SearchView });
