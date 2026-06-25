# Field Comparison — Cortex vs Context-Layer Systems & Research

Captured from a design session (2026-06-10). Companion to
[`00a - how-it-comes-together.md`](./00a%20-%20how-it-comes-together.md) and
[`00b - design-debate-qa.md`](./00b%20-%20design-debate-qa.md).
Question answered: **how strong is the Cortex design against the real,
measured problems of existing context-layer / agent-memory systems —
and what should we improve?**

---

## Bottom line

**The write side is ahead of the field. The read side is behind it.**
Three-planes, verbatim ground truth, provenance, and the linter gate
solve problems the commercial systems are still bleeding from. The
retrieval path — single embedding ANN + `entity_refs` — is what the
field now explicitly calls an anti-pattern, and there is no eval
harness, so retrieval quality is currently unmeasured.

---

## The field, calibrated with independent numbers

| System | Architecture | LongMemEval (independent) | Self-reported |
|---|---|---|---|
| [Mem0](https://vectorize.io/articles/mem0-vs-zep) | vector + optional KG, LLM fact extraction at ingest | **49.0%** | 67–68% |
| [Zep / Graphiti](https://arxiv.org/abs/2501.13956) | temporal KG, bi-temporal fact validity windows, hybrid retrieval | **63.8%** | 90.2% |
| [Hindsight](https://venturebeat.com/data/with-91-accuracy-open-source-hindsight-agentic-memory-provides-20-20-vision) | 4 memory networks; TEMPR 4-channel retrieval + RRF + cross-encoder rerank | **91.4%** (top score) | — |

Findings that matter more than the leaderboard:

1. **Self-reported numbers collapse under independent eval** (Mem0
   68→49, Zep 90→64). Nothing is trusted without a harness.
2. **[Letta showed](https://www.letta.com/blog/benchmarking-ai-agent-memory)
   a plain filesystem + gpt-4o-mini agent scores 74% on LoCoMo**,
   beating Mem0's graph variant. Their conclusion: *memory is more
   about how agents manage context than the retrieval mechanism* —
   direct validation of the wiki-filesystem approach.
3. **Hard categories are brutal for everyone**: multi-hop reasoning
   drops to ~26% and temporal reasoning to 7–45% on EverMemBench;
   LoCoMo high-scorers fall to 40–60% on agentic multi-session tasks
   (MemoryArena). Nobody has solved this; set expectations accordingly.
4. **Production retrieval consensus**: naive vector-only fails ~40% of
   retrievals; the standard stack is BM25 + dense in parallel → RRF
   fusion (k=60) → cross-encoder reranker (15–40% precision lift);
   [contextual chunk embeddings](https://cadence.withremote.ai/blog/production-rag-architecture)
   (prepend 50–100 token doc-context before embedding) cut failed
   retrievals 49%, 67% with reranker.
5. **[GraphRAG research](https://arxiv.org/abs/2502.11371)**: vector
   RAG wins single-hop/detail; graph wins multi-hop/global; graph
   construction is expensive. The
   ["Do we still need GraphRAG?"](https://arxiv.org/abs/2604.09666v1)
   line shows agentic iterative search substitutes for explicit graph
   structure at far lower cost (same bet as LazyGraphRAG).

---

## Where Cortex is strong — validated by the field's pain

1. **Verbatim ground truth is the structural moat.** Mem0/Zep/Hindsight
   all run an LLM at ingest to extract "facts" — whatever the extractor
   drops or distorts is gone forever ("representation mismatch", the
   field's named failure mode; Mem0 production reports cite memories
   "not added consistently"). Cortex cannot have this failure class:
   plane 1 is deterministic; LLMs only annotate beside the record.
   When a Zep extraction is wrong there is nothing to check it against;
   when a Cortex tldr is wrong, the transcript is right below it.
2. **Provenance nobody else has.** No surveyed system retains raw
   payloads the way bronze does. "Answer with receipts, dispute
   anything back to the original JSON" is a sales story no memory
   vendor can tell. For a product whose value is *trust*, this beats
   5 points of recall.
3. **Supersession ≈ the field's best idea, arrived at independently.**
   Graphiti's headline feature is bi-temporal fact invalidation. The
   Living Source Policy (00b pushback #9) is the same move at document
   granularity — coarser, but deterministic where Zep uses an LLM to
   decide invalidation.
4. **Deterministic entity resolution is the right precision/recall
   trade.** Hindsight uses string similarity + co-occurrence; Zep uses
   LLM judgment — both produce silent false merges. Email-match cannot
   false-merge; it only under-links. Note: Mem0's own 2026
   state-of-the-field names **cross-session identity** the hardest open
   problem — that is exactly 00b pushback #5 (entity merge). The design
   found the field's hardest problem independently; it just hasn't
   solved it either.
5. **The closed-vocab linter gate is unique.** No surveyed system has a
   write gate; they accept whatever the extractor emits, which is why
   their graphs rot. No equivalent of "page #10,000 as trustworthy as
   page #1" exists in the field.

---

## Where Cortex is behind

1. **Single-strategy retrieval — the documented anti-pattern.**
   Hindsight's 91.4% comes from four parallel channels (vector, BM25,
   graph traversal, temporal filter) fused with RRF + cross-encoder
   rerank. Cortex has two channels (vector, graph-via-`entity_refs`),
   **no keyword channel, no reranker**. Irony: on Postgres, `tsvector`
   FTS is nearly free and RRF is ~20 lines of SQL.
2. **Weak document representation.** BGE-small is a weak embedder by
   2026 standards, and one sampler vector per document (P0.14) for a
   30k-token transcript is severely lossy. Contextual chunk embeddings
   map directly onto the unbuilt P0.15.
3. **No eval harness.** SPEC §15's 10 eval questions are written, never
   executed. The clearest lesson of the benchmark wars: unmeasured
   retrieval quality is always overestimated.
4. **Multi-hop unsolved** — `entity_refs` is one hop. Escape hatch the
   research hands us: the consumer is an agent with MCP tools, so
   agentic iterative search (search → read → re-search) substitutes for
   gold-layer graph traversal. Defer graph infra; let the agent hop.
5. **No temporal retrieval channel.** Temporal queries are everyone's
   worst category. Cortex has the scaffolding (`occurred_at`,
   supersession, decay) but date-range extraction from the query is not
   a first-class search strategy yet (Hindsight's is).

---

## Improvements, ranked by impact ÷ cost

| # | Improvement | Cost | Why |
|---|---|---|---|
| 1 | **Eval harness** — execute SPEC §15 questions + ~50 labeled queries; Recall@10 / MRR on every retrieval change | days | Everything below is a guess until this exists |
| 2 | **Hybrid retrieval** — Postgres `tsvector` channel + RRF fusion (k=60) | days | Field consensus: biggest recall lift; nearly free on this stack |
| 3 | **Cross-encoder reranker** — `bge-reranker-v2-m3` local, top-50 → top-5, ~30 ms | small | Biggest precision lift; best single retrofit per production data |
| 4 | **P0.15 with contextual chunk embeddings** — section vectors with prepended doc-context | planned | 49–67% failed-retrieval reduction in published results |
| 5 | **Entity merge/redirect** (00b pushback #5) | medium | The field's named hardest problem; bites on day one of real data |
| 6 | **Temporal filter as retrieval channel** — query date-range → `occurred_at` filter joined into fusion | small | Worst category for everyone; columns already exist |
| 7 | **Embedder upgrade path** — plan migration to `bge-m3` (dense + sparse in one pass; would merge with #2) | medium | Not now; re-embed-ability already guaranteed (bodies rebuildable) |
| 8 | **Defer gold-layer graph; bet on agentic search** | zero | Agent-in-the-loop multi-hop beats expensive graph construction |

---

## Scorecard

| Dimension | vs field | Verdict |
|---|---|---|
| Ground-truth integrity | ahead of everyone | moat — keep |
| Provenance / audit | ahead of everyone | moat — sell it |
| Write discipline (gate, vocab) | unique | moat — but unbuilt (P9) |
| Temporal model | par with Zep conceptually, coarser granularity | good enough for v1 |
| Entity resolution | higher precision, lower recall | right trade; merge flow missing |
| **Retrieval** | **behind — single-strategy vs 4-channel + rerank** | **the gap** |
| Long-doc representation | behind until P0.15 | known, planned |
| Evaluation | behind — designed, not executed | cheapest fix, biggest blindspot |
| Realistic accuracy ceiling | nobody exceeds ~91% recall / ~60% agentic | trust story > recall race |

**One sentence:** Cortex is the layer the field will wish it had once
its extracted-facts graphs rot — but today a question asked of Cortex
flows through a weaker retrieval path than a question asked of any
competitor. All catch-up work is read-side, which strengthens the
existing P9-first sequencing argument (00b pushback #2).

---

## Sources

- [Zep: A Temporal Knowledge Graph Architecture for Agent Memory](https://arxiv.org/abs/2501.13956) (arXiv 2501.13956)
- [Hindsight: Structured Agent Memory that Retains, Recalls, and Reflects](https://ar5iv.labs.arxiv.org/html/2512.12818) (arXiv 2512.12818) + [TEMPR retrieval docs](https://hindsight.vectorize.io/developer/retrieval)
- [Letta — Benchmarking AI Agent Memory: Is a Filesystem All You Need?](https://www.letta.com/blog/benchmarking-ai-agent-memory)
- [RAG vs GraphRAG: A Systematic Evaluation](https://arxiv.org/abs/2502.11371) (arXiv 2502.11371)
- [Do We Still Need GraphRAG? Benchmarking for Agentic Search](https://arxiv.org/abs/2604.09666) (arXiv 2604.09666)
- [Mem0 — State of AI Agent Memory 2026](https://mem0.ai/blog/state-of-ai-agent-memory-2026)
- [Mem0 vs Zep independent comparison](https://vectorize.io/articles/mem0-vs-zep) (independent LongMemEval scores: arXiv 2603.04814)
- [Production RAG architecture 2026](https://cadence.withremote.ai/blog/production-rag-architecture) (hybrid + rerank + contextual retrieval consensus)
