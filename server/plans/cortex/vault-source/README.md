# vault-source — Mirrored from Obsidian vault

Verbatim copies of the canonical planning docs that live in the Obsidian vault at `01 - Projects/08 - Donna AI/Plans/`. Mirrored into the repo on **2026-06-10** so engineers without vault access can read them.

## Files

| File | Vault source | Role |
|---|---|---|
| `SPEC.md` | `Cortex Universal Silver Specification.md` (rev 3, 2026-06-02) | **Locked contract.** Schema + edges + storage + write contract that applies identically across all Cortex workspaces. |
| `IMPLEMENTATION-ROADMAP.md` | `Cortex Implementation Roadmap.md` | Phase-ordered build plan (F0 → F12). Critical path + milestones M1-M5. |
| `CORTEX-LAYER-PLAN-rev1-superseded.md` | `Cortex Layer Plan.md` (rev 1) | **Superseded by SPEC.md rev 3.** Original 9-step pipeline + 5 subsystems plan. Kept for history. |

## Source of truth

**Vault remains canonical.** Edits land in the vault first; this folder is regenerated when the vault changes. Do not edit these files in place — sync them from the vault instead.

Engineering companion docs at `server/plans/cortex/00 - vision.md`, `01 - architecture/`, `02 - subsystems/`, etc. expand the spec operationally. Those ARE edited in-repo and are the live source for implementation detail (11-step pipeline, OCR strategies, atomic persist, etc.).

## Why mirror?

1. **Read access** — engineers using only the repo (no vault) can see the locked schema + roadmap.
2. **Diff history** — git history captures spec evolution alongside code changes.
3. **Offline reference** — survive vault outages, plugin breakage, or any external knowledge-base failure.
4. **CI hooks** — pre-commit / linter checks can read the spec without external fetches.

## Relationship to other in-repo docs

```
vault-source/SPEC.md                              ← locked contract (vault canonical)
       │
       │  expanded operationally by
       ▼
server/plans/cortex/00 - vision.md                ← engineering entry doc
server/plans/cortex/01 - architecture/*           ← system shape
server/plans/cortex/02 - subsystems/*             ← the five Strategy pieces
server/plans/cortex/03 - contracts/*              ← closed-vocab enforcement
server/plans/cortex/04 - flows/*                  ← runtime walks
server/plans/cortex/05 - examples/*               ← end-to-end traces
server/plans/cortex/06 - status/*                 ← implementation state + adoptions

vault-source/IMPLEMENTATION-ROADMAP.md            ← vault roadmap (phases F0-F12)
       │
       │  current state tracked in
       ▼
server/plans/cortex/06 - status/01-implementation-state.md
```

## Re-sync procedure

1. Fetch latest from vault: `01 - Projects/08 - Donna AI/Plans/*.md`
2. Overwrite the files above (preserve filenames + the supersession header on the rev-1 plan)
3. Update revision dates + this README
4. Commit with message `docs: sync vault-source from vault (rev X)`
