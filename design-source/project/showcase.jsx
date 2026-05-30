// ════════════════════════════════════════════════════════════════
//  GOOFY UI — showcase gallery
//  Renders every component group with a theme + wiggle toggle.
// ════════════════════════════════════════════════════════════════
const { useState } = React;

function Section({ id, title, hint, children }) {
  return (
    <section className="sc-section" id={id}>
      <div className="sc-shead">
        <h2 className="gx-display">{title}</h2>
        {hint && <span className="gx-hand">{hint}</span>}
      </div>
      <div className="sc-body">{children}</div>
    </section>
  );
}
function Cell({ label, children, wide = false }) {
  return (
    <div className={`sc-cell${wide ? " wide" : ""}`}>
      <div className="sc-cell-demo">{children}</div>
      {label && <div className="sc-cell-label">{label}</div>}
    </div>
  );
}

/* ── Color schemes section ───────────────────────────────────── */
const SWATCHES = [
  ["--ink", "ink"], ["--bg-0", "bg-0"], ["--bg-1", "bg-1"], ["--bg-2", "bg-2"],
  ["--bg-3", "bg-3"], ["--bg-4", "bg-4"], ["--text-0", "text-0"], ["--text-2", "text-2"],
];
const ACCENTS = [
  ["--ai", "ai grape"], ["--pop-blue", "blue"], ["--pop-coral", "coral"],
  ["--pop-sun", "sun"], ["--pop-mint", "mint"], ["--ok", "ok"], ["--warn", "warn"], ["--danger", "danger"],
];
function Swatch({ token, name }) {
  return (
    <div className="sc-swatch">
      <div className="chip" style={{ background: `var(${token})` }} />
      <div className="meta"><b>{name}</b><code className="gx-mono">{token}</code></div>
    </div>
  );
}

function Showcase() {
  const [dark, setDark] = useState(false);
  const [wiggly, setWiggly] = useState(false);
  const [tab, setTab] = useState("Messages");
  const [chips, setChips] = useState({ All: true, Docs: false, Runs: false });
  const [checks, setChecks] = useState({ a: true, b: false });
  const [sw, setSw] = useState(true);
  const [active, setActive] = useState("recist-protocol");

  return (
    <div className={`gx${dark ? " dark" : ""}${wiggly ? " wiggly" : ""}`} style={{ minHeight: "100vh" }}>
      <div className="sc-wrap">

        {/* Masthead */}
        <header className="sc-masthead">
          <div className="sc-brand">
            <div className="sc-logo gx-anim-bob">🦔</div>
            <div>
              <h1 className="gx-display">Goofy UI</h1>
              <p className="gx-hand">a bouncy sticker-book component kit</p>
            </div>
          </div>
          <div className="sc-controls">
            <GTabs tabs={["Cream", "Midnight"]} value={dark ? "Midnight" : "Cream"} onChange={(t) => setDark(t === "Midnight")} />
            <label className="sc-toggle">
              <GSwitch on={wiggly} onChange={setWiggly} />
              <span>wiggle</span>
            </label>
          </div>
        </header>

        {/* Color schemes */}
        <Section title="Color schemes" hint="cream paper ✦ midnight slate" id="colors">
          <div className="sc-scheme">
            <div className="sc-scheme-h gx-mono">NEUTRALS · {dark ? "midnight" : "cream"}</div>
            <div className="sc-swatches">{SWATCHES.map(([t, n]) => <Swatch key={t} token={t} name={n} />)}</div>
          </div>
          <div className="sc-scheme">
            <div className="sc-scheme-h gx-mono">ACCENTS · crayon box + grape AI</div>
            <div className="sc-swatches">{ACCENTS.map(([t, n]) => <Swatch key={t} token={t} name={n} />)}</div>
          </div>
        </Section>

        {/* Type */}
        <Section title="Type" hint="Fredoka · Caveat · Geist" id="type">
          <Cell label="Fredoka — display" wide>
            <div className="gx-display" style={{ fontSize: 30 }}>The quick brown hedgehog</div>
          </Cell>
          <Cell label="Caveat — hand-lettered labels" wide>
            <div className="gx-hand" style={{ fontSize: 24 }}>resurfaced decisions ✎</div>
          </Cell>
          <Cell label="Geist — body" wide>
            <div style={{ fontSize: 14, color: "var(--text-1)", maxWidth: 460 }}>
              Body copy rides on cream paper with a faint dotted texture. Ink borders stay chunky, shadows stay hard.
            </div>
          </Cell>
          <Cell label="Geist Mono — meta">
            <code className="gx-mono" style={{ fontSize: 13, color: "var(--text-2)" }}>2.4s · 1,208 tok</code>
          </Cell>
        </Section>

        {/* Buttons */}
        <Section title="Buttons" hint="press down + tilt on hover" id="buttons">
          <Cell label="default"><GButton>Button</GButton></Cell>
          <Cell label="coral / primary"><GButton variant="coral" icon="plus">New channel</GButton></Cell>
          <Cell label="ai grape"><GButton variant="ai" icon="sparkle">Ask Donna</GButton></Cell>
          <Cell label="sun"><GButton variant="sun">Sunny</GButton></Cell>
          <Cell label="mint"><GButton variant="mint" icon="check">Done</GButton></Cell>
          <Cell label="blue"><GButton variant="blue">Open</GButton></Cell>
          <Cell label="ghost"><GButton variant="ghost">Ghost</GButton></Cell>
          <Cell label="disabled"><GButton disabled>Disabled</GButton></Cell>
          <Cell label="sizes">
            <div className="sc-row">
              <GButton size="sm" variant="coral">Small</GButton>
              <GButton variant="coral">Medium</GButton>
              <GButton size="lg" variant="coral">Large</GButton>
            </div>
          </Cell>
          <Cell label="icon buttons">
            <div className="sc-row">
              <GIconButton icon="smile" />
              <GIconButton icon="more" />
              <GIconButton icon="plus" outlined />
              <GIconButton icon="sparkle" outlined />
            </div>
          </Cell>
        </Section>

        {/* Inputs */}
        <Section title="Inputs" hint="capsules & note cards" id="inputs">
          <Cell label="search capsule" wide><GInput placeholder="Search everything…" kbd="⌘K" /></Cell>
          <Cell label="text capsule" wide><GInput icon="edit" placeholder="Name this channel…" /></Cell>
          <Cell label="note-card textarea" wide>
            <GField placeholder="Message #recist-protocol…">
              <div className="sc-row" style={{ marginTop: 8 }}>
                <GTag variant="mint"><GlyphSlot name="sparkle" size={11} /> @Donna</GTag>
                <span style={{ flex: 1 }} />
                <GIconButton icon="send" outlined />
              </div>
            </GField>
          </Cell>
          <Cell label="ai ask field" wide>
            <GField ai placeholder="Ask the vault anything…" rows={2} />
          </Cell>
        </Section>

        {/* Chips & badges */}
        <Section title="Chips · tags · badges" id="chips">
          <Cell label="filter chips" wide>
            <div className="sc-row">
              {Object.keys(chips).map(k => (
                <GChip key={k} active={chips[k]} onClick={() => setChips(c => ({ ...c, [k]: !c[k] }))}>{k}</GChip>
              ))}
            </div>
          </Cell>
          <Cell label="removable chip"><GChip active onRemove={() => {}}>oncology</GChip></Cell>
          <Cell label="tags">
            <div className="sc-row">
              <GTag>label</GTag>
              <GTag variant="mint">live</GTag>
              <GTag variant="sun" count={12}>threads</GTag>
            </div>
          </Cell>
          <Cell label="count badge"><span className="sc-row" style={{ alignItems: "center", gap: 10 }}><GBadge>3</GBadge><GBadge>24</GBadge></span></Cell>
          <Cell label="mention badge"><GBadge mention>@5</GBadge></Cell>
          <Cell label="role chip"><div className="sc-row"><GRoleChip>AI</GRoleChip><GRoleChip>AGENT</GRoleChip></div></Cell>
        </Section>

        {/* Avatars */}
        <Section title="Avatars" hint="every face gets an ink outline" id="avatars">
          <Cell label="sizes">
            <div className="sc-row" style={{ alignItems: "center" }}>
              <GAvatar name="JD" color="var(--pop-blue)" size="sm" />
              <GAvatar name="JD" color="var(--pop-coral)" />
              <GAvatar name="JD" color="var(--pop-mint)" size="lg" />
              <GAvatar name="JD" color="var(--pop-sun)" size="xl" />
            </div>
          </Cell>
          <Cell label="agent + pulsing">
            <div className="sc-row" style={{ alignItems: "center" }}>
              <GAvatar name="DO" agent />
              <GAvatar name="DO" agent size="lg" pulsing />
            </div>
          </Cell>
          <Cell label="stacked group">
            <GAvatarStack people={[
              { name: "AB", color: "var(--pop-coral)" },
              { name: "CD", color: "var(--pop-blue)" },
              { name: "EF", color: "var(--pop-mint)" },
              { name: "DO", agent: true },
            ]} />
          </Cell>
        </Section>

        {/* Cards */}
        <Section title="Cards" id="cards">
          <Cell label="basic" wide>
            <GCard hover title="Weekly digest" sub="Donna summarised 14 threads and flagged 2 decisions for review." />
          </Cell>
          <Cell label="ai card" wide>
            <GCard ai title="Memory updated" sub="Remembered that the RECIST cutoff is 20% for this trial.">
              <div className="sc-row" style={{ marginTop: 10 }}>
                <GTag variant="mint"><GlyphSlot name="brain" size={11} /> memory</GTag>
              </div>
            </GCard>
          </Cell>
          <Cell label="stats" wide>
            <div className="sc-row">
              <GStat value="248" label="runs" />
              <GStat value="2.4s" label="median" />
              <GStat value="98%" label="approved" />
            </div>
          </Cell>
        </Section>

        {/* Lists */}
        <Section title="Lists" hint="sidebar items snap into stickers" id="lists">
          <Cell label="channel list" wide>
            <div style={{ maxWidth: 260 }}>
              <GList>
                <GListItem hash="#" active={active === "recist-protocol"} onClick={() => setActive("recist-protocol")}>recist-protocol</GListItem>
                <GListItem hash="#" badge={<GBadge mention>3</GBadge>} active={active === "trial-ops"} onClick={() => setActive("trial-ops")}>trial-ops</GListItem>
                <GListItem dot="ai" active={active === "donna"} onClick={() => setActive("donna")}>Donna</GListItem>
                <GListItem dot="online" active={active === "jordan"} onClick={() => setActive("jordan")}>Jordan Patel</GListItem>
              </GList>
            </div>
          </Cell>
          <Cell label="document list" wide>
            <div style={{ maxWidth: 280 }}>
              <GDoc name="Protocol v3.2.pdf" meta="2.4mb" />
              <GDoc icon="link" name="Trial registry entry" meta="ext" />
              <GDoc name="Eligibility matrix" meta="edited 2d" />
            </div>
          </Cell>
        </Section>

        {/* Toggles */}
        <Section title="Toggles" hint="checks, spinners & switches" id="toggles">
          <Cell label="checkbox">
            <div className="sc-row" style={{ alignItems: "center", gap: 14 }}>
              <GCheck checked={checks.a} onChange={(v) => setChecks(c => ({ ...c, a: v }))} />
              <GCheck checked={checks.b} onChange={(v) => setChecks(c => ({ ...c, b: v }))} />
            </div>
          </Cell>
          <Cell label="task states">
            <div className="sc-row" style={{ alignItems: "center", gap: 14 }}>
              <GTaskCheck state="todo" />
              <GTaskCheck state="running" />
              <GTaskCheck state="done" />
            </div>
          </Cell>
          <Cell label="switch">
            <GSwitch on={sw} onChange={setSw} />
          </Cell>
        </Section>

        {/* Popovers / menus */}
        <Section title="Popovers · menus · toolbars" id="popovers">
          <Cell label="dropdown menu">
            <GPopover>
              <GMenuItem icon="reply" kbd="R">Reply in thread</GMenuItem>
              <GMenuItem icon="edit">Edit message</GMenuItem>
              <GMenuItem icon="sparkle" ai>Ask Donna about this</GMenuItem>
              <GMenuSep />
              <GMenuItem icon="pin">Pin to channel</GMenuItem>
              <GMenuItem icon="trash" danger>Delete</GMenuItem>
            </GPopover>
          </Cell>
          <Cell label="hover toolbar">
            <GToolbar actions={[
              { icon: "smile", title: "React" },
              { icon: "reply", title: "Reply" },
              { icon: "sparkle", title: "Ask AI", ai: true },
              { icon: "more", title: "More" },
            ]} />
          </Cell>
          <Cell label="tooltip"><GTooltip>⌘K to search</GTooltip></Cell>
          <Cell label="tabs">
            <GTabs tabs={["Messages", "Files", "Pins"]} value={tab} onChange={setTab} />
          </Cell>
        </Section>

        {/* Chat bubbles */}
        <Section title="Chat bubbles" id="bubbles">
          <Cell label="conversation" wide>
            <div style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 520 }}>
              <GBubble from="user">Can you pull the RECIST cutoff for the lung cohort?</GBubble>
              <GBubble><GAvatar name="DO" agent />Sure — for this trial the partial-response threshold is a 30% decrease, progression at 20% increase. Want me to drop it in #recist-protocol?</GBubble>
            </div>
          </Cell>
        </Section>

        {/* Agent run — showpiece */}
        <Section title="Agent run card" hint="the showpiece sticker ★" id="run">
          <Cell label="completed run" wide>
            <div style={{ maxWidth: 560 }}>
              <GRun
                label="Donna ran"
                summary="eligibility sweep"
                status="done"
                steps={[
                  { icon: "doc", label: "Read protocol v3.2", meta: "12 pages", state: "done" },
                  { icon: "bolt", label: "Matched 84 patients", meta: "registry", state: "done" },
                  { icon: "brain", label: "Cross-checked exclusions", state: "done" },
                ]}
                output="3 patients fail the washout criterion — flagged for Jordan to review before enrollment."
                memory="washout = 28d"
              />
            </div>
          </Cell>
          <Cell label="running" wide>
            <div style={{ maxWidth: 560 }}>
              <GRun
                label="Donna is working"
                status="thinking"
                running
                thought="scanning the registry for matching cohorts"
                steps={[
                  { icon: "doc", label: "Loaded eligibility matrix", state: "done" },
                  { icon: "bolt", label: "Querying registry", meta: "84 / 210", state: "running" },
                ]}
              />
            </div>
          </Cell>
        </Section>

        {/* Animations */}
        <Section title="Animations" hint="bounce, bob, spin, pop, pulse" id="animations">
          <Cell label="bob"><div className="gx-anim-bob" style={{ fontSize: 30 }}>🦔</div></Cell>
          <Cell label="wiggle"><div className="gx-anim-wiggle"><GRoleChip>AI</GRoleChip></div></Cell>
          <Cell label="pop-in"><div className="gx-anim-pop"><GBadge mention>@9</GBadge></div></Cell>
          <Cell label="spin (loader)"><span className="gx-task-check is-running" /></Cell>
          <Cell label="pulse ring"><GAvatar name="DO" agent size="lg" pulsing /></Cell>
          <Cell label="blink (status)"><span className="sc-row" style={{ alignItems: "center", gap: 8 }}><span className="gx-led running" /><span style={{ fontSize: 12, color: "var(--text-2)" }}>running</span></span></Cell>
          <Cell label="hover-press (any button)"><GButton variant="coral">Hover me</GButton></Cell>
        </Section>

        <footer className="sc-foot gx-hand">that's the whole sticker book — toggle Midnight up top ↑</footer>
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<Showcase />);
