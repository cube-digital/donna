// Mock data for DonnaAI prototype
// All names invented / generic. Not copyrighted.

window.DONNA_DATA = (function () {
  const agents = [
    {
      id: "donna",
      name: "Donna",
      role: "Chief of Staff",
      hue: 282,
      blurb: "Coordinates work, drafts, and keeps everyone aligned.",
      skills: ["Planning", "Drafting", "Meeting prep", "Follow-ups"],
      memory: 142,
      runs: 1840,
      tools: ["Calendar", "Notion", "Mail", "Drive"],
    },
    {
      id: "mira",
      name: "Mira",
      role: "Research Analyst",
      hue: 192,
      blurb: "Long-form research, market scans, source verification.",
      skills: ["Research", "Synthesis", "Citation", "Comparisons"],
      memory: 318,
      runs: 962,
      tools: ["Web", "Arxiv", "PubMed", "PDF"],
    },
    {
      id: "kai",
      name: "Kai",
      role: "Engineer",
      hue: 142,
      blurb: "Reads code, writes patches, runs diagnostics.",
      skills: ["Code review", "Refactor", "Logs", "Schema"],
      memory: 89,
      runs: 1204,
      tools: ["GitHub", "Linear", "Sentry", "Terminal"],
    },
    {
      id: "atlas",
      name: "Atlas",
      role: "Strategy",
      hue: 32,
      blurb: "Market intel, competitive analysis, briefings.",
      skills: ["Briefings", "SWOT", "Forecasts"],
      memory: 204,
      runs: 487,
      tools: ["Web", "CRM", "Sheets"],
    },
    {
      id: "nova",
      name: "Nova",
      role: "Design",
      hue: 332,
      blurb: "Critique, copywriting, brand voice.",
      skills: ["Copy", "Critique", "Voice"],
      memory: 67,
      runs: 311,
      tools: ["Figma", "Drive"],
    },
  ];

  const humans = [
    { id: "marius", name: "Marius M.", initials: "MM", color: "#c89b6a" },
    { id: "rebeca", name: "Rebeca P.", initials: "RP", color: "#7aa6d9" },
    { id: "alice", name: "Alice T.", initials: "AT", color: "#d97a7a" },
    { id: "marko", name: "Marko P.", initials: "MP", color: "#7ad9a3" },
    { id: "andreea", name: "Andreea I.", initials: "AI", color: "#b07ad9" },
    { id: "you", name: "You", initials: "YO", color: "#e8e6df" },
  ];

  const projects = [
    {
      id: "recist",
      name: "Recist Protocol",
      color: "oklch(0.72 0.12 282)",
      glyph: "R",
      channels: ["recist-protocol", "recist-data", "recist-clinicians"],
      members: 12,
      agents: ["donna", "mira", "kai"],
    },
    {
      id: "launch",
      name: "Launch Ops",
      color: "oklch(0.72 0.12 192)",
      glyph: "L",
      channels: ["launch-plan", "launch-press", "launch-metrics"],
      members: 8,
      agents: ["donna", "atlas", "nova"],
    },
    {
      id: "brand",
      name: "Brand & Site",
      color: "oklch(0.72 0.12 32)",
      glyph: "B",
      channels: ["brand-site", "brand-copy"],
      members: 5,
      agents: ["nova", "atlas"],
    },
  ];

  // Messages for #recist-protocol channel
  const channelMessages = [
    {
      id: "m1",
      kind: "system",
      text: "Marko P. created #recist-protocol · Wed, Mar 12",
    },
    {
      id: "m2",
      kind: "msg",
      author: "marius",
      time: "10:33",
      text: "Quick context for the agents joining today — we're standardizing how lesion measurements get pulled from radiology PDFs into our labeling pipeline. Donna has the brief.",
    },
    {
      id: "m3",
      kind: "msg",
      author: "rebeca",
      time: "10:41",
      text: "I dropped the v3 protocol PDF and the labeling rubric into Docs. Two open questions in there.",
      attachments: [
        { name: "RECIST_v3_protocol.pdf", size: "2.1 MB" },
        { name: "labeling_rubric.md", size: "8 KB" },
      ],
    },
    {
      id: "m4",
      kind: "agent-run",
      author: "donna",
      time: "10:42",
      summary: "Reading the brief and proposing a 3-week plan",
      status: "done",
      steps: [
        { kind: "read", label: "RECIST_v3_protocol.pdf", meta: "42 pages" },
        { kind: "read", label: "labeling_rubric.md", meta: "8 KB" },
        { kind: "think", label: "Drafted milestones, flagged 2 risks" },
        { kind: "write", label: "Plan posted below" },
      ],
      output:
        "Three-week plan: (1) Lock the lesion taxonomy with Rebeca by Fri. (2) Mira runs a literature scan on baseline scan comparability. (3) Kai stubs the parser against 20 sample PDFs. Risks: scan modality mismatch, missing baseline dates. I can own follow-ups.",
      memoryTouched: ["RECIST v3", "labeling rubric", "team availability"],
    },
    {
      id: "m5",
      kind: "msg",
      author: "alice",
      time: "10:58",
      text: "+1, looks tight. Can Mira pull comparable trial protocols too?",
    },
    {
      id: "m6",
      kind: "agent-run",
      author: "mira",
      time: "11:02",
      summary: "Searching for comparable trial protocols",
      status: "running",
      streaming: true,
      currentThought: "Scanning ClinicalTrials.gov for oncology imaging protocols filed 2022–2025 with baseline + follow-up scan cadence …",
      steps: [
        { kind: "tool", label: "ClinicalTrials.gov", meta: "query: imaging + RECIST + oncology", state: "done" },
        { kind: "tool", label: "PubMed", meta: "187 results, filtering", state: "done" },
        { kind: "read", label: "10 most-cited reviews", state: "running" },
      ],
    },
    {
      id: "m7",
      kind: "msg",
      author: "marko",
      time: "11:06",
      text: "While Mira's running — Kai, can you take a look at the PDF parser? Last run choked on multi-column tables.",
    },
    {
      id: "m8",
      kind: "agent-run",
      author: "kai",
      time: "11:08",
      summary: "Investigating multi-column table extraction",
      status: "done",
      steps: [
        { kind: "tool", label: "Read parser.py @ main", meta: "GitHub" },
        { kind: "tool", label: "Pulled 4 failing samples", meta: "from S3" },
        { kind: "think", label: "Issue is column-detection threshold at line 142" },
        { kind: "write", label: "Patch drafted (24 lines)" },
      ],
      output:
        "Found it. `column_threshold` is hard-coded to 60px which fails for narrow tables. PR up: cube-digital/recist-pipeline#284. Patch passes on all 4 samples + the existing 12 in the test suite. Want me to merge or hold for review?",
      memoryTouched: ["parser.py", "test samples", "previous bug #261"],
      attachments: [{ name: "PR #284 — fix column detection", size: "+24 / −6" }],
    },
    {
      id: "m9",
      kind: "msg",
      author: "marius",
      time: "11:14",
      text: "Hold for review please. @rebeca want to look?",
    },
    {
      id: "m10",
      kind: "msg",
      author: "rebeca",
      time: "11:15",
      text: "On it after lunch.",
      reactions: [{ emoji: "👀", count: 2 }],
    },
  ];

  // Personal AI chat — private to "you"
  const personalChats = [
    { id: "p1", title: "Quarterly review prep", when: "Today", preview: "Pulled metrics, drafted outline", agent: "donna" },
    { id: "p2", title: "Reading list for week", when: "Yesterday", preview: "6 papers + 2 essays", agent: "mira" },
    { id: "p3", title: "Travel — Berlin trip", when: "Mon", preview: "Hotel options, conflicts checked", agent: "donna" },
    { id: "p4", title: "Code review: webhook v2", when: "Fri", preview: "3 issues, 1 nit", agent: "kai" },
    { id: "p5", title: "Competitor scan — Q1", when: "Mar 28", preview: "12 companies, 4 standouts", agent: "atlas" },
  ];

  const personalMessages = [
    { id: "pm1", role: "you", time: "9:14", text: "Donna, what's on my plate today that I haven't acknowledged?" },
    {
      id: "pm2",
      role: "agent",
      agent: "donna",
      time: "9:14",
      text: "Three things. (1) Marius asked for the protocol sign-off — needs your reply before 2pm. (2) Andreea pinged about the Berlin venue — she's holding two options for you. (3) The Recist all-hands has no agenda yet and it's Thursday. Want me to draft one?",
    },
    { id: "pm3", role: "you", time: "9:15", text: "Draft the agenda. Keep it tight." },
    {
      id: "pm4",
      role: "agent",
      agent: "donna",
      time: "9:15",
      streaming: false,
      text: "Done. 4 items, 30 min total. Pulled the last two retro notes for context so we don't repeat. Want me to circulate, or hold for you to review?",
      attachments: [{ name: "recist_allhands_apr11.md", size: "1.2 KB" }],
    },
    { id: "pm5", role: "you", time: "9:17", text: "Hold for review. Also — pull last quarter's clinical-ops numbers." },
    {
      id: "pm6",
      role: "agent",
      agent: "donna",
      time: "9:17",
      status: "running",
      streaming: true,
      currentThought: "Hitting the warehouse for Q1 clinical-ops figures · scans processed, turnaround, label drift …",
      text: "",
    },
  ];

  // Chat history items for search view
  const searchResults = [
    {
      where: "#recist-protocol",
      who: "donna",
      when: "2 days ago",
      text: "Three-week plan: lock taxonomy by Fri, lit-scan, parser stub …",
    },
    {
      where: "#launch-press",
      who: "atlas",
      when: "3 days ago",
      text: "Competitive scan complete — 12 companies, key takeaway is positioning around clinical validation, not speed.",
    },
    {
      where: "Personal · Donna",
      who: "donna",
      when: "Mon",
      text: "Berlin trip — held 2 hotels matching your 10-min-to-venue rule, both refundable.",
    },
    {
      where: "#recist-data",
      who: "kai",
      when: "Mon",
      text: "Fixed column detection in parser.py — see PR #284. All test samples pass.",
    },
    {
      where: "DM · Rebeca",
      who: "rebeca",
      when: "Mon",
      text: "Can you grab the v3 protocol from drive and share with the room?",
    },
    {
      where: "#recist-protocol",
      who: "mira",
      when: "Last week",
      text: "Comparable protocols: 14 found in oncology imaging space, 4 highly relevant.",
    },
  ];

  return { agents, humans, projects, channelMessages, personalChats, personalMessages, searchResults };
})();
