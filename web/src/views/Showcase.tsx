// Showcase gallery — organised by atomic-design tiers.
//
//   Foundations  — colour tokens, type, motion
//   Atoms        — smallest indivisible units (icons, buttons, badges, ...)
//   Molecules    — combinations of atoms (inputs, list rows, switches, ...)
//   Organisms    — composed surfaces (run card, bubble, composer, sidebar, ...)
//
// A sticky in-page nav floats on the right so reviewers can jump
// between tiers without scroll-hunting. The whole page mounts a
// public route (`/showcase`) — no auth needed.

import { useCallback, useState, type ReactNode } from "react";

import {
  GAvatar,
  GAvatarStack,
  GBadge,
  GBubble,
  GButton,
  GCard,
  GCheck,
  GChip,
  GDoc,
  GEmptyState,
  GField,
  GFormField,
  GIc,
  GIconButton,
  GInput,
  GList,
  GListItem,
  GMenuItem,
  GMenuSep,
  GPopover,
  GRoleChip,
  GRun,
  GStat,
  GSwitch,
  GTabs,
  GTag,
  GTaskCheck,
  GToast,
  GToolbar,
  GTooltip,
  GlyphSlot,
  GoofyTheme,
  type IconName,
} from "../components/Goofy";

// ─── Layout primitives ──────────────────────────────────────────────────

function Tier({
  id,
  title,
  blurb,
  children,
}: {
  id: string;
  title: string;
  blurb: string;
  children: ReactNode;
}) {
  return (
    <section id={id} className="scroll-mt-6 mb-12">
      <header className="mb-5 pl-1">
        <h2 className="font-display font-semibold text-[32px] leading-none text-text-0 m-0">
          {title}
        </h2>
        <p className="font-hand font-bold text-[20px] text-ai-deep mt-1.5">
          {blurb}
        </p>
      </header>
      <div className="flex flex-col gap-6">{children}</div>
    </section>
  );
}

function Section({
  title,
  hint,
  id,
  cols = 3,
  children,
}: {
  title: string;
  hint?: string;
  id?: string;
  cols?: 2 | 3;
  children: ReactNode;
}) {
  const gridCls =
    cols === 2
      ? "grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-7"
      : "grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-7";
  return (
    <section
      id={id}
      className="scroll-mt-6 border-2 border-ink rounded-[18px] shadow-ink-1 bg-bg-1 p-6 md:p-8"
    >
      <header className="flex items-baseline gap-3 mb-6 flex-wrap">
        <h3 className="font-display font-semibold text-[24px] leading-none text-text-0 m-0">
          {title}
        </h3>
        {hint ? (
          <span className="font-hand font-bold text-[19px] text-ai-deep">
            {hint}
          </span>
        ) : null}
      </header>
      <div className={gridCls}>{children}</div>
    </section>
  );
}

function Cell({
  label,
  wide = false,
  children,
}: {
  label?: ReactNode;
  wide?: boolean;
  children: ReactNode;
}) {
  return (
    <div className={"flex flex-col gap-2.5 " + (wide ? "sm:col-span-2 md:col-span-3" : "")}>
      <div className="flex items-center gap-3 flex-wrap min-h-[44px]">{children}</div>
      {label ? (
        // Calm 1 px solid hairline — dashed separator competed visually
        // with the run-card's intentional dashed dividers.
        <div className="font-mono text-[10.5px] text-text-3 uppercase tracking-[0.06em] border-t border-border-soft pt-1.5">
          {label}
        </div>
      ) : null}
    </div>
  );
}

// ─── Foundations data ───────────────────────────────────────────────────

const NEUTRAL_SWATCHES: Array<[string, string]> = [
  ["--ink", "ink"],
  ["--bg-0", "bg-0"],
  ["--bg-1", "bg-1"],
  ["--bg-2", "bg-2"],
  ["--bg-3", "bg-3"],
  ["--bg-4", "bg-4"],
  ["--text-0", "text-0"],
  ["--text-2", "text-2"],
];

const ACCENT_SWATCHES: Array<[string, string]> = [
  ["--ai", "ai grape"],
  ["--pop-blue", "blue"],
  ["--pop-coral", "coral"],
  ["--pop-sun", "sun"],
  ["--pop-mint", "mint"],
  ["--ok", "ok"],
  ["--warn", "warn"],
  ["--danger", "danger"],
];

function Swatch({ token, name }: { token: string; name: string }) {
  return (
    <div className="flex items-center gap-2.5 p-2 rounded-[10px] border-2 border-ink bg-bg-1 shadow-ink-1">
      <div
        className="w-9 h-9 rounded-[9px] border-2 border-ink shrink-0"
        style={{ background: `var(${token})` }}
      />
      <div className="flex flex-col leading-tight">
        <b className="font-display text-[13px] text-text-0">{name}</b>
        <code className="font-mono text-[11px] text-text-3">{token}</code>
      </div>
    </div>
  );
}

// ─── Sticky nav ──────────────────────────────────────────────────────────

const NAV_TIERS = [
  { id: "foundations", label: "Foundations" },
  { id: "atoms", label: "Atoms" },
  { id: "molecules", label: "Molecules" },
  { id: "organisms", label: "Organisms" },
];

// ─── Showcase ────────────────────────────────────────────────────────────

export default function Showcase() {
  const [dark, setDark] = useState(false);
  const [wiggly, setWiggly] = useState(false);
  const [tab, setTab] = useState<"Messages" | "Files" | "Pins">("Messages");
  const [chips, setChips] = useState<Record<string, boolean>>({
    All: true,
    Docs: false,
    Runs: false,
  });
  const [checks, setChecks] = useState<{ a: boolean; b: boolean }>({
    a: true,
    b: false,
  });
  const [switchOn, setSwitchOn] = useState(true);
  const [activeChannel, setActiveChannel] = useState("recist-protocol");
  const [composerText, setComposerText] = useState("");
  const [showToast, setShowToast] = useState(true);

  const handleNavClick = useCallback((id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  return (
    <GoofyTheme dark={dark} wiggly={wiggly} paper className="min-h-screen">
      <div className="max-w-[1100px] mx-auto px-5 md:px-8 py-8 grid grid-cols-1 lg:grid-cols-[1fr_140px] gap-6">
        <div>
          {/* Masthead */}
          <header className="flex items-center justify-between gap-4 flex-wrap mb-10 p-5 md:p-6 border-2 border-ink rounded-[18px] shadow-ink-1 bg-bg-1">
            <div className="flex items-center gap-4">
              <div className="w-[68px] h-[68px] grid place-items-center border-2 border-ink rounded-[14px] shadow-ink-1 bg-pop-sun text-4xl animate-bob">
                🦔
              </div>
              <div>
                <h1 className="font-display font-semibold text-[34px] leading-none text-text-0 m-0">
                  Goofy UI
                </h1>
                <p className="font-hand font-bold text-[22px] text-ai-deep m-0 mt-1">
                  a bouncy sticker-book component kit
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <GTabs<"Cream" | "Midnight">
                tabs={["Cream", "Midnight"]}
                value={dark ? "Midnight" : "Cream"}
                onChange={(t) => setDark(t === "Midnight")}
              />
              <label className="flex items-center gap-2 text-[12.5px] text-text-2">
                <GSwitch on={wiggly} onChange={setWiggly} />
                <span>wiggle</span>
              </label>
            </div>
          </header>

          {/* ─── FOUNDATIONS ─── */}
          <Tier
            id="foundations"
            title="Foundations"
            blurb="tokens, type & motion — the base layer everything else sits on"
          >
            <Section
              title="Color schemes"
              hint="cream paper ✦ midnight slate"
              cols={2}
            >
              <div className="col-span-full grid grid-cols-1 md:grid-cols-2 gap-5">
                <div className="border-2 border-dashed border-border-soft rounded-[14px] p-4">
                  <div className="font-mono text-[11px] text-text-3 mb-3 uppercase tracking-[0.06em]">
                    Neutrals · {dark ? "midnight" : "cream"}
                  </div>
                  <div className="grid grid-cols-2 gap-2.5">
                    {NEUTRAL_SWATCHES.map(([token, name]) => (
                      <Swatch key={token} token={token} name={name} />
                    ))}
                  </div>
                </div>
                <div className="border-2 border-dashed border-border-soft rounded-[14px] p-4">
                  <div className="font-mono text-[11px] text-text-3 mb-3 uppercase tracking-[0.06em]">
                    Accents · crayon box + grape AI
                  </div>
                  <div className="grid grid-cols-2 gap-2.5">
                    {ACCENT_SWATCHES.map(([token, name]) => (
                      <Swatch key={token} token={token} name={name} />
                    ))}
                  </div>
                </div>
              </div>
            </Section>

            <Section title="Type" hint="Fredoka · Caveat · Geist">
              <Cell label="Fredoka — display" wide>
                <div className="font-display text-[30px] text-text-0">
                  The quick brown hedgehog
                </div>
              </Cell>
              <Cell label="Caveat — hand-lettered" wide>
                <div className="font-hand font-bold text-[24px] text-ai-deep">
                  resurfaced decisions ✎
                </div>
              </Cell>
              <Cell label="Geist — body" wide>
                <div className="text-[14px] text-text-1 max-w-[460px]">
                  Body copy rides on cream paper with a faint dotted texture. Ink
                  borders stay chunky, shadows stay hard.
                </div>
              </Cell>
              <Cell label="Geist Mono — meta">
                <code className="font-mono text-[13px] text-text-2">
                  2.4s · 1,208 tok
                </code>
              </Cell>
            </Section>

            <Section title="Motion" hint="bounce, bob, spin, pop, pulse">
              <Cell label="bob">
                <div className="text-3xl animate-bob">🦔</div>
              </Cell>
              <Cell label="wiggle">
                <div className="animate-wiggle">
                  <GRoleChip>AI</GRoleChip>
                </div>
              </Cell>
              <Cell label="pop-in">
                <div className="animate-pop-in">
                  <GBadge mention>@9</GBadge>
                </div>
              </Cell>
              <Cell label="spin (loader)">
                <GTaskCheck state="running" />
              </Cell>
              <Cell label="pulse ring">
                <GAvatar kind="agent" name="DO" size="lg" pulsing />
              </Cell>
              <Cell label="blink (status LED)">
                <span className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-ai animate-led-blink" />
                  <span className="text-[12px] text-text-2">running</span>
                </span>
              </Cell>
            </Section>
          </Tier>

          {/* ─── ATOMS ─── */}
          <Tier
            id="atoms"
            title="Atoms"
            blurb="indivisible — every component eventually decomposes to these"
          >
            <Section title="Buttons" hint="press down + tilt on hover">
              <Cell label="default">
                <GButton>Button</GButton>
              </Cell>
              <Cell label="coral / primary">
                <GButton variant="coral" icon="plus">
                  New channel
                </GButton>
              </Cell>
              <Cell label="ai grape">
                <GButton variant="ai" icon="sparkle">
                  Ask Donna
                </GButton>
              </Cell>
              <Cell label="sun">
                <GButton variant="sun">Sunny</GButton>
              </Cell>
              <Cell label="mint">
                <GButton variant="mint" icon="check">
                  Done
                </GButton>
              </Cell>
              <Cell label="blue">
                <GButton variant="blue">Open</GButton>
              </Cell>
              <Cell label="ghost">
                <GButton variant="ghost">Ghost</GButton>
              </Cell>
              <Cell label="disabled">
                <GButton disabled>Disabled</GButton>
              </Cell>
              <Cell label="sizes" wide>
                <GButton size="sm" variant="coral">
                  Small
                </GButton>
                <GButton variant="coral">Medium</GButton>
                <GButton size="lg" variant="coral">
                  Large
                </GButton>
              </Cell>
              <Cell label="icon buttons" wide>
                <GIconButton icon="smile" aria-label="React" />
                <GIconButton icon="more" aria-label="More" />
                <GIconButton icon="plus" outlined aria-label="New" />
                <GIconButton icon="sparkle" outlined aria-label="Ask AI" />
              </Cell>
            </Section>

            <Section title="Icons" hint="self-contained set · stroke = currentColor">
              <div className="col-span-full grid grid-cols-6 sm:grid-cols-8 md:grid-cols-10 gap-3">
                {(Object.keys(GIc) as IconName[]).map((name) => (
                  <div
                    key={name}
                    className="flex flex-col items-center gap-1.5 p-2 rounded-[10px] border-2 border-dashed border-border-soft text-text-2"
                    title={name}
                  >
                    <GlyphSlot name={name} size={20} />
                    <span className="font-mono text-[9.5px] text-text-3 uppercase tracking-[0.04em]">
                      {name}
                    </span>
                  </div>
                ))}
              </div>
            </Section>

            <Section title="Chips" hint="filter & label stickers — colour variants">
              <Cell label="default · paper">
                <GChip>label</GChip>
                <GChip active>active</GChip>
              </Cell>
              <Cell label="mint">
                <GChip variant="mint">
                  <GlyphSlot name="sparkle" size={11} /> @Donna
                </GChip>
              </Cell>
              <Cell label="sun · ai · blue · coral" wide>
                <GChip variant="sun">sun</GChip>
                <GChip variant="ai">
                  <GlyphSlot name="sparkle" size={11} /> ai
                </GChip>
                <GChip variant="blue">blue</GChip>
                <GChip variant="coral">coral</GChip>
              </Cell>
              <Cell label="removable">
                <GChip onRemove={() => undefined}>oncology</GChip>
              </Cell>
            </Section>

            <Section title="Badges & tags" hint="stamps you stick anywhere">
              <Cell label="count badge">
                <GBadge>3</GBadge>
                <GBadge>24</GBadge>
              </Cell>
              <Cell label="mention badge">
                <GBadge mention>@5</GBadge>
              </Cell>
              <Cell label="role chip">
                <GRoleChip>AI</GRoleChip>
                <GRoleChip>AGENT</GRoleChip>
              </Cell>
              <Cell label="tags">
                <GTag>label</GTag>
                <GTag variant="mint">live</GTag>
                <GTag variant="sun" count={12}>
                  threads
                </GTag>
              </Cell>
              <Cell label="tooltip / sticky note">
                <GTooltip>⌘K to search</GTooltip>
              </Cell>
              <Cell label="status indicators">
                <span className="flex items-center gap-1.5 text-[12px] text-text-2">
                  <span className="w-2 h-2 rounded-full bg-ok" />
                  done
                </span>
                <span className="flex items-center gap-1.5 text-[12px] text-text-2">
                  <span className="w-2 h-2 rounded-full bg-ai animate-led-blink" />
                  running
                </span>
                <span className="flex items-center gap-1.5 text-[12px] text-text-2">
                  <span className="w-2 h-2 rounded-full bg-text-3" />
                  todo
                </span>
              </Cell>
            </Section>

            <Section title="Avatars" hint="every face gets an ink outline">
              <Cell label="sizes" wide>
                <GAvatar name="JD" color="var(--pop-blue)" size="sm" />
                <GAvatar name="JD" color="var(--pop-coral)" />
                <GAvatar name="JD" color="var(--pop-mint)" size="lg" />
                <GAvatar name="JD" color="var(--pop-sun)" size="xl" />
              </Cell>
              <Cell label="agent · gradient">
                <GAvatar kind="agent" name="DO" />
                <GAvatar kind="agent" name="MI" hue={210} />
                <GAvatar kind="agent" name="AT" hue={150} />
              </Cell>
              <Cell label="pulsing while streaming">
                <GAvatar kind="agent" name="DO" size="lg" pulsing />
              </Cell>
              <Cell label="stacked group" wide>
                <GAvatarStack
                  people={[
                    { name: "AB", color: "var(--pop-coral)" },
                    { name: "CD", color: "var(--pop-blue)" },
                    { name: "EF", color: "var(--pop-mint)" },
                    { kind: "agent", name: "DO" },
                  ]}
                />
              </Cell>
            </Section>

            <Section title="Spinners & loaders">
              <Cell label="task spinner">
                <GTaskCheck state="running" />
              </Cell>
              <Cell label="thought dots">
                <span className="text-text-2 italic text-[13px]">
                  thinking<span className="thought-dots" />
                </span>
              </Cell>
              <Cell label="led blink">
                <span className="w-2.5 h-2.5 rounded-full bg-ai animate-led-blink" />
              </Cell>
            </Section>
          </Tier>

          {/* ─── MOLECULES ─── */}
          <Tier
            id="molecules"
            title="Molecules"
            blurb="combinations of atoms that act as one — inputs, list rows, switches"
          >
            <Section title="Inputs" hint="capsules & note cards">
              <Cell label="search capsule" wide>
                <GInput placeholder="Search everything…" kbd="⌘K" />
              </Cell>
              <Cell label="text capsule" wide>
                <GInput icon="edit" placeholder="Name this channel…" />
              </Cell>
              <Cell label="note-card textarea" wide>
                <div className="w-full">
                  <GField
                    placeholder="Message #recist-protocol…"
                    trailing={
                      <div className="flex items-center gap-2 mt-2">
                        <GTag variant="mint">
                          <GlyphSlot name="sparkle" size={11} /> @Donna
                        </GTag>
                        <span className="flex-1" />
                        <GIconButton icon="send" outlined aria-label="Send" />
                      </div>
                    }
                  />
                </div>
              </Cell>
              <Cell label="ai ask field" wide>
                <div className="w-full">
                  <GField ai placeholder="Ask the vault anything…" rows={2} />
                </div>
              </Cell>
            </Section>

            <Section title="Form fields" hint="label + control + helper">
              <Cell label="basic" wide>
                <div className="w-full max-w-[420px]">
                  <GFormField
                    label="Channel name"
                    hint="Letters, numbers, dashes — keep it short."
                  >
                    <GInput icon="edit" placeholder="recist-protocol" />
                  </GFormField>
                </div>
              </Cell>
              <Cell label="required + error" wide>
                <div className="w-full max-w-[420px]">
                  <GFormField
                    label="Workspace slug"
                    required
                    error="Slug already taken — try another."
                  >
                    <GInput icon="hash" placeholder="cube" />
                  </GFormField>
                </div>
              </Cell>
              <Cell label="row layout" wide>
                <div className="w-full max-w-[520px]">
                  <GFormField label="Notifications" layout="row" hint="Email me when an agent mentions me.">
                    <GSwitch on={switchOn} onChange={setSwitchOn} />
                  </GFormField>
                </div>
              </Cell>
            </Section>

            <Section title="Filter chips" hint="stateful — toggle filters">
              <Cell label="multi-select filter" wide>
                {Object.keys(chips).map((k) => (
                  <GChip
                    key={k}
                    active={chips[k]}
                    onClick={() => setChips((c) => ({ ...c, [k]: !c[k] }))}
                  >
                    {k}
                  </GChip>
                ))}
              </Cell>
            </Section>

            <Section title="Toggles" hint="checks, spinners & switches">
              <Cell label="checkbox">
                <GCheck
                  checked={checks.a}
                  onChange={(v) => setChecks((c) => ({ ...c, a: v }))}
                />
                <GCheck
                  checked={checks.b}
                  onChange={(v) => setChecks((c) => ({ ...c, b: v }))}
                />
              </Cell>
              <Cell label="task states">
                <GTaskCheck state="todo" />
                <GTaskCheck state="running" />
                <GTaskCheck state="done" />
              </Cell>
              <Cell label="switch">
                <GSwitch on={switchOn} onChange={setSwitchOn} />
              </Cell>
            </Section>

            <Section title="List row · doc row · menu item">
              <Cell label="list item — channel" wide>
                <div className="w-full max-w-[260px]">
                  <GListItem hash="#" active>
                    recist-protocol
                  </GListItem>
                </div>
              </Cell>
              <Cell label="list item — with badge" wide>
                <div className="w-full max-w-[260px]">
                  <GListItem hash="#" badge={<GBadge mention>3</GBadge>}>
                    trial-ops
                  </GListItem>
                </div>
              </Cell>
              <Cell label="doc row" wide>
                <div className="w-full max-w-[280px]">
                  <GDoc name="Protocol v3.2.pdf" meta="2.4mb" />
                </div>
              </Cell>
              <Cell label="menu item — ai variant" wide>
                <div className="w-full max-w-[280px]">
                  <GPopover>
                    <GMenuItem icon="sparkle" ai kbd="A">
                      Ask Donna about this
                    </GMenuItem>
                  </GPopover>
                </div>
              </Cell>
            </Section>

            <Section title="Tabs">
              <Cell label="segmented" wide>
                <GTabs<"Messages" | "Files" | "Pins">
                  tabs={["Messages", "Files", "Pins"]}
                  value={tab}
                  onChange={setTab}
                />
              </Cell>
            </Section>

            <Section title="Card · stat">
              <Cell label="basic card" wide>
                <div className="w-full">
                  <GCard
                    hover
                    title="Weekly digest"
                    sub="Donna summarised 14 threads and flagged 2 decisions for review."
                  />
                </div>
              </Cell>
              <Cell label="ai card" wide>
                <div className="w-full">
                  <GCard
                    ai
                    title="Memory updated"
                    sub="Remembered that the RECIST cutoff is 20% for this trial."
                  >
                    <div className="flex items-center gap-2 mt-2.5">
                      <GTag variant="mint">
                        <GlyphSlot name="brain" size={11} /> memory
                      </GTag>
                    </div>
                  </GCard>
                </div>
              </Cell>
              <Cell label="stats" wide>
                <GStat value="248" label="runs" />
                <GStat value="2.4s" label="median" />
                <GStat value="98%" label="approved" />
              </Cell>
            </Section>
          </Tier>

          {/* ─── ORGANISMS ─── */}
          <Tier
            id="organisms"
            title="Organisms"
            blurb="full surfaces — composed from molecules + atoms into something usable"
          >
            <Section title="Lists" hint="sidebar items snap into stickers">
              <Cell label="channel list" wide>
                <div className="w-full max-w-[260px]">
                  <GList>
                    <GListItem
                      hash="#"
                      active={activeChannel === "recist-protocol"}
                      onClick={() => setActiveChannel("recist-protocol")}
                    >
                      recist-protocol
                    </GListItem>
                    <GListItem
                      hash="#"
                      badge={<GBadge mention>3</GBadge>}
                      active={activeChannel === "trial-ops"}
                      onClick={() => setActiveChannel("trial-ops")}
                    >
                      trial-ops
                    </GListItem>
                    <GListItem
                      dot="ai"
                      active={activeChannel === "donna"}
                      onClick={() => setActiveChannel("donna")}
                    >
                      Donna
                    </GListItem>
                    <GListItem
                      dot="online"
                      active={activeChannel === "jordan"}
                      onClick={() => setActiveChannel("jordan")}
                    >
                      Jordan Patel
                    </GListItem>
                  </GList>
                </div>
              </Cell>
              <Cell label="document list" wide>
                <div className="w-full max-w-[280px]">
                  <GDoc name="Protocol v3.2.pdf" meta="2.4mb" />
                  <GDoc icon="link" name="Trial registry entry" meta="ext" />
                  <GDoc name="Eligibility matrix" meta="edited 2d" />
                </div>
              </Cell>
            </Section>

            <Section title="Popovers · toolbars" hint="hover-to-reveal action surfaces">
              <Cell label="dropdown menu" wide>
                <GPopover>
                  <GMenuItem icon="reply" kbd="R">
                    Reply in thread
                  </GMenuItem>
                  <GMenuItem icon="edit">Edit message</GMenuItem>
                  <GMenuItem icon="sparkle" ai>
                    Ask Donna about this
                  </GMenuItem>
                  <GMenuSep />
                  <GMenuItem icon="pin">Pin to channel</GMenuItem>
                  <GMenuItem icon="trash" danger>
                    Delete
                  </GMenuItem>
                </GPopover>
              </Cell>
              <Cell label="hover toolbar">
                <GToolbar
                  actions={[
                    { icon: "smile", title: "React" },
                    { icon: "reply", title: "Reply" },
                    { icon: "sparkle", title: "Ask AI", ai: true },
                    { icon: "more", title: "More" },
                  ]}
                />
              </Cell>
            </Section>

            <Section title="Chat bubbles">
              <Cell label="conversation" wide>
                <div className="w-full max-w-[520px] flex flex-col gap-3">
                  <GBubble from="user">
                    Can you pull the RECIST cutoff for the lung cohort?
                  </GBubble>
                  <GBubble>
                    Sure — for this trial the partial-response threshold is a 30%
                    decrease, progression at 20% increase. Want me to drop it in
                    #recist-protocol?
                  </GBubble>
                </div>
              </Cell>
            </Section>

            <Section title="Agent run card" hint="the showpiece sticker ★">
              <Cell label="completed run" wide>
                <div className="w-full max-w-[560px]">
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
                <div className="w-full max-w-[560px]">
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

            <Section title="Empty states" hint="when there's nothing to show">
              <Cell label="neutral · with CTA" wide>
                <div className="w-full">
                  <GEmptyState
                    icon="msg"
                    title="No messages yet"
                    sub="invite a teammate or @Donna to break the ice"
                    cta={<GButton variant="coral" icon="plus">Invite</GButton>}
                  />
                </div>
              </Cell>
              <Cell label="ai · welcome" wide>
                <div className="w-full">
                  <GEmptyState
                    tone="ai"
                    icon="sparkle"
                    title="Donna is ready"
                    sub="ask anything — protocols, patients, paperwork"
                    cta={<GButton variant="ai" icon="sparkle">Say hi</GButton>}
                  />
                </div>
              </Cell>
            </Section>

            <Section title="Toasts" hint="stack 'em on dispatch">
              <Cell label="success" wide>
                <div className="w-full">
                  <GToast
                    tone="success"
                    title="Saved"
                    sub="Channel description updated."
                    onDismiss={() => undefined}
                  />
                </div>
              </Cell>
              <Cell label="ai · with actions" wide>
                <div className="w-full">
                  {showToast ? (
                    <GToast
                      tone="ai"
                      title="Donna found a conflict"
                      sub="Two patients are enrolled in overlapping cohorts."
                      actions={
                        <>
                          <GButton size="sm" variant="ai">
                            Open
                          </GButton>
                          {/* No `variant` prop — uses the default beige-hover atom. */}
                          <GButton size="sm" onClick={() => setShowToast(false)}>
                            Dismiss
                          </GButton>
                        </>
                      }
                      onDismiss={() => setShowToast(false)}
                    />
                  ) : (
                    <GButton variant="ghost" onClick={() => setShowToast(true)}>
                      Re-show toast
                    </GButton>
                  )}
                </div>
              </Cell>
              <Cell label="danger" wide>
                <div className="w-full">
                  <GToast
                    tone="danger"
                    title="Couldn't reach the registry"
                    sub="Retrying in 30 seconds…"
                  />
                </div>
              </Cell>
            </Section>

            <Section title="Composer" hint="full message-write surface">
              <Cell label="channel composer" wide>
                <div className="w-full max-w-[640px]">
                  <div className="flex items-center gap-1 p-1.5 mb-2 rounded-[10px] border-2 border-ink shadow-ink-1 bg-bg-1 w-fit">
                    <GIconButton icon="bolt" aria-label="Bold" />
                    <GIconButton icon="edit" aria-label="Italic" />
                    <GIconButton icon="link" aria-label="Link" />
                    <span className="w-px h-5 bg-border-soft mx-1" />
                    <GIconButton icon="smile" aria-label="Emoji" />
                  </div>
                  <GField
                    value={composerText}
                    onChange={(e) => setComposerText(e.target.value)}
                    placeholder="Message #recist-protocol…"
                    rows={3}
                    trailing={
                      <div className="flex items-center gap-2 mt-2.5">
                        <GChip variant="mint">
                          <GlyphSlot name="sparkle" size={11} /> @Donna
                        </GChip>
                        <GChip>
                          <GlyphSlot name="doc" size={11} /> protocol.pdf
                        </GChip>
                        <span className="flex-1" />
                        <GIconButton icon="at" aria-label="Mention" />
                        <GIconButton icon="plus" aria-label="Attach" />
                        <GButton size="sm" variant="coral" icon="send">
                          Send
                        </GButton>
                      </div>
                    }
                  />
                </div>
              </Cell>
            </Section>

            <Section title="Filter bar" hint="chips + tabs working together">
              <Cell label="search & filter row" wide>
                <div className="w-full flex flex-col gap-3">
                  <div className="flex items-center gap-3 flex-wrap">
                    <div className="flex-1 min-w-[200px]">
                      <GInput placeholder="Search messages, files, agents…" kbd="⌘K" />
                    </div>
                    <GTabs<"All" | "Channels" | "DMs">
                      tabs={["All", "Channels", "DMs"]}
                      value="All"
                      onChange={() => undefined}
                    />
                  </div>
                  <div className="flex items-center gap-2 flex-wrap">
                    {Object.keys(chips).map((k) => (
                      <GChip
                        key={k}
                        active={chips[k]}
                        onClick={() => setChips((c) => ({ ...c, [k]: !c[k] }))}
                      >
                        {k}
                      </GChip>
                    ))}
                    <GChip onRemove={() => undefined}>has:attachment</GChip>
                    <GChip onRemove={() => undefined}>from:Donna</GChip>
                  </div>
                </div>
              </Cell>
            </Section>

            <Section title="Mini sidebar" hint="real-world composition">
              <Cell label="workspace nav" wide>
                <div className="w-[240px] border-2 border-ink rounded-[14px] shadow-ink-1 bg-bg-1 p-3 flex flex-col gap-3">
                  <div className="flex items-center gap-2 px-2">
                    <div className="w-8 h-8 grid place-items-center rounded-[8px] border-2 border-ink bg-pop-sun text-on-bright font-display font-bold text-[14px]">
                      C
                    </div>
                    <div className="flex-1">
                      <div className="font-display font-semibold text-text-0 text-[14px] leading-tight">
                        Cube
                      </div>
                      <div className="font-mono text-[10.5px] text-text-3">cube</div>
                    </div>
                    <GIconButton icon="more" aria-label="Workspace settings" />
                  </div>
                  <GInput placeholder="Search…" kbd="⌘K" />
                  <div>
                    <div className="font-hand font-bold text-[15px] text-ai-deep px-2 mb-1">
                      channels
                    </div>
                    <GList>
                      <GListItem hash="#" active>
                        recist-protocol
                      </GListItem>
                      <GListItem hash="#" badge={<GBadge mention>3</GBadge>}>
                        trial-ops
                      </GListItem>
                      <GListItem hash="#">launch-plan</GListItem>
                    </GList>
                  </div>
                  <div>
                    <div className="font-hand font-bold text-[15px] text-ai-deep px-2 mb-1">
                      teammates
                    </div>
                    <GList>
                      <GListItem dot="ai">Donna</GListItem>
                      <GListItem dot="online">Jordan Patel</GListItem>
                      <GListItem dot="muted">Sam Reyes</GListItem>
                    </GList>
                  </div>
                </div>
              </Cell>
            </Section>

            <Section title="Login card" hint="auth surface composition">
              <Cell label="sign-in" wide>
                <div className="w-full max-w-[400px] border-2 border-ink rounded-[18px] shadow-ink-2 bg-bg-1 p-7">
                  <div className="flex items-center gap-3 mb-5">
                    <div className="w-12 h-12 grid place-items-center rounded-[12px] border-2 border-ink shadow-ink-1 bg-pop-sun text-2xl">
                      🦔
                    </div>
                    <div>
                      <div className="font-display font-semibold text-[20px] text-text-0">
                        Welcome back
                      </div>
                      <div className="font-hand font-bold text-[16px] text-ai-deep">
                        sign in to your workspace
                      </div>
                    </div>
                  </div>
                  <div className="flex flex-col gap-3.5">
                    <GFormField label="Email">
                      <GInput icon="at" placeholder="you@company.com" />
                    </GFormField>
                    <GFormField label="Password">
                      <GInput icon="lock" placeholder="••••••••" type="password" />
                    </GFormField>
                    <GButton variant="coral" className="w-full justify-center">
                      Sign in
                    </GButton>
                    <div className="flex items-center gap-2 my-1">
                      <span className="flex-1 h-0.5 border-t-2 border-dashed border-border-soft" />
                      <span className="font-mono text-[10px] text-text-3 uppercase">or</span>
                      <span className="flex-1 h-0.5 border-t-2 border-dashed border-border-soft" />
                    </div>
                    <GButton variant="ghost" icon="sparkle" className="w-full justify-center">
                      Continue with Google
                    </GButton>
                  </div>
                </div>
              </Cell>
            </Section>
          </Tier>

          <footer className="font-hand font-bold text-[22px] text-ai-deep text-center pt-2 pb-10">
            that&apos;s the whole sticker book — flip wiggle on for chaos ↑
          </footer>
        </div>

        {/* Sticky tier nav */}
        <nav
          aria-label="Showcase sections"
          className="hidden lg:block lg:sticky lg:top-6 lg:self-start"
        >
          <div className="border-2 border-ink rounded-[14px] shadow-ink-1 bg-bg-1 p-2">
            {NAV_TIERS.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => handleNavClick(t.id)}
                className="block w-full text-left px-2.5 py-1.5 rounded-md font-display font-medium text-[12.5px] text-text-1 hover:bg-bg-3 hover:text-text-0"
              >
                {t.label}
              </button>
            ))}
          </div>
        </nav>
      </div>
    </GoofyTheme>
  );
}
