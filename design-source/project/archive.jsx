// Archive dock — slim bar that launches the full Vault view
function Archive({ openVault }) {
  return (
    <div className="archive">
      <div className="dock-label"><Ic.archive/>Vault</div>
      <div className="dock-tags">
        <span className="dock-tag" onClick={openVault} style={{ cursor: "default" }}>Decisions <span className="count">42</span></span>
        <span className="dock-tag" onClick={openVault} style={{ cursor: "default" }}>Docs <span className="count">218</span></span>
        <span className="dock-tag" onClick={openVault} style={{ cursor: "default" }}>Links <span className="count">93</span></span>
        <span className="dock-tag" onClick={openVault} style={{ cursor: "default" }}>Files <span className="count">1.4k</span></span>
        <span className="dock-tag" onClick={openVault} style={{ cursor: "default" }}>Old channels <span className="count">17</span></span>
        <span className="dock-tag" onClick={openVault} style={{ color: "var(--ai)", borderColor: "var(--ai-glow)", background: "var(--ai-bg)", cursor: "default" }}>
          <Ic.sparkle/> Agent runs <span className="count">3.2k</span>
        </span>
      </div>
      <span style={{ fontSize: 11, color: "var(--ai)", fontFamily: "Geist Mono" }}>✦ 3 resurfaced for you</span>
      <button className="dock-toggle" onClick={openVault}>Open vault →</button>
    </div>
  );
}

// Legacy expanded view (no longer reachable but kept for compatibility)
function _LegacyArchiveExpanded({ expanded, setExpanded }) {
  if (!expanded) return null;

  const categories = [
    { id: "all", name: "Everything", count: "5,931" },
    { id: "dec", name: "Decisions", count: "42" },
    { id: "doc", name: "Documents", count: "218" },
    { id: "link", name: "Links", count: "93" },
    { id: "file", name: "Files", count: "1,409" },
    { id: "run", name: "Past agent runs", count: "3,201", ai: true },
    { id: "channels", name: "Archived channels", count: "17" },
    { id: "people", name: "Former members", count: "11" },
  ];

  const tiles = [
    { title: "Decision: lesion taxonomy v3", meta: "Marko · Apr 8", tags: ["#recist-protocol", "decision"] },
    { title: "Q1 clinical-ops review", meta: "Donna · Apr 2", tags: ["agent run", "personal"] },
    { title: "Vendor: Acme RWE data", meta: "Atlas · Mar 28", tags: ["#launch-press", "research"] },
    { title: "RECIST_v2_archive.pdf", meta: "Drive · Mar 14", tags: ["file"] },
    { title: "Hiring loop debrief", meta: "Rebeca · Mar 12", tags: ["doc"] },
    { title: "Press FAQ — Series B", meta: "Nova · Mar 9", tags: ["agent run", "#launch-press"] },
    { title: "Competitor scan: imaging AI", meta: "Atlas · Feb 28", tags: ["agent run", "research"] },
    { title: "Old #all-cube channel", meta: "Archived Feb 14", tags: ["channel"] },
    { title: "Brand voice principles", meta: "Nova · Feb 7", tags: ["doc", "#brand-site"] },
    { title: "Investor update Q4", meta: "Marius · Jan 18", tags: ["doc"] },
  ];

  return (
    <div className="archive expanded">
      <div className="vault-head">
        <Ic.archive style={{ color: "var(--text-2)" }}/>
        <div>
          <div className="title">Vault</div>
          <div className="sub">Searchable archive of decisions, documents, links, and past agent runs.</div>
        </div>
        <div className="spacer"/>
        <div className="search" style={{
          display: "flex", alignItems: "center", gap: 8,
          height: 30, padding: "0 12px",
          background: "var(--bg-2)", border: "1px solid var(--border)",
          borderRadius: 7, fontSize: 12, color: "var(--text-2)",
          width: 280
        }}>
          <Ic.search/>
          <span>Search vault…</span>
        </div>
        <button className="dock-toggle" onClick={() => setExpanded(false)}>Collapse ↓</button>
      </div>
      <div className="vault-body">
        <div className="vault-side">
          <div style={{ fontSize: 11, letterSpacing: 0.4, textTransform: "uppercase", color: "var(--text-3)", padding: "4px 8px 8px", fontWeight: 600 }}>By type</div>
          {categories.map((c, i) => (
            <div key={c.id} className={"vs " + (i === 0 ? "active" : "")} style={c.ai ? { color: "var(--ai)" } : {}}>
              {c.ai && <Ic.sparkle/>}
              {!c.ai && <Ic.folder/>}
              <span>{c.name}</span>
              <span className="count">{c.count}</span>
            </div>
          ))}
          <div style={{ fontSize: 11, letterSpacing: 0.4, textTransform: "uppercase", color: "var(--text-3)", padding: "16px 8px 8px", fontWeight: 600 }}>By project</div>
          {window.DONNA_DATA.projects.map(p => (
            <div key={p.id} className="vs">
              <span className="glyph" style={{ width: 14, height: 14, borderRadius: 4, background: p.color, color: "#fff", fontSize: 9, fontWeight: 700, display: "grid", placeItems: "center" }}>{p.glyph}</span>
              <span>{p.name}</span>
            </div>
          ))}
        </div>
        <div className="vault-grid">
          {tiles.map((t, i) => (
            <div key={i} className="vault-tile">
              <div className="ttitle">{t.title}</div>
              <div className="tmeta">{t.meta}</div>
              <div className="tags">
                {t.tags.map((tag, j) => (
                  <span key={j} className="tag" style={tag.includes("agent run") ? { color: "var(--ai)", background: "var(--ai-bg)" } : {}}>{tag}</span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { Archive });
