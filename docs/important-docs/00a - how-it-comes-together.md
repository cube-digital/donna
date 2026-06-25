# How It All Comes Together — Plain English

No jargon. One story, one week, one client. Read top to bottom.

---

## The cast

- **You** run the agency `qube-digital`.
- **Acme** is a client. **Alice** works there.
- Donna is connected to your Fathom (meetings), Gmail, and Drive.
- Cortex is the system that turns everything those tools produce into
  **one wiki that an AI agent can trust**.

---

## Monday — a meeting happens

You have a call with Alice: "Acme onboarding kickoff". Fathom records it.
Here is everything that happens, in order:

**1. The raw recording is saved untouched.**
The exact JSON Fathom sent goes into storage as-is. Nobody ever edits it.

> *Why:* if anything downstream is ever wrong or disputed, this is the
> evidence locker. You can always rebuild everything from here.

**2. The transcript is converted to markdown — word for word.**
No AI rewrites it. It's a format change, like converting a .docx to .pdf.
The words are identical.

**3. A "cover sheet" is stapled on top.**
This is the frontmatter — pure facts copied from what Fathom already knows:

```markdown
---
type: meeting
title: Acme onboarding kickoff
occurred_at: 2026-06-08 14:00
attendees:
  - "Alice <alice@acme.com> (host)"
  - "You <you@qube.digital>"
duration_min: 45
---

# Acme onboarding kickoff

[ ...the full transcript, verbatim... ]

Source: fathom://meeting/rec-abc123
```

> *Why:* an agent can read the cover sheet in a split second and know
> what this is, who was there, and when — without reading 40 pages of
> transcript. And the `Source:` line at the bottom means every page in
> the wiki can prove where it came from.

**4. The system notices WHO and WHAT this is about.**
It sees `alice@acme.com` in the attendee list. It checks: do I have a
page for Alice? No → it creates a small stub page:

```markdown
# Alice
type: person, email: alice@acme.com
Spawned by: cortex-resolver
```

Same for Acme (it noticed the `acme.com` email domain → that's a company).
This is done by simple rules — email matching — **not** by an AI guessing.

> *Why:* now "Alice" and "Acme" are real things in the system, not just
> words in a transcript. Every future document that mentions them will
> point at these same pages.

**5. Invisible threads are tied.**
The meeting page gets links: *mentions → Alice, mentions → Acme.*
These are stored like database arrows, not text.

**6. The meeting gets a topic.**
The transcript is turned into a "fingerprint" (an embedding — a list of
numbers that captures what the text is *about*). The system compares it
with every other fingerprint in your workspace and says: "this belongs
with the other onboarding stuff." That topic group is a **cluster**.

> *Why:* nobody has to manually decide which folder things belong in.
> Topics emerge from the content itself.

**7. The page is filed in exactly one place.**

```
meetings/2026/06/2026-06-08-acme-onboarding-kickoff.md
```

One canonical home. Everything else (the Acme view, the topic view) is
computed, never copied.

---

## Tuesday — an email arrives

Alice emails you: "Re: onboarding — we'll use Stripe for payments."

The exact same 7 steps run. The important part: step 4 finds that Alice
and Acme **already have pages** — so instead of creating new ones, the
email simply points at the same Alice and the same Acme.

This is the moment the magic compounds. Two completely different tools
(Fathom and Gmail), two different formats, and the system knows they're
about the same person and the same client.

---

## Wednesday — a contract PDF lands in Drive

A scanned PDF. Here OCR kicks in — the only step that differs: the PDF's
text is extracted to markdown (trying the cheap fast tool first, falling
back to smarter tools only if needed).

One more thing happens: a PDF doesn't announce what kind of document it
is. So a small AI is asked **one tightly controlled question**: "is this
an offer / contract / spec / runbook / ...?" It must pick from a fixed
list of 16 — it cannot invent a category. It answers: `contract`.

> *Why this is safe:* the AI never writes content. It fills one field on
> the cover sheet, from a closed menu. The contract text itself is
> verbatim.

---

## What exists after three days

**The filesystem (what you'd see in Obsidian):**

```
qube-digital/
├── meetings/2026/06/2026-06-08-acme-onboarding-kickoff.md
├── emails/2026/06/2026-06-09-re-onboarding-stripe.md
├── docs/2026-06-10-acme-services-contract.md
├── people/
│   └── alice.md
└── clients/
    └── acme/
        └── org.md
```

**The invisible web (what the database knows):**

```
meeting ──mentions──▶ Alice      email ──mentions──▶ Alice
meeting ──mentions──▶ Acme       email ──mentions──▶ Acme
contract ──mentions──▶ Acme
meeting + email + contract ──same topic──▶ "Acme Onboarding" cluster
```

Five pages. Seven threads. Zero duplication.

---

## "Show me everything about Acme"

This is the payoff question. Notice that **no folder contains all three
documents** — the meeting is in `meetings/`, the email in `emails/`, the
contract in `docs/`.

The system doesn't search text for the word "Acme" (slow, error-prone).
It asks the database: *"give me every page whose threads point at the
Acme page"* — one indexed query, milliseconds:

```
1. Acme onboarding kickoff   (meeting, Jun 8)
2. Re: onboarding — Stripe   (email,   Jun 9)
3. Acme services contract    (doc,     Jun 10)
```

The "everything about Acme" view is **never stored anywhere**. It's
computed fresh every time from the threads. That's why it can't go stale
and can't drift out of sync.

---

## Every night — the janitor runs

While you sleep:

- **Topics are recomputed.** As content accumulates, vague groups split
  into sharp ones ("Acme misc" becomes "Onboarding" + "Payments").
- **Topic names are refreshed** (a small AI suggests a 2-4 word label
  from samples — naming only, nothing else).
- **Old claims fade.** A fact nobody has confirmed in 6 months drops
  from high confidence to medium to low.
- **Contradictions are flagged, never resolved.** If a new email says
  "actually we'll use Adyen, not Stripe", both emails get marked as
  conflicting and land in an *Open Questions* list. A human (or a recorded
  decision) settles it. The system never silently picks a winner.

---

## Week two — the briefing layer

Once ~10 Acme documents share the onboarding topic, a bigger AI is asked
to write a **synthesis** — but under strict rules:

```markdown
# Pattern: Acme onboarding is blocked on payments provider choice

Stripe was agreed in the kickoff [meeting Jun 8], then reversed
[email Jun 9 → contradicted by email Jun 15]. Contract signed [doc Jun 10].
Open: final provider decision.

Sources: [meeting-uuid], [email-uuid], [email2-uuid], [contract-uuid]
```

Every sentence must point at a source page. If you deleted this synthesis,
the system could regenerate it from the originals. It's a **cache of
conclusions**, never a source of truth. When new Acme documents arrive,
it's marked stale and rewritten.

So the wiki ends up with two kinds of pages:

| | Ground truth pages | Synthesis pages |
|---|---|---|
| Made by | format conversion (no AI) | AI, forced to cite |
| Content | verbatim words from the source | conclusions with footnotes |
| If wrong | can't be — it's a copy | regenerate from ground truth |
| Editable | never (replaced via supersession) | rebuilt automatically |

---

## How an agent answers a question

You ask Donna: *"What's the status of Acme onboarding?"*

1. **Resolve** — "Acme" → the Acme page.
2. **Gather** — one query pulls every page threaded to Acme; a fingerprint
   search adds anything topically related the threads missed.
3. **Prioritize** — a signed contract outranks a chat message; a decision
   outranks an email (there's a fixed trust ladder for every page type).
4. **Read** — only the top handful of pages are actually opened.
5. **Answer with receipts** — *"Contract signed Jun 10. Payments provider
   contested: Stripe (Jun 9) vs Adyen (Jun 15) — unresolved, flagged in
   Open Questions."* Every claim links to a page; every page links to its
   raw source.

The agent never answers from memory. It answers from pages it can show you.

---

## Why anyone (human or AI) can write to it without ruining it

Every write — from a connector, a coding agent, or a person — goes
through the same gate:

- Page type must be one of 12. No inventing new ones.
- Required fields per type (a decision **must** cite its evidence; a doc
  **must** declare what kind of doc it is). Missing → rejected.
- The last line **must** say where it came from. Missing → rejected.
- Existing pages are **never edited**. To change a decision, you write a
  new page that says "this supersedes the old one" — both stay, the chain
  is the history.

> *Why so strict:* a wiki everyone writes to degrades by default. The
> gate is what makes page #10,000 as trustworthy as page #1.

---

## The whole thing in four sentences

1. Every source document is kept **word-for-word**, with a fact sheet on
   top and a receipt at the bottom.
2. Simple rules (email matching, not AI) tie every document to the
   **people, companies, and projects** it involves, and math groups
   documents into **topics**.
3. AI is only allowed at the edges: filling one menu field, naming
   topics, and writing **summaries that must cite their sources** and are
   thrown away and rebuilt when stale.
4. Agents answer questions by **querying the threads**, reading the few
   pages that matter, and showing receipts — so the answer is only ever
   as wrong as the source documents themselves.

---

## See also

- [`00b - design-debate-qa.md`](./00b%20-%20design-debate-qa.md) — the
  design debate behind this narrative: the three-planes model, the five
  foundational Q&As with pushbacks, the trust-tier table, and the open
  issues list.
- [`00c - field-comparison.md`](./00c%20-%20field-comparison.md) — how
  this design measures against existing context-layer systems (Zep,
  Mem0, Hindsight, GraphRAG) and research, with a ranked improvement
  list.
- [`00d - connective-tissue-walkthrough.md`](./00d%20-%20connective-tissue-walkthrough.md) —
  end-to-end mechanics of extraction, resolution, clustering, edges,
  and `_index.md`/`_log.md` generation, with built-vs-designed markers.
- [`00e - end-to-end-example.md`](./00e%20-%20end-to-end-example.md) —
  step-by-step worked example with a diagram per step: the full write
  pipeline building the silver layer, then the retrieval agent
  answering a question through the P9 API.
- [`00f - silver-completion-plan.md`](./00f%20-%20silver-completion-plan.md) —
  the master end-to-end plan to complete the silver layer: 7 phases
  (cleanup → Living Source → connectors → cluster continuity → P9 API
  with hybrid retrieval → vault + rebuild → maintenance + eval), with
  per-phase tests, the pushback ledger, risks, and a ~3-week timeline.
- [`00g - mcp-implementation-guide.md`](./00g%20-%20mcp-implementation-guide.md) —
  educational MCP tutorial, theory + practice: protocol architecture
  (host/client/server, JSON-RPC, primitives, lifecycle, transports,
  OAuth 2.1), how the industry implements it (github-mcp-server,
  FastMCP idioms, design rules), and the Cortex MCP server applied
  end-to-end with code, client configs, tests, and flow diagrams.
- [`00h - ask-donna-roadmap.md`](./00h%20-%20ask-donna-roadmap.md) —
  the critical-path cut of 00f: six steps, ~7 working days, from
  today's code to asking questions about ongoing projects through
  the MCP server with cited answers; everything else explicitly
  deferred with reasons.
- [`conversations.md`](./conversations.md) — raw running transcript of
  the design sessions these docs were distilled from (digest debate,
  duplication, Living Source Policy, field comparison, connective
  tissue, scope-vs-mention, bronze↔silver storage).
- [`00 - vision.md`](./00%20-%20vision.md) — the formal vision doc.
