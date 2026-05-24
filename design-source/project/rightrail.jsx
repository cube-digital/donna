// Right rail — context-aware: progress, docs, context, agent memory
function RightRail({ view, channel, currentAgent }) {
  return (
    <aside className="rightrail">
      {(view === "channel" || view === "workspace") && (
        <>
          <ProgressSection/>
          <DocsSection/>
          <ContextSection/>
          <MemorySection/>
        </>
      )}
      {view === "personal" && (
        <>
          <DonnaToday/>
          <MemorySection isPersonal/>
        </>
      )}
      {view === "profile" && (
        <ProfileSidebarStats agentId={currentAgent}/>
      )}
      {view === "empty" && (
        <SuggestedSection/>
      )}
    </aside>
  );
}

function SectionHeader({ children, ai, action }) {
  return (
    <div className={"rr-h " + (ai ? "ai" : "")}>
      <span>{children}</span>
      <span className="spacer"/>
      {action || <button className="icon" style={{ color: "var(--text-3)" }}><Ic.caret/></button>}
    </div>
  );
}

function ProgressSection() {
  const tasks = [
    { id: "t1", status: "done", title: "Lock lesion taxonomy", who: { kind: "human", who: { initials: "RP", color: "#7aa6d9" } } },
    { id: "t2", status: "done", title: "Pull v3 protocol & rubric", who: { kind: "human", who: { initials: "RP", color: "#7aa6d9" } } },
    { id: "t3", status: "running", title: "Comparable trial protocol scan", who: { kind: "agent", agent: { name: "Mira", hue: 192 } } },
    { id: "t4", status: "running", title: "Parser fix — PR review", who: { kind: "human", who: { initials: "RP", color: "#7aa6d9" } } },
    { id: "t5", status: "todo", title: "Schedule clinician walkthrough", who: { kind: "agent", agent: { name: "Donna", hue: 282 } } },
  ];
  return (
    <div className="rr-section">
      <SectionHeader>Progress · #recist-protocol</SectionHeader>
      <div className="progress-tasks">
        {tasks.map(t => (
          <div key={t.id} className={"task " + t.status}>
            <div className="check">{t.status === "done" && <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round"><polyline points="5 12 10 17 19 7"/></svg>}</div>
            <div className="body">
              <div className="title">{t.title}</div>
              <div className="meta">
                <Av kind={t.who.kind} who={t.who.who} agent={t.who.agent} size="sm" />
                <span>{t.status === "running" ? "in progress" : t.status === "todo" ? "queued" : "done · 2h ago"}</span>
              </div>
            </div>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 10, display: "flex", gap: 8, fontSize: 11.5, color: "var(--text-3)" }}>
        <span>2 done · 2 running · 1 queued</span>
        <span style={{ marginLeft: "auto" }}>3 days left</span>
      </div>
    </div>
  );
}

function DocsSection() {
  const docs = [
    { name: "RECIST_v3_protocol.pdf", meta: "2.1 MB", icon: "pdf" },
    { name: "labeling_rubric.md", meta: "8 KB", icon: "md" },
    { name: "lesion_taxonomy_v0.4.md", meta: "12 KB", icon: "md" },
    { name: "PR #284 — column fix", meta: "github", icon: "link" },
    { name: "Clinician interview notes", meta: "drive", icon: "doc" },
  ];
  return (
    <div className="rr-section">
      <SectionHeader action={<button className="icon" style={{ color: "var(--text-3)" }}><Ic.plus/></button>}>
        Docs · 12
      </SectionHeader>
      <div className="doc-list">
        {docs.map((d, i) => (
          <div key={i} className="doc">
            <span className="icon"><Ic.doc/></span>
            <span className="name">{d.name}</span>
            <span className="meta">{d.meta}</span>
          </div>
        ))}
        <div className="doc" style={{ color: "var(--text-3)" }}>
          <span className="icon"><Ic.plus/></span>
          <span className="name">Drop or paste a doc</span>
        </div>
      </div>
    </div>
  );
}

function ContextSection() {
  return (
    <div className="rr-section">
      <SectionHeader>Context · Connectors</SectionHeader>
      <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 2 }}>
        <div className="connector">
          <div className="icon">G</div>
          <span className="name">GitHub · recist-pipeline</span>
          <span className="state live">live</span>
        </div>
        <div className="connector">
          <div className="icon">L</div>
          <span className="name">Linear · Clinical Ops</span>
          <span className="state live">live</span>
        </div>
        <div className="connector">
          <div className="icon">D</div>
          <span className="name">Drive · /recist</span>
          <span className="state live">live</span>
        </div>
        <div className="connector">
          <div className="icon">C</div>
          <span className="name">ClinicalTrials.gov</span>
          <span className="state">read-only</span>
        </div>
      </div>
    </div>
  );
}

function MemorySection({ isPersonal }) {
  const items = isPersonal ? [
    { key: "schedule", val: "Berlin trip Apr 22–25, refundable hotels held" },
    { key: "tone", val: "Concise, no bullet bloat. Prefers raw figures." },
    { key: "calendar", val: "Heads-down 9–11am M/W/F, no meetings" },
  ] : [
    { key: "RECIST v3", val: "Lesion measurement protocol, 42 pages, baseline + 3 follow-ups" },
    { key: "team avail", val: "Marko PTO Apr 18–22, Rebeca clinician calls Tue/Thu" },
    { key: "open Qs", val: "Scan modality mismatch · Missing baseline dates" },
    { key: "history", val: "Bug #261 (March) — also column threshold" },
  ];
  return (
    <div className="rr-section">
      <SectionHeader ai action={<button className="icon" style={{ color: "var(--ai-dim)" }}><Ic.plus/></button>}>
        <Ic.brain style={{ verticalAlign: -2, marginRight: 4 }}/>
        Agent memory {!isPersonal && "· this channel"}
      </SectionHeader>
      <div className="mem-list" style={{ marginTop: 6 }}>
        {items.map((m, i) => (
          <div key={i} className="mem-item">
            <span className="key">{m.key}</span>
            <span className="val">{m.val}</span>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 8, fontSize: 11.5, color: "var(--text-3)", display: "flex", gap: 8 }}>
        <span>{items.length} items</span>
        <span style={{ marginLeft: "auto", color: "var(--ai-dim)" }}>Inspect all →</span>
      </div>
    </div>
  );
}

function DonnaToday() {
  return (
    <div className="rr-section">
      <SectionHeader ai>Donna · Today</SectionHeader>
      <div className="rr-card ai" style={{ marginTop: 6 }}>
        <div style={{ fontSize: 12, color: "var(--text-1)", lineHeight: 1.5 }}>
          <b style={{ color: "var(--text-0)" }}>3 things need you</b>
          <ul style={{ margin: "8px 0 0", padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
            <li style={{ display: "flex", gap: 8 }}>
              <span style={{ width: 18, height: 18, borderRadius: 4, background: "var(--ai)", color: "var(--bg-0)", display: "grid", placeItems: "center", fontSize: 11, fontWeight: 700, flexShrink: 0 }}>1</span>
              <span>Reply to Marius on protocol sign-off <span style={{ color: "var(--text-3)" }}>· 2pm</span></span>
            </li>
            <li style={{ display: "flex", gap: 8 }}>
              <span style={{ width: 18, height: 18, borderRadius: 4, background: "var(--ai)", color: "var(--bg-0)", display: "grid", placeItems: "center", fontSize: 11, fontWeight: 700, flexShrink: 0 }}>2</span>
              <span>Pick a Berlin hotel from Andreea</span>
            </li>
            <li style={{ display: "flex", gap: 8 }}>
              <span style={{ width: 18, height: 18, borderRadius: 4, background: "var(--ai)", color: "var(--bg-0)", display: "grid", placeItems: "center", fontSize: 11, fontWeight: 700, flexShrink: 0 }}>3</span>
              <span>Approve all-hands agenda <span style={{ color: "var(--text-3)" }}>· draft ready</span></span>
            </li>
          </ul>
        </div>
      </div>
      <div className="rr-card" style={{ marginTop: 8 }}>
        <div style={{ fontSize: 11, color: "var(--text-3)", letterSpacing: 0.4, textTransform: "uppercase", marginBottom: 6 }}>Calendar</div>
        <div style={{ fontSize: 12.5, color: "var(--text-1)", display: "flex", flexDirection: "column", gap: 4 }}>
          <div>11:00 · Recist sync <span style={{ color: "var(--text-3)" }}>· 30m</span></div>
          <div>14:00 · Marius 1:1 <span style={{ color: "var(--text-3)" }}>· 30m</span></div>
          <div>16:30 · Andreea — Berlin <span style={{ color: "var(--text-3)" }}>· 15m</span></div>
        </div>
      </div>
    </div>
  );
}

function SuggestedSection() {
  return (
    <div className="rr-section">
      <SectionHeader ai>Suggested for this channel</SectionHeader>
      <div className="rr-card ai" style={{ marginTop: 6 }}>
        <div style={{ fontSize: 12.5, color: "var(--text-0)", marginBottom: 6 }}>Donna can set this up</div>
        <div style={{ fontSize: 12, color: "var(--text-2)", lineHeight: 1.5 }}>
          Drop the model card and Donna will: pull related channels, suggest reviewers, draft an intro post, and create a 3-task checklist.
        </div>
        <button style={{ marginTop: 10, padding: "5px 10px", borderRadius: 6, background: "var(--ai)", color: "var(--bg-0)", fontSize: 12, fontWeight: 500 }}>
          Run setup
        </button>
      </div>
    </div>
  );
}

function ProfileSidebarStats({ agentId }) {
  const a = window.lookup(agentId);
  return (
    <div className="rr-section">
      <SectionHeader ai>Recent activity</SectionHeader>
      <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 6 }}>
        <div className="rr-card">
          <div style={{ fontSize: 11.5, color: "var(--text-3)", fontFamily: "Geist Mono", marginBottom: 2 }}>2h ago · #recist-protocol</div>
          <div style={{ fontSize: 12.5, color: "var(--text-0)" }}>Drafted 3-week plan with risks flagged</div>
        </div>
        <div className="rr-card">
          <div style={{ fontSize: 11.5, color: "var(--text-3)", fontFamily: "Geist Mono", marginBottom: 2 }}>Yesterday · Personal</div>
          <div style={{ fontSize: 12.5, color: "var(--text-0)" }}>Berlin trip — held 2 hotels</div>
        </div>
        <div className="rr-card">
          <div style={{ fontSize: 11.5, color: "var(--text-3)", fontFamily: "Geist Mono", marginBottom: 2 }}>Mon · #launch-plan</div>
          <div style={{ fontSize: 12.5, color: "var(--text-0)" }}>Press list refresh — 22 contacts updated</div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { RightRail });
