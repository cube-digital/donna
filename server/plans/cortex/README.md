# Cortex Docs

Engineering documentation for Donna's Cortex layer — the structured,
queryable, cluster-organised entity layer that sits between Bronze
(raw connector blobs) and the future Graph layer.

This folder is **plain-English-first**. Every doc opens with the
"why" then drops into the "how". Examples use the same recurring
fixture (Acme onboarding meeting with Alice + Bob) so you can track a
single row through every concept.

Source spec: `01 - Projects/08 - Donna AI/Plans/Cortex Universal Silver
Specification.md` (vault, rev 3). Mirrored in-repo at
[`vault-source/SPEC.md`](./vault-source/SPEC.md) for engineers without
vault access. The implementation roadmap (phases F0-F12) lives at
[`vault-source/IMPLEMENTATION-ROADMAP.md`](./vault-source/IMPLEMENTATION-ROADMAP.md).
The original rev-1 layer plan (superseded by SPEC.md rev 3) is preserved
at [`vault-source/CORTEX-LAYER-PLAN-rev1-superseded.md`](./vault-source/CORTEX-LAYER-PLAN-rev1-superseded.md).
This folder is the engineering companion — how the spec is realised in
Python + Postgres.

## Reading order

1. **Start here** → [`00 - vision.md`](./00%20-%20vision.md)
   - New to the project? Read the plain-English narrative first:
     [`00a - how-it-comes-together.md`](./00a%20-%20how-it-comes-together.md)
   - Then the design rationale + debate:
     [`00b - design-debate-qa.md`](./00b%20-%20design-debate-qa.md)
2. **Architecture** — system shape, data model, facade
3. **Subsystems** — deep dive into the five pieces
4. **Contracts** — closed-vocab types, edges, rules
5. **Flows** — runtime behaviour
6. **Examples** — concrete end-to-end traces
7. **Status** — what's shipped, what's left

## Folder map

```
00 - vision.md                         ← entry: why + glossary
00a - how-it-comes-together.md         ← plain-English narrative (one client, one week)
00b - design-debate-qa.md              ← three-planes model, 5 foundational Q&As, open pushbacks
01 - architecture/                     ← system shape
   01-five-subsystems.md
   02-cortexwriter-facade.md
   03-data-model.md
   04-scope-boundary.md
   05-storage-postgres-derived.md
02 - subsystems/                       ← the five pieces, deeper
   01-ocr.md
   02-embedding-clustering.md
   03-entity-extraction-resolver.md
   04-folder-resolvers.md
   05-template-engine.md
03 - contracts/                        ← closed-vocab definitions
   01-12-types.md
   02-9-edges.md
   03-3-reverse-backlinks.md
   04-linter-r1-r10.md
   05-type-authority.md
   06-reject-codes.md
04 - flows/                            ← runtime walks
   01-bronze-to-cortex-trigger.md
   02-11-step-walkthrough.md
   03-save-with-reverse-edges.md
   04-clustering-online-vs-batch.md
05 - examples/                         ← concrete end-to-end traces
   01-fathom-meeting-end-to-end.md
   02-acme-unified-namespace.md
   03-adr-supersession.md
   04-contradiction-open-questions.md
06 - status/                           ← state of the world
   (01-implementation-state / 02-spec-gap-analysis / 03-roadmap-remaining-work
    were deleted 2026-07-15 — superseded by ../../16-remaining-work.md, the
    single verified remaining-work doc)
   04-p0.14-storage-and-embedding-refactor.md   ← SHIPPED (kept for reference)
   05-deferred-document-chunking.md             ← deferred P0.15 (feature spec)
   06-narrio-adoptions.md                       ← 8 items pulled from Narrio (feature spec)
   06-p0.15-long-document-support.md            ← deferred long-doc (feature spec)
vault-source/                          ← verbatim mirror of vault canonical docs
   README.md
   SPEC.md                                       ← Universal Silver Specification (rev 3)
   IMPLEMENTATION-ROADMAP.md                     ← F0-F12 phase roadmap
   CORTEX-LAYER-PLAN-rev1-superseded.md          ← legacy, kept for history
```

## Companions outside this folder

| File | Purpose |
|---|---|
| `server/donna/cortex/` | Implementation source (Python) |
| `01 - Projects/08 - Donna AI/Plans/Cortex Universal Silver Specification.md` (vault) | Spec — the locked contract. Mirrored at `vault-source/SPEC.md` |
| `01 - Projects/08 - Donna AI/Plans/Cortex Implementation Roadmap.md` (vault) | Phase plan F0-F12. Mirrored at `vault-source/IMPLEMENTATION-ROADMAP.md` |
| `01 - Projects/08 - Donna AI/Plans/Cortex Layer Plan.md` (vault) | Original 9-step plan (rev 1 — superseded by spec rev 3). Mirrored at `vault-source/CORTEX-LAYER-PLAN-rev1-superseded.md` |
| `server/plans/communication-platform-plan.md` | Chat platform plan (Phase 0-8). Mirrored from vault `Communication Platform Plan.md` |
| `server/donna/CLAUDE.md` | Repo-wide conventions |
