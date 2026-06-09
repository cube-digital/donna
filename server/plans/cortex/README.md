# Cortex Docs

Engineering documentation for Donna's Cortex layer — the structured,
queryable, cluster-organised entity layer that sits between Bronze
(raw connector blobs) and the future Graph layer.

This folder is **plain-English-first**. Every doc opens with the
"why" then drops into the "how". Examples use the same recurring
fixture (Acme onboarding meeting with Alice + Bob) so you can track a
single row through every concept.

Source spec: `01 - Projects/08 - Donna AI/Plans/Cortex Universal Silver
Specification.md` (vault). This folder is the engineering companion —
how the spec is realised in Python + Postgres.

## Reading order

1. **Start here** → [`00 - vision.md`](./00%20-%20vision.md)
2. **Architecture** — system shape, data model, facade
3. **Subsystems** — deep dive into the five pieces
4. **Contracts** — closed-vocab types, edges, rules
5. **Flows** — runtime behaviour
6. **Examples** — concrete end-to-end traces
7. **Status** — what's shipped, what's left

## Folder map

```
00 - vision.md                         ← entry: why + glossary
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
   01-implementation-state.md
   02-spec-gap-analysis.md
   03-roadmap-remaining-work.md
   04-p0.14-storage-and-embedding-refactor.md   ← next phase plan
   05-deferred-document-chunking.md             ← deferred P0.15
```

## Companions outside this folder

| File | Purpose |
|---|---|
| `server/donna/cortex/` | Implementation source (Python) |
| `01 - Projects/08 - Donna AI/Plans/Cortex Universal Silver Specification.md` (vault) | Spec — the locked contract |
| `01 - Projects/08 - Donna AI/Plans/Cortex Layer Plan.md` (vault) | Original 9-step plan (rev 1 — superseded by spec rev 3) |
| `server/donna/CLAUDE.md` | Repo-wide conventions |
