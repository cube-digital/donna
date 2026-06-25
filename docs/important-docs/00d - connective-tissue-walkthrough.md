# Connective Tissue Walkthrough — Extraction, Resolution, Clustering, Edges, and the Navigation Files

Captured from a design session (2026-06-10). Companion to
[`00a - how-it-comes-together.md`](./00a%20-%20how-it-comes-together.md),
[`00b - design-debate-qa.md`](./00b%20-%20design-debate-qa.md), and
[`00c - field-comparison.md`](./00c%20-%20field-comparison.md).
Question answered: **how do entity extraction, resolution, clustering,
edges, and `_index.md` / `_log.md` generation actually work — end to
end, with built-vs-designed markers?**

---

## The big picture — one row, four kinds of connection

When one artifact is written, it gets connected along four independent
axes, each made by a different mechanism with a different trust tier:

```
                       ┌──────────────────────────┐
                       │  CortexEntity (one row)   │
                       └──────────────────────────┘
   WHO/WHAT is it about?    WHAT topic?           HOW does it relate?        WHERE does it live?
          │                     │                       │                         │
    entity_refs[]          cluster_id             edges (9 types)           parent_path
    (deterministic         (statistical:          (sources, supersedes,     (deterministic
     email/domain match)    embedding+HDBSCAN)     contradicts + reverses)   folder resolver)
          │                     │                       │                         │
          └─────────────────────┴───────────────────────┴─────────────────────────┘
                                          │
                  _index.md + _log.md are PROJECTIONS of all four
                  (never sources of truth — regenerable from Postgres)
```

Discipline: **every arrow is written at ingest, atomically, by rules —
navigation files are computed *from* the arrows, never the reverse.**

---

## 1. Entity extraction — reading the envelope, not the letter

Two extractors chained via `CompositeExtractor` (dedupes on
`(type, email, domain, label)`):

- **`ProviderMetadataExtractor`** (deterministic, conf 1.0, always on).
  Never reads the body. Fathom gives attendees, Gmail gives
  sender/recipients, Drive gives the owner. Every email address → a
  `person` candidate; every non-public email **domain** → an `org`
  candidate (conf 0.9). The `_PUBLIC_EMAIL_DOMAINS` guard stops
  `alice@gmail.com` from spawning an org called "Gmail". This is the
  "~90% of entity signal is free" claim made concrete: the *envelope*
  carries the people and companies.
- **`GLiNERExtractor`** (statistical NER, optional, **off by
  default**). Small local model (`gliner_medium-v2.1`, not an LLM)
  that skims the body for `person/org/project/concept` mentions with
  spans + scores. Recall-recovery for what metadata can't see ("Bob
  from Initech" mentioned mid-transcript). ⚠️ Known bug (00b pushback
  #4): still reads `entity.body_md`, removed in P0.14 — latent
  `AttributeError` when first enabled.

---

## 2. Resolution — the receptionist with a rolodex

`DeterministicResolver` answers: *does this thing already have a page?*

| Type | Rule 1 (strong) | Rule 2 (fallback) | Else |
|---|---|---|---|
| person | `extensions.primary_email` exact match (lowercased) | label vs `cross_workspace_aliases[]` | spawn |
| org | domain ∈ `extensions.email_domains[]` | label vs aliases | spawn |
| project / concept | label vs aliases only | — | spawn |

No fuzzy matching, no LLM judgment → **no false merges, ever** (the
failure that silently corrupts Zep/Hindsight graphs), at the price of
under-linking ("Robert" vs "Bob" stay two people until merged — the
missing merge flow, pushback #5).

**Spawning**: first time `alice@acme.com` appears, the resolver creates
a stub — `author="donna"`, `source="cortex://spawn/<id>"`,
`confidence="medium"` ("machine-made, human hasn't verified"),
idempotent via synthetic `content_hash("person:alice@acme.com")`.
Every future artifact resolves to the *same UUID* — that UUID accretion
is the compounding effect: Tuesday's email points at Monday's Alice.
⚠️ `_spawn` bypasses the linter today (pushback #3) — first internal
violation of "every write through the gate".

---

## 3. Edges — the threads, and who ties them

- **`entity_refs[]` is the workhorse**: resolved UUIDs dropped into the
  row's array; the GIN index makes "everything about Acme" a
  millisecond containment query (`entity_refs @> '["<acme-uuid>"]'`).
  The Acme view is never stored — always computed.
- **Semantic edges** carry an invariant the repository enforces in
  **one Postgres transaction** — every forward edge writes its reverse
  onto the target row (`select_for_update` against concurrent writers):

| Forward | Reverse | Cardinality |
|---|---|---|
| `sources[]` | `applied_in[]` | append |
| `supersedes[]` | `superseded_by` | assign (1:1) |
| `contradicts[]` | `contradicts[]` | symmetric |

Why atomicity is the point: if an ADR cites a meeting but the meeting
never learns it was cited, the graph is silently one-directional and
"what came out of this meeting?" is unanswerable. The Living Source
Policy (pushback #9) plugs straight into `_assign_superseded_by` — the
same mechanism flips a superseded thread version out of answer mode.

---

## 4. Clustering — the tables at the party

Two rhythms:

- **At write (cheap, instant):** body sampled per-type (contracts keep
  endings/signatures, meetings keep late decisions), embedded with
  BGE-small, assigned to the **nearest existing centroid** by cosine —
  a dot product, no model run.
- **Nightly (the real clustering):** HDBSCAN per scope — clusters never
  cross `(workspace, client, project)` lines. HDBSCAN's arbitrary
  integer labels are mapped to **stable uuid5 ids** namespaced by
  scope, so June's "misc" splitting into July's "Payments Integration"
  doesn't break references — names refresh (Haiku, 5 samples, 2–4
  words, cosmetic only), identities persist. Noise points get
  `cluster_id=None` honestly.

⚠️ Caveats: (a) **cold start** — no centroids until a scope has ~5
embedded docs; (b) **pushback #1 bites hardest here** — nothing
promotes scope until P9, so everything clusters in one workspace-root
pot. The stale comment in `pipeline.py` step 5 (`client_id=None  # set
below once entity_refs resolved` — never set) is this gap wearing a
disguise.

---

## 5. Write pipeline order (CortexWriter.write)

**(1)** OCR/markdownify → **(2)** type resolve → **(3)** deterministic
frontmatter → **(4)** Haiku fit *only if* nav fields missing →
**(5)** embed + cluster assign → **(6)** folder placement →
**(7)** render body → **(8)** build row → **(9)** extract + resolve →
`entity_refs` → **(10)** linter gate → **(11)** repository persists
row + body file + all reverse edges atomically. The linter sits after
assembly and before persistence — rejection costs nothing.

---

## 6. `_index.md` + `_log.md` — the projections (designed, unbuilt)

100% spec, 0% code today (pushback #6). The contract (spec §9.1):

| File | What | Update rule |
|---|---|---|
| `_index.md` | catalog of folder children, **grouped by type + sub-discriminator** (docs by `doc_type`, tickets by `status`, meetings by recency) | regenerated on every write to the folder |
| `_log.md` | append-only event feed — one line per Cortex event | append, never rewrite |

The grouping is the intelligence: `_index.md` isn't `ls`, it's a
*briefing-shaped* table of contents — which is what makes browse mode
worth anything for an agent with a vague question.

Both files are pure plane-3 projections: all needed data already lives
in Postgres (`parent_path`, `type`, extensions, `occurred_at`). The
plan is a `vault_renderer.py` Celery task that walks `cortex_entities`,
renders `_index.md` per folder + `_log.md` per scope + entity `.md` per
row, git-commits per batch. Delete every `_index.md` → regenerate →
identical (the 00b Q2 litmus test holds by construction).

### Three design decisions the spec hasn't made (flag before P9 builds it)

1. **Write amplification.** "Regenerate on every write" = a 50-email
   day rewrites one `_index.md` 50 times — in Mode A (git vault), 50
   commits. Same medicine as the Living Source debounce: dirty-flag per
   folder, coalesced flush every N minutes. `_log.md` stays per-event
   (appends are free).
2. **Index meets supersession.** `_index.md` must list **heads only**
   (`superseded_by IS NULL`) or browse mode re-imports the duplication
   problem pushback #9 just solved. `_log.md` is the natural home of
   version history ("superseded by [[…]]").
3. **`_log.md` could ship before P9.** No grouping logic, no MCP API —
   just an append per pipeline write. Disproportionate value: "what
   changed this week" is the most common vague-browse question, and an
   append-only feed answers it with zero queries.

---

## Verdict

Of the four connection axes: two fully alive in code (`entity_refs`,
edges), one half-alive (clustering — runs, but cold-start +
single-scope), and the navigation layer that makes it all *legible* is
pure paper. Retrieval channels are commodity (00c catch-up list);
**deterministic connective tissue is not** — it's what Mem0/Zep build
with LLM extractors and then can't trust. The connective tissue exists;
the nervous system that lets an agent feel it (P9 read API + index/log
regeneration) is the unbuilt half. Same conclusion every thread
converges on: **P9 first.**
