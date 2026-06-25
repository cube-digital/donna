# 2026-06-10 12:51 — Cortex Silver Layer Design Review

## Summary & Overview

Deep design-review session on Donna's Cortex (Silver) layer. Read the complete `server/plans/cortex/` doc tree (architecture, subsystems, contracts, flows, examples, status), the `vault-source/` mirrored spec docs, and the full `server/donna/cortex/` implementation. Then re-anchored the vision in a debate over five foundational questions (verbatim content vs LLM-altered, derived docs, hierarchy vs graph, write discipline, continuous maintenance). Output: two new permanent docs (`00a` plain-English narrative, `00b` design Q&A + pushback tracker), README updated, and a tracked list of 8 open design debts. No production code was changed.

## Key Learnings

- **The three-planes model** — the whole design reduces to: plane 1 ground truth (verbatim bodies + provenance, immutable), plane 2 connective tissue (edges, entity refs, clusters, scope — deterministic + statistical), plane 3 derived surface (synthesis docs, indexes — LLM, citation-bound, disposable). The trust rule: plane 3 may only cite plane 1, never replace it.
- **Three trust tiers, not two** — deterministic (provider metadata, email-match resolution), statistical (BGE-small embeddings + HDBSCAN clustering — reproducible math), LLM (only fills closed-vocab fields, names clusters, writes citation-bound syntheses). LLM-based entity extraction was deliberately rejected; ~90% of entity signal comes free from provider metadata. GLiNER is a small local NER model (optional, off by default), not an LLM.
- **Normalization ≠ alteration** — bodies are verbatim; only the *format* is normalized (adapter/OCR → markdown + frontmatter + Source footer). Digestibility comes from augmentation beside the body (tldr in frontmatter, P0.15 sections, patterns/narratives), never from rewriting it.
- **"Everything about Acme" is never stored** — it's a live GIN query over `entity_refs`. The entity page is the anchor; the query is the biography. That's why entity views can't go stale.
- **Search is answer mode; the tree is browse mode** — agents should answer via Postgres (ANN + `entity_refs` containment + filters); `_index.md`/`_log.md` walking is for vague questions, cold start, and human/Obsidian auditability.
- **Scope `client_id=None/project_id=None` at write is policy, not a bug** — `04-scope-boundary.md` mandates that promotion to client scope is a deliberate human/agent act via MCP API (P9). Consequence: until P9 exists, everything clusters in one workspace-root scope.
- **Status docs drift from code** — `06 - status/01-implementation-state.md` says Gmail pending, but `google/mail/tasks.py` already has the CortexWriter hop (Drive was skipped). `diagrams.md` is the more current source. P0.14 (body → FileField + samplers) is fully in code with the FileField squashed into `0001_initial.py`.

## Decisions Made

- **Augment, don't alter** — verbatim body stays canonical; LLM digestibility lives in frontmatter tldr + synthesis docs with mandatory citations. Rejected: LLM-rewritten bodies (loses anti-hallucination + audit-trail guarantees).
- **Hold the line on closed vocabularies + Path 1 Strict** — every write (connector, human, coding agent) through the same MCP API → linter gate. Rejection at the gate is cheap; cleaning a polluted wiki is not.
- **Maintenance may only touch planes 2 and 3** — recluster, decay, staleness cascade, contradiction flags, derived-doc rebuilds. Ground-truth bodies never mutated; changes only via supersession chains (R1).
- **Recommended sequencing: P9 (MCP API) first** — over P0.15 long-doc tiers and Narrio synthesis PRs, because nothing can read the layer yet and the enforcement surface (the wiki's actual moat) doesn't exist. Not yet ratified by user — recorded as open pushback #2.
- **Docs placement** — session knowledge preserved as `00a` (narrative) + `00b` (debate + pushback table) inside `server/plans/cortex/`, registered in README reading order between vision and architecture.

## Pending Tasks

- [ ] Decide sequencing: P9 MCP API vs P0.15 long-doc support vs Narrio PRs 1-3 (`00b` pushback #2). Recommendation on record: P9 first.
- [ ] Fix resolver `_spawn` bypassing the linter — spawned person/org/concept/project rows land unchecked (`server/donna/cortex/entities.py`, `_spawn`). Cheap: run `FrontmatterLinter.check()` before save.
- [ ] Fix `GLiNERExtractor.extract` reading `entity.body_md` — attribute removed in P0.14 (now `body` FileField / `load_body()`); latent `AttributeError` when GLiNER is first enabled (`entities.py` line ~170).
- [ ] Spec amendment: curated-entity merge/redirect flow (duplicate orgs from `acme.com`/`acme.io`, persons under two emails). No mechanism exists today.
- [ ] Sync `06 - status/01-implementation-state.md` with reality (Gmail wired, Drive skipped, P0.14 landed).
- [ ] Mark `server/donna/cortex/storage.py` (`LocalFSStorage` + Protocol) explicitly as P9+ to avoid two coexisting "storage truths" (real SilverStorage today = FileField + `default_storage`).
- [ ] When any pushback is resolved, update its row in the `00b` table in the same commit (per plans-as-live-contract convention).

## Files Modified

- `server/plans/cortex/00a - how-it-comes-together.md` — NEW (earlier in session): plain-English narrative — one client (Acme), one week, library metaphor; appended See-also section linking 00b.
- `server/plans/cortex/00b - design-debate-qa.md` — NEW: three-planes model, five foundational Q&As with step-by-step examples and pushbacks, trust-tier table (deterministic/statistical/LLM), four-sentence compression, table of 8 open pushbacks.
- `server/plans/cortex/README.md` — registered 00a + 00b in reading order and folder map.

## Blockers & External Dependencies

- **P9 (MCP API) unbuilt** — blocks: scope promotion, `_index.md`/`_log.md` regeneration, lint dry-run for coding agents, R1/R10 update-path enforcement, SilverStorage Protocol wiring. Unblocks when: P9 is prioritized and shipped.
- **Maintenance jobs unbuilt beyond reclustering** — R6 staleness cascade, R8 confidence decay, R7 contradiction sweep are designed (fields + repo writers exist) but have no detectors/tasks. Unblocks when: corresponding Celery tasks are implemented (R7 additionally needs an entailment model).
