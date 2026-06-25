# Design Debate — Q&A on What the Silver Layer Really Is

Captured from a design session (2026-06-10). Five foundational questions,
answered with positions, examples, and honest pushbacks. Companion to
[`00a - how-it-comes-together.md`](./00a%20-%20how-it-comes-together.md)
(plain-English narrative),
[`00c - field-comparison.md`](./00c%20-%20field-comparison.md)
(design vs existing systems & research),
[`00d - connective-tissue-walkthrough.md`](./00d%20-%20connective-tissue-walkthrough.md)
(plane-2 mechanics end to end), and
[`00 - vision.md`](./00%20-%20vision.md).

---

Good reset. Let me anchor the debate on one mental model first: the cortex has three planes — (1) ground truth (verbatim bodies + provenance), (2) connective tissue (edges, clusters, entity refs, scope), (3) derived surface (synthesis docs + indexes + views). The design rule that makes the whole thing trustworthy is: plane 3 may only cite plane 1, never replace it. Now your questions:

1. Full content, altered for LLM understanding? Half agree. Split "altered" into two things:

Deterministic normalization — yes, already there: adapter/OCR → uniform markdown, frontmatter as structured metadata, Source footer. That IS the LLM-friendly altered form.
LLM rewriting of the body — no, and I'd fight hard here. The verbatim body is your court of record; rewrite it and you lose the anti-hallucination guarantee and the audit trail. The real gap you're sensing: a 90-min raw transcript is verbatim but unreadable for an agent. The answer is augmentation, not alteration — add a tldr/key-points block in frontmatter (HaikuFitter already has the hook), plus sections/summaries (P0.15) and synthesis docs on top. Body stays sacred; everything digestible sits beside it with citations.
2. Generated support documents? Yes — three kinds, all derived: spawned curated rows (person/org/concept), Narrio's CortexPattern/CortexNarrative (cluster + scope syntheses), and _index.md/_log.md navigation files. The contract that keeps them safe: author=agent, confidence, staleness tracking, mandatory sources, and full rebuildability. If a synthesis doc can't be deleted and regenerated from plane 1, it's designed wrong.

3. Hierarchical structure for fast agent iteration? Yes, but I'll push back on the emphasis. It's a hierarchy plus a graph plus indexes, and for the vast majority of questions agents should NOT walk the tree — Postgres is the fast path (ANN search, entity_refs GIN containment, cluster/temporal filters). The folder tree + _index.md/_log.md serve three things: human/Obsidian legibility, agent exploration when the question is vague ("what's going on with Acme?"), and cold-start orientation. Treat tree-walking as the browse mode, search as the answer mode. Note: _index.md regeneration is still unbuilt (P9) — so this axis is currently theoretical.

4. Strict rules for externally-generated docs? Exactly — that's Path 1 Strict: every write through the MCP API → linter (13 reject codes) → closed vocab → Pydantic-locked extensions → provenance footer, with linter_check dry-run so coding agents validate before committing, and plugin/CLI/pre-commit blocking stray file edits. My pushback: none of that enforcement surface exists yet, and ironically your own resolver spawn path already bypasses the linter today. If write discipline is the core invariant of the wiki, P9 + linter-everywhere should outrank any new write-side feature.

5. Continuous maintenance? Yes, and the skeleton exists: nightly recluster+rename, R6 resynth, R8 confidence decay, R7 contradiction detection, Narrio staleness cascade, orphan reaping, rebuild-from-files. Two pushbacks: (a) most of these are TODO stubs — today only reclustering runs; (b) there's a missing maintenance primitive nobody planned: curated-entity merge. Two "Acme" orgs spawned from acme.com and acme.io, or one person under two emails, will happen on day one of real data, and there's no merge/redirect flow in the spec. Continuous revision must also respect R1 — jobs may only touch derived fields (cluster, confidence, reverse edges) and derived docs, never ground-truth bodies.

Net: your five instincts match the design. The honest tension is sequencing — items 4 and 5 (enforcement + maintenance) are the actual moat of a trustworthy wiki, and they're the least-built parts.

## The mission, restated

> The silver layer is a post-processing phase of the bronze raw data.
> Its scope is to create a base foundation of correlated, connected
> knowledge that stands as the brain of the multi-agent system.
> Multiple sources (emails, deals, documents, meeting transcripts) are
> helpful alone but not as powerful as being correlated and connected.
> The approach: a Wiki Filesystem, aggregating and connecting
> information accurately.

## The mental model — three planes

The whole design hangs on one separation:

| Plane | Contents | Made by | Mutability |
|---|---|---|---|
| **1. Ground truth** | verbatim bodies + provenance footers | format conversion, no LLM | immutable (R1); changed only via supersession |
| **2. Connective tissue** | edges, entity refs, clusters, scope | deterministic rules + statistics | maintained by jobs |
| **3. Derived surface** | synthesis docs, indexes, views | LLM (citation-bound) + regeneration | disposable, rebuildable |

**The rule that makes the wiki trustworthy: plane 3 may only cite
plane 1, never replace it.** Facts flow only through deterministic
paths; LLMs only summarize what is already stored and must point back
at it.

---

## Q1 — Don't we need the full content, but altered so the LLM understands it better?

**Position: half agree. Split "altered" into two different things.**

- *Deterministic normalization* — yes, and it already exists: adapter/OCR
  → uniform markdown, frontmatter as structured metadata, Source footer.
  That IS the LLM-friendly altered form.
- *LLM rewriting of the body* — no. The verbatim body is the court of
  record; rewrite it and you lose the anti-hallucination guarantee and
  the audit trail.

The real gap behind the question: a 90-minute raw transcript is verbatim
but *unreadable* for an agent. The answer is **augmentation, not
alteration** — a `tldr`/key-points block in frontmatter (HaikuFitter
hook), sections + summaries for long docs (P0.15), and synthesis docs on
top. Body stays sacred; everything digestible sits beside it with
citations.

### Step-by-step (Fathom call "Acme onboarding kickoff")

```
Step 1  Fathom webhook → raw JSON saved to bronze, untouched
        WHY: evidence locker — everything downstream is re-derivable
Step 2  Adapter renders JSON → markdown transcript (deterministic, no LLM)
        WHY: format change only, like docx → pdf; words identical
Step 3  Template staples a cover sheet: frontmatter (attendees, duration,
        cluster_name) + verbatim transcript + "Source: fathom://meeting/rec-abc"
        WHY: agent parses the cover sheet in ~50 tokens instead of reading
        30k tokens of transcript; the Source line makes every page provable
Step 4  (augmentation) Haiku writes tldr + key decisions INTO frontmatter,
        Pydantic-locked. Body untouched.
        WHY: digestibility without destroying the record. If the tldr is
        ever wrong, the verbatim body below it is the proof and the fix.
```

The day an agent answers "we agreed X" and the client disputes it, you
scroll past the frontmatter and the literal words are there.

---

## Q2 — Are we generating additional documents that serve as support for agent reasoning?

**Position: yes — three kinds, all derived.**

1. **Spawned curated rows** (person / org / concept stubs) — created
   deterministically by the resolver, `confidence=medium` until a human
   verifies.
2. **Synthesis docs** — `CortexPattern` (cluster-anchored conclusion) and
   `CortexNarrative` (per-scope wiki page). LLM-written, citation-bound.
3. **Navigation files** — `_index.md` / `_log.md` per folder, regenerated
   mechanically.

The contract that keeps them safe: `author=agent`, confidence tier,
staleness tracking, mandatory sources, full rebuildability.

**Litmus test: delete any derived doc → regenerate it from plane 1 →
identical. If not, it is holding unsourced claims and degrading trust.**

### Step-by-step

```
Step 1  Pipeline sees host=alice@acme.com → no Acme org row exists →
        SPAWNS org "Acme" (author=donna, source=cortex://spawn/…, conf=medium)
        WHY: the meeting needs something to point at; medium confidence
        flags "machine-made, human hasn't verified"
Step 2  Meeting row gets entity_refs=[alice, bob, acme]
        WHY: edges, not copies — the meeting lives once, views are queries
Step 3  After ~10 Acme artifacts share one cluster, synthesis runs:
        CortexPattern "Acme onboarding blocked on payments integration"
        sources=[meeting1, email4, ticket9]
        WHY: agents shouldn't re-read 10 docs per question; the pattern is
        the cached conclusion WITH citations — verifiable and rebuildable
Step 4  CortexNarrative compiles the scope wiki page from patterns
        WHY: one briefing page an agent (or human) reads first
```

---

## Q3 — Are we building a hierarchy so agents iterate fast through the filesystem via index logs?

**Position: yes, but with a pushback on emphasis.** It's a hierarchy
**plus a graph plus indexes**, and for the vast majority of questions
agents should NOT walk the tree. Postgres is the fast path (vector ANN,
`entity_refs` GIN containment, cluster/temporal filters). The folder tree
+ `_index.md`/`_log.md` serve three things:

1. Human/Obsidian legibility — humans audit the same structure agents use.
2. Agent *exploration* when the question is vague.
3. Cold-start orientation.

**Search answers questions; the tree builds orientation.**

### Step-by-step — "What's happening with Acme onboarding?"

```
ANSWER MODE (default, fast):
  1. Resolve "Acme" → acme_uuid (alias lookup)
  2. SQL: entity_refs @> [acme_uuid] AND occurred_at > now()-30d  (GIN, ms)
  3. Vector ANN on the question embedding for anything the refs missed
  4. Load top-5 bodies only → synthesize with citations
  WHY: 3 indexed queries beat walking any tree; bodies fetched only
  for the winners

BROWSE MODE (vague questions, cold start):
  1. Open clients/acme/_index.md → grouped catalog (decisions, recent
     meetings, tickets by status)
  2. Open _log.md → "what changed this week" as an append-only feed
  3. Descend only into what looks relevant
  WHY: when the agent doesn't know what to ask, a curated table of
  contents beats 20 blind searches
```

Key structural fact: "everything about Acme" is **never stored** — no
folder contains all the Acme documents. It's computed fresh from
`entity_refs` every time, so it can't go stale and can't drift.

---

## Q4 — If coding agents generate new docs, do they need strict rules so the wiki doesn't degrade?

**Position: exactly — that's Path 1 Strict.** Every write — connector,
human, coding agent — goes through the same gate: MCP API → linter (13
closed reject codes) → closed vocabularies (12 types, 9 edges, 16
doc_types) → Pydantic-locked extensions → provenance footer. Plus
`linter_check` dry-run so agents validate *before* committing, and
plugin/CLI/pre-commit hooks blocking stray file edits.

### Step-by-step — a coding agent records an ADR

```
Step 1  POST cortex.linter_check(payload)            ← dry-run, nothing written
Step 2  REJECT: MISSING_REQUIRED_EXTENSION — decision needs context_sources
        WHY: an ADR with no cited evidence is an opinion, not a decision
Step 3  Agent adds context_sources=[meeting_uuid, ticket_uuid], retries
Step 4  REJECT: MISSING_SOURCE_FOOTER — body must end "Source: manual://adr/0042"
        WHY: every doc must be traceable to its origin, even agent-made ones
Step 5  Passes → cortex.create_entity writes it; repository atomically
        back-writes applied_in on the cited meeting + ticket
Step 6  Agent later tries to EDIT the ADR body → REJECT (R1 immutable).
        Correct path: new ADR with supersedes=[old]
        WHY: edits rewrite history silently; supersession chains preserve it
```

Why closed vocab everywhere: every ad-hoc type/edge is a new layout
agents must learn and a query that breaks. **Rejection at the gate is
cheap; cleaning a polluted wiki is not.** The gate is what makes page
#10,000 as trustworthy as page #1.

**Pushback:** the enforcement surface (MCP API, dry-run, hooks) is P9 —
not built yet. And the resolver spawn path currently bypasses the linter,
which is the first internal violation of this rule. If write discipline
is the core invariant, P9 + linter-everywhere outranks any new
write-side feature.

---

## Q5 — Does the cortex need continuous maintenance of connections and correlations?

**Position: yes — and the nightly cycle is the design.** Hard rule:
maintenance touches only planes 2 and 3 (clusters, confidence, reverse
edges, derived docs). **Ground-truth bodies are never mutated** — that's
what lets you trust a wiki that rewrites itself every night.

### The nightly cycle

```
02:00  recluster per scope (HDBSCAN) → topics re-form as data grows
       WHY: June's "misc" cluster becomes July's "Payments Integration" —
       taxonomy must follow the data, not a hand-made folder list
02:10  Haiku renames changed clusters; cluster UUIDs stay stable (uuid5)
       WHY: names refresh, references don't break
02:20  staleness cascade: new entity in cluster → Pattern marked stale →
       Narrative marked stale → resynth queued (R6)
       WHY: a briefing doc that lags reality is worse than none
02:30  confidence decay (R8): unconfirmed claims fade high→medium→low
       WHY: "we use Stripe" from January shouldn't outrank June's reality
02:40  contradiction sweep (R7): email says Stripe, newer says Adyen, no
       supersedes link → both flagged → Open Questions. NEVER auto-merged.
       WHY: the system detects conflicts; humans decide truth
02:50  hygiene: orphan body files reaped; Postgres index rebuildable
       from SilverStorage files
```

**Pushbacks:** (a) today only reclustering + renaming + orphan reaping
run; the cascade, decay, and contradiction sweep are designed but
unbuilt. (b) A maintenance primitive is missing entirely: **curated-entity
merge**. Two "Acme" orgs spawned from `acme.com` and `acme.io`, or one
person under two emails, will happen on day one of real data — there is
no merge/redirect flow in the spec yet.

---

## Which mechanism does what — the trust-tier table

| What | Mechanism | LLM involved? |
|---|---|---|
| Body content | verbatim from source; format normalized (adapter/OCR → markdown) | No |
| Frontmatter facts (attendees, dates, thread_id) | copied from provider metadata | No |
| Frontmatter gaps (`doc_type` on a PDF, tldr) | Haiku fills, Pydantic-locked to closed vocab | Yes — fills only, cannot invent fields |
| Entity extraction | provider metadata first (emails, domains — deterministic, conf 1.0); GLiNER optional for body mentions | No — GLiNER is a small local NER model, not an LLM |
| Entity resolution ("same Alice?") | deterministic: email match → alias match → spawn | No |
| Edges + reverse edges | written at ingest, atomic transaction | No |
| Clustering | embeddings + HDBSCAN — statistical | No (cluster *naming* is Haiku — cosmetic only) |
| Synthesis docs (patterns, narratives) | LLM, must cite sources, rebuildable | Yes |
| Folders / `_index.md` / `_log.md` | deterministic resolvers + regeneration | No |

Three trust tiers, not two: **deterministic** (provider facts, rules),
**statistical** (embeddings, clustering — reproducible math, no
judgment), **LLM** (summaries and labels only, always citation-bound or
vocabulary-locked).

LLM-based entity extraction was deliberately rejected: non-deterministic,
expensive, hallucinates matches. ~90% of entity signal comes free from
provider metadata (Fathom gives attendees, Gmail gives sender/recipients).

---

## The design, compressed to one sentence each

1. Every source document is kept **word-for-word**, with a fact sheet on
   top and a receipt at the bottom.
2. Simple rules (email matching, not AI) tie every document to the
   **people, companies, and projects** it involves; math groups documents
   into **topics**.
3. AI is allowed only at the edges: filling one menu field, naming
   topics, and writing **summaries that must cite sources** and are
   rebuilt when stale.
4. Agents answer by **querying the threads**, reading the few pages that
   matter, and showing receipts — the answer is only ever as wrong as the
   source documents themselves.

---

## Open pushbacks from this session (tracked, not yet resolved)

| # | Pushback | Status |
|---|---|---|
| 1 | Scope promotion (`client_id`/`project_id`) is policy-correct but depends on the unbuilt MCP API — until P9, everything clusters at workspace root, and per-scope narratives have exactly one scope | open |
| 2 | Sequencing: three workstreams (P0.15 long docs, P9 MCP API, Narrio synthesis PRs) all claim "next"; recommendation is P9 first — nothing can read the layer yet | open |
| 3 | Resolver `_spawn` bypasses the linter — spawned rows land unchecked | open, cheap fix |
| 4 | `GLiNERExtractor` reads `entity.body_md`, which no longer exists post-P0.14 (FileField) — latent AttributeError when first enabled | open, cheap fix |
| 5 | No curated-entity merge/redirect flow (duplicate orgs/persons inevitable with real data) | open, needs spec amendment |
| 6 | `_index.md`/`_log.md` regeneration unbuilt (P9) — the browse axis is theoretical today | open |
| 7 | Maintenance jobs beyond reclustering (R6 cascade, R8 decay, R7 contradictions) are designed but unbuilt | open |
| 8 | `storage.py` (`LocalFSStorage` + Protocol) coexists with the actual SilverStorage (FileField + default_storage) — mark it explicitly P9+ to avoid two "storage truths" | open |
| 9 | Temporal duplication of living sources — a growing email thread / edited Drive·Notion doc re-ingests with a new `content_hash`, creating a new immutable row that contains the previous version's content. Costs: retrieval pollution (top-k filled with versions of one thread), R7 false contradictions (version N vs N−1), cluster distortion (near-duplicate embeddings) | proposed resolution below — Living Source Policy; spec amendment pending |
| 10 | `_index.md` regeneration design decisions unmade (see `00d`): (a) "regenerate on every write" = write amplification — needs dirty-flag + coalesced flush, mirroring #9's debounce; (b) `_index.md` must list heads only (`superseded_by IS NULL`) or browse mode re-imports the duplication #9 solved; (c) `_log.md` is shippable pre-P9 — append-only, no grouping logic, answers "what changed this week" for free | open — decide before P9 builds the vault renderer |
| 11 | Resolver never links curated entities to each other — `_spawn_person` leaves `employer_org_id=None` even when person + org are spawned from the same email (`alice@acme.com` → Alice, `acme.com` → Acme). Both connect to the document, not to each other; "who works at Acme?" only works via the indirect join through shared docs. Deterministic fix at spawn/resolve time: domain of `primary_email` matches an org's `email_domains[]` → set `employer_org_id` (+ `related` edge). Same trust tier as the resolver, no LLM | open, cheap fix (same class as #3/#4) |
| 12 | Bronze overwrite-on-retry contradicts the evidence-locker claim — every connector task does `delete` + `save` on the same `storage_key` at re-ingest, so bronze is *latest-snapshot-per-item*, not immutable. After a Living Source supersession (#9), the ancestor's silver body survives but its bronze blob is overwritten — the old row's `bronze_storage_key` points at the *new* version's content, and the chain's provenance is silently broken. If bronze is the court of record, re-ingesting sources need versioned bronze keys (hash- or timestamp-suffixed); one-shot sources (Fathom) are unaffected | open, needs spec amendment (pairs with #9) |
| 13 | Author-volume pollution — a well-meaning or abusive author (human or agent) producing high volumes of *rule-compliant* low-value pages breaks nothing at the gate but distorts clusters and burns retrieval slots: #9's failure shape with an author instead of a living source as the generator. No per-author rate limits or trust weighting in the spec. Heads-only retrieval + authority ranking + R8 decay absorb most of it; add policy knobs (per-author quotas, author-tier retrieval weighting) only when observed in real data, not preemptively | open — deliberate wait-for-evidence |
| 14 | No similarity threshold at write-time cluster assign — `HDBSCANClusterer.assign()` takes the best centroid *unconditionally*, so a document about a genuinely novel topic is shoved into whatever existing cluster is least-unlike it and stays mis-filed until the nightly HDBSCAN pass. Fix: minimum-cosine floor (below it → `cluster_id=None`, wait for nightly) — makes write-time assignment as honest as the batch pass | open, cheap fix (same class as #3/#4/#11) |
| 15 | Cluster identity is run-deterministic, not semantically continuous — `uuid5(scope_ns, str(label))` guarantees *same label → same UUID*, but HDBSCAN's integer labels are arbitrary across runs: the same pile of documents can get a different label (→ different cluster UUID) tomorrow. Rows survive (remapped wholesale nightly), but anything **anchored** on a cluster UUID — `CortexPattern` is cluster-anchored by design — can be orphaned by pure label churn. The 00d "identities persist across recluster" claim is stronger than the code guarantees. Fix: centroid-matching across runs (map new clusters to old UUIDs by nearest-centroid overlap; mint fresh UUIDs only for genuinely new topics). **Must land before Narrio PR 2 builds patterns on cluster anchors** | open — blocks Narrio PR 2 |

---

## Pushback #9 — proposed resolution: the Living Source Policy

*(2026-06-10, follow-up session.)* Key realization: both primitives
already exist. The `source` field is already a stable logical URI per
living thing (`gmail://thread/<id>`, `drive://file/<id>`), and R3
supersession chains *are* version history. The bug is that dedup is
one-tier (`(workspace, content_hash)` unique constraint only) when it
should be two-tier. The storage cost was never the problem (text is
cents); the agent's context window, the Open Questions signal-to-noise,
and cluster geometry are.

**Rule 1 — two-tier dedup at ingest.** Lookup `(workspace, source)`
before insert:

| Lookup result | Action |
|---|---|
| same `source`, same `content_hash` | `DUPLICATE` — return existing id (replay guard, unchanged) |
| same `source`, different hash | new immutable row with `supersedes=[old head]` — a **version**, not a duplicate |
| no match | genuinely new entity |

No special-casing "living" vs "dead" sources: a Fathom meeting never
changes at the source, so its chain never grows past length 1.

**Rule 2 — answer mode reads heads only.** Every agent retrieval path
(vector ANN, `entity_refs` GIN, cluster membership) defaults to
`superseded_by IS NULL` (partial indexes make it free). Ancestors stay
readable by id / chain-walk — which is exactly what the
"diff initial proposal vs final offer" eval needs.

**Rule 3 — ancestors keep their words, lose their weight.** On
supersession: verbatim body file kept (R1, audit, rebuild — intact);
embedding nulled and row evicted from clusters. Plane-2 operation, so
maintenance is allowed to do it. Fixes retrieval pollution and cluster
distortion in one move; bonus: reclaims the 1.5 KB vector, the actual
largest per-row storage.

**Rule 4 — R7 skips supersession chains.** Versions are definitionally
not contradictions. Already implied by the reject code's own wording —
`IMPLICIT_CONTRADICTION` = "contradicting newer Silver *without*
supersedes" — auto-supersession makes thread evolution legal by
construction.

**Rule 5 — supersession triggers the R6 staleness cascade.** A Pattern
citing a superseded uuid stays *valid* (citation resolves) but goes
*stale* → resynth queued against the new head.

**Rejected alternatives:** delta storage for ancestors (breaks
rebuild-from-silver into chain reassembly — wrong resource optimized);
LLM-merging versions into one canonical page (same four failure modes
as the digest debate); mutating the row in place (breaks R1).

**Operational knob:** chatty threads (webhook per reply) produce long
chains — debounce thread re-ingest at the connector (at most once per
few hours, or on quiescence). Policy stays clean; the connector blinks
slower.

**Cost of the fix:** one dedup lookup change in `pipeline.py`, one
default query filter, one maintenance behavior on supersession, two
rule clarifications (R7 chain-skip, R6 trigger). No new models, no new
vocab, no LLM in the path.

---

## Bronze ↔ Silver storage debate — resolution (2026-06-10, evening session)

*(Raw transcript in [`conversations.md`](./conversations.md).)*
Question: should bronze↔silver duplication be minimized by (1) running
OCR at ingest and storing markdown bronze-adjacent, (2) making silver
bodies pointers into bronze, (3) structuring bronze with the wiki
folder hierarchy? **Decision: adopt (1), reject (2) and (3) — the
deliberate bronze↔silver duplication stays.**

### Adopted — OCR/extraction at connector time, bronze-adjacent derived sidecar

The connector task runs OCR/extraction once and stores
`{id}.extracted.md` beside `{id}.json` (Drive's `.txt` sidecar already
half-does this). Wins: OCR runs once per blob instead of on every
pipeline pass through `_body_for()`; rebuild-from-bronze becomes cheap;
"re-extract with a better engine" becomes a bronze-side maintenance
job; the pipeline becomes text-in, deterministic.

**Discipline rule: the sidecar is NOT bronze.** It is derived and
regenerable (a different OCR engine yields different markdown). Stored
adjacent, labeled derived, never the court of record — the raw blob
stays the dispute anchor. Re-OCR → new `content_hash` → a supersession
version under the Living Source Policy (#9); consistent by
construction.

Implementation notes: connector tasks own extraction; `pipeline.py
_body_for()` reads the sidecar when present and falls back to inline
OCR otherwise; kill Drive's within-bronze double-store (`exported_text`
lives both inside the `.json` and as the `.txt` sidecar — store the
export once).

### Rejected — silver bodies as pointers into bronze

Decisive, found in code: every connector overwrites the same bronze key
on retry/re-ingest, so bronze is mutable (see pushback #12). Pointing
immutable silver rows (R1) at mutable blobs means a re-ingested thread
silently changes superseded rows' bodies — the audit trail walks.
Fixing it requires versioned bronze keys, i.e. rebuilding silver's
immutability inside bronze under another name. Independent breaks:
(a) canonicality inversion — spec §14 locks "files = canonical,
Postgres = derived index"; bodies-in-bronze + frontmatter-only-in-
Postgres means the canonical page exists nowhere as a file and rebuild
degrades to a full pipeline re-run; (b) the wiki tree must be real
files for Obsidian + browse mode + `_index.md` — pointer stubs kill
browsing, and the P9 vault renderer copying text back in merely
relocates the duplication; (c) savings ≈ 10 KB of text per artifact —
cents; the real duplication costs were already fixed by #9.

**Noted for the record:** if the byte-level overlap (sidecar ≈ silver
verbatim section, post-adoption) ever matters, the correct fix is
content-addressed body blobs — store the text once keyed by hash, both
layers reference it. Dedupe the bytes, never the model. Currently
over-engineering for single-digit GB.

### Rejected — bronze structured by the wiki folder hierarchy

Bronze keys must be computable at **webhook time** from
`(workspace, provider, item_id)` — that's what makes retry-overwrite
idempotent and `bronze_storage_key` stable. The wiki path is computed
at **pipeline time** from type resolution + Haiku fit + scope — and
scope changes (promotion is a deliberate post-P9 act, pushback #1).
Hierarchy-keyed bronze means every scope promotion physically moves
blobs and rewrites every pointer: the evidence locker becomes mobile,
same crime as mutable. Scope-vs-mention applied one layer down — the
wiki tree is keyed by scope (a silver concern); bronze's stable key is
provider identity. Two layers, two organizing keys, on purpose.

---

## Derived vs authored documents — the two populations (2026-06-11 session)

*(Raw transcript in [`conversations.md`](./conversations.md).)*
Questions: does the system generate adjacent valuable documents
(narratives, decisions) beside the ones humans/agents author? And do
authored docs go through embedding/clustering/folder placement — with
or without generation guidelines?

### The four system-generated derived kinds

All share one contract — **delete it, regenerate it from plane 1, get
the identical document**:

| Kind | What | Generator | Status |
|---|---|---|---|
| Curated stubs | `people/alice.md`, `clients/acme/org.md` | resolver, deterministic | ✅ built |
| `CortexPattern` | cluster-anchored conclusion, mandatory `sources=[uuids]` | Haiku `PatternExtractor` | 📐 Narrio PR 2 |
| `CortexNarrative` | per-scope briefing page compiled from patterns | Sonnet `NarrativeCompiler`, lazy | 📐 Narrio PR 3 |
| `_index.md` / `_log.md` | navigation projections | mechanical renderer | 📐 P9 |

Trigger chain (specced in ADR-0001 / `06-narrio-adoptions.md`): cluster
reaches ~10 docs → patterns extracted citation-bound → narrative
compiled per scope → new arrival flips `stale=True` → resynth queued
(R6 cascade).

### The hard boundary — the system never generates a `decision`

`decision` is authority **100**, above `doc:contract` 95 — a rank
justified only because a decision is an *original act of commitment by
someone accountable*. An LLM auto-promoting "sounds like they agreed
on Stripe" into a decision row makes the wiki's most authoritative
page type an LLM interpretation — the digest debate's failure mode at
the top of the trust ladder. Division of labor: the system **detects**
(Pattern surfaces the candidate with citations; R7 flags
contradictions into Open Questions); the author **asserts** (human or
agent-on-instruction records the decision through the gate, which
demands `context_sources` on pain of `INSUFFICIENT_EVIDENCE`).

| | System-derived | Externally-authored |
|---|---|---|
| Nature | cache of conclusions | **new ground truth** — original assertion |
| When wrong | regenerate from plane 1 | supersede (R1 — never edit) |
| Deletable | freely — rebuildable | never — it's evidence |
| Litmus | rebuildable from plane 1 alone → plane 3 | not rebuildable → plane 1 |

### One write path for everyone — and no topical folders

An authored doc enters via the MCP API (`cortex.create_entity`,
`source=manual://…`, `author=human|agent`) and walks the same pipeline
steps 2-11 as a connector doc — including **embed + cluster assign**
and folder placement. The author never picks a folder, and there are
no topical folders to pick (no `tech/`, no `engineering/`): the tree
is scope + type + date, computed by the resolver; *aboutness* is the
cluster's job (emergent, reshaped nightly). A hand-made topic taxonomy
was explicitly rejected — stale the day after creation, and every
author files differently. Folder = ownership; cluster = aboutness; the
author controls neither directly.

### "No generation guidelines" — resolved as: free content, strict shape

The gate never judges value (no editorial review, no approval queue);
it enforces shape (closed vocab, required fields, evidence, footer, no
edits). Abuse analysis: rewriting/deleting history is impossible by
construction (R1 + supersession keeps both); forged high-authority
pages hit `INSUFFICIENT_EVIDENCE` + the R7 sweep; contradictions get
flagged to Open Questions, never auto-resolved; spam enters at its
honest authority rung (chat 30, journal 15) and decays via R8;
duplicates die on `content_hash`; every page is attributed via
`author` + provenance footer. **Because mutation is forbidden, the
worst possible abuse is additive noise — never subtraction of truth.**
The one residual gap — high-volume rule-compliant noise distorting
clusters and retrieval — is pushback #13, deliberately deferred until
observed.
