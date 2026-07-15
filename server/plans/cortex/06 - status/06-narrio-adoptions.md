# Narrio Adoptions — 8 "Strong Now" items for Cortex

> Status: **Approved 2026-06-10**. Phased rollout across 3 PRs.
> Source plan: `/Users/ristoc/.claude/plans/let-s-do-an-plan-sunny-starfish.md`
> Decision: `server/plans/decisions/ADR-0001-narrio-adoptions-locked.md` (PR 1)

---

## Context

Donna's Cortex layer (the "LLM Wiki enhanced silver layer") shipped through P0.13: 11-step `CortexWriter` pipeline, 12 entity types, R1-R5 + R9 linter rules, bidirectional edges, HDBSCAN clustering, BGE-small embeddings, Postgres + SilverStorage protocol.

Narrio's `narrio-docs` (at `/Users/ristoc/Workspaces/narrio/narrio/narrio-docs/`) shows a parallel B2B-CRM system one stage ahead in synthesis maturity: cluster-anchored pattern extraction (`ExtractedPattern`), per-deal narrative compile (`WikiPage` + Sonnet), two-tier staleness flags, per-entity health scoring, ADR discipline, and a 4-lens quality gate per sprint.

Eight items are worth adopting **now** because the slots are missing entirely in Cortex and adding them later costs schema migration + linter rewrites + cache invalidation pain. The remaining Narrio items (separate embedding table, lazy compile, per-tenant config, scale-ops research) defer cleanly.

Roll out in three PRs to keep review surface small and let each PR ship + bake before the next.

---

## Eight items adopted

| ID | Item | PR |
|---|---|---|
| A1 | `CortexPattern` model (cluster-anchored synthesis slot) | 2 |
| A2 | `compile_narrative` Celery task + `CortexNarrative` model (Sonnet, lazy) | 3 |
| A3 | Two-tier staleness: `cluster_stale` + `narrative_stale` cascade | 2 |
| A4 | Model-tier policy doc (Haiku/Sonnet/Opus per step) | 1 |
| A5 | `evidence_entity_ids` on synthesized rows + linter rule R11 | 2 |
| A6 | `TypeSpec.embed_policy` opt-out for state-only entities | 2 |
| A7 | Architecture quality lens template (4 lenses: scale/cloud/observability/extensibility) | 1 |
| A8 | ADR-0001 + supersession protocol + `server/plans/decisions/` folder | 1 |

---

## PR 1 — Docs + governance (no schema, no code)

**Goal:** ship the discipline layer first. Forces every subsequent PR to follow ADR + quality-lens conventions.

### Files created (new)

| Path | Purpose |
|---|---|
| `server/plans/decisions/README.md` | ADR conventions: monotonic numbering (`ADR-0001`), `Supersedes:` header, statuses (Proposed/Accepted/Superseded/Deprecated), one decision per file, never delete |
| `server/plans/decisions/ADR-0000-template.md` | Skeleton: title / status / context / options / decision / consequences / supersedes |
| `server/plans/decisions/ADR-0001-narrio-adoptions-locked.md` | The decision itself — adopt A1-A8, defer B/C. Cites this plan. |
| `server/plans/cortex/quality-lens-template.md` | 4-lens review: SCALE, CLOUD ARCHITECTURE, OBSERVABILITY, EXTENSIBILITY. Each section: questions to answer + deferral ID convention `DEF-<phase>-<n>` |
| `server/plans/cortex/model-tier-policy.md` | Locked table: Step → Model. Step 4 fitter → Haiku. Step 9 GLiNER + Haiku fallback. Future Step 12 synth → Sonnet. Agent reasoning → Sonnet/Opus. |
| `server/plans/cortex/06 - status/06-narrio-adoptions.md` | This file. |

### Files edited

| Path | Change |
|---|---|
| `server/plans/cortex/README.md` | Add reading-order entry for `decisions/` + `quality-lens-template.md` + `model-tier-policy.md` |
| `server/plans/README.md` | Mention `decisions/` is the project-wide ADR home |
| `CLAUDE.md` | Add bullet: every architectural change needs an ADR; every phase plan closes with a quality-lens review section |

### Verification

```bash
# 1. Folder + files exist
ls server/plans/decisions/ server/plans/cortex/quality-lens-template.md server/plans/cortex/model-tier-policy.md

# 2. ADR-0001 references this adoption plan
grep -q "06-narrio-adoptions" server/plans/decisions/ADR-0001-narrio-adoptions-locked.md

# 3. No code changed
git diff --stat server/donna/ | wc -l   # → 0
```

No code, no tests, no migration. Pure docs PR — fast review.

---

## PR 2 — Structural: pattern model, staleness, evidence, embed-policy

**Goal:** all schema + linter + TypeSpec changes in one cohesive PR. One migration. No runtime behaviour change yet (the new compile task lands in PR 3).

### Files created

| Path | Purpose |
|---|---|
| `server/donna/cortex/models.py` (extend) | Add `CortexPattern` model |
| `server/donna/cortex/schemas.py` (extend) | Pydantic `PatternKind` enum + `PatternEvidence` shape |
| `server/donna/cortex/migrations/0002_pattern_staleness_embedpolicy.py` | One atomic migration |
| `server/donna/cortex/tests/test_pattern_model.py` | Pattern CRUD + evidence linter |
| `server/donna/cortex/tests/test_staleness_cascade.py` | New entity → cluster_stale → patterns of that cluster → narrative_stale |
| `server/donna/cortex/tests/test_embed_policy.py` | `embed: "never"` skips embedder, no embedding row |

### Files edited

| Path | Change |
|---|---|
| `server/donna/cortex/models.py` | Add `cluster_stale: bool` and `narrative_stale: bool` to CortexEntity. Default `True` on insert (forces first synth). |
| `server/donna/cortex/registry.py` | Add `embed_policy: Literal["always", "if_body_len_gt", "never"]` to `TypeSpec`. Default `"always"`. Add `embed_policy_threshold: int = 0`. |
| `server/donna/cortex/templates/ticket.py` | Set `embed_policy="if_body_len_gt"`, `embed_policy_threshold=120` (skip pure status-change tickets) |
| `server/donna/cortex/templates/chat.py` | Set `embed_policy="if_body_len_gt"`, `embed_policy_threshold=20` (skip emoji-only) |
| `server/donna/cortex/pipeline.py` | Step 5 guard: skip `embedder.embed()` + `clusterer.assign()` when policy says don't embed |
| `server/donna/cortex/pipeline.py` | Step 5 also: when new entity DOES embed, set `cluster_stale=True` on all entities sharing the assigned `cluster_id` in same scope (cascade trigger for PR 3) |
| `server/donna/cortex/linter.py` | Add `R11_EVIDENCE_REQUIRED_FOR_SYNTH`: if `author == "donna"` AND `source.startswith("cortex://synth/")`, then `evidence_entity_ids` must be non-empty list |
| `server/donna/cortex/authority.py` | Add `RejectCode.MISSING_SYNTH_EVIDENCE` |
| `server/plans/cortex/03 - contracts/04-linter-r1-r10.md` | Document R11 (rule list becomes R1-R11) |

### `CortexPattern` model shape

```python
# server/donna/cortex/models.py
class CortexPattern(TimestampsMixin, models.Model):
    """
    Cluster-anchored synthesis row. LLM-extracted facts about a cluster of entities.
    Re-extracted when cluster_stale on member entities flips True.
    Lives separate from CortexEntity to keep the 12-type closed vocab intact.
    """
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4)
    workspace     = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    client_id     = models.UUIDField(null=True, db_index=True)
    project_id    = models.UUIDField(null=True, db_index=True)
    cluster_id    = models.UUIDField(db_index=True)

    pattern_kind  = models.CharField(max_length=32)       # Literal from PatternKind
    title         = models.CharField(max_length=500)
    body_md       = models.TextField()                    # short, structured. ~500 tokens.

    evidence_entity_ids = models.JSONField(default=list)  # required non-empty by R11
    confidence    = models.CharField(max_length=8, choices=[("high","high"),("medium","medium"),("low","low")])

    extracted_by  = models.CharField(max_length=16)       # "haiku-v4.5", "sonnet-v4.6"
    last_extracted = models.DateTimeField(auto_now=True)

    stale         = models.BooleanField(default=False)    # set True when any evidence entity is updated

    class Meta:
        indexes = [
            models.Index(fields=["workspace", "cluster_id"]),
            models.Index(fields=["workspace", "client_id", "project_id"]),
            models.Index(fields=["stale"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "cluster_id", "pattern_kind"],
                name="uq_pattern_per_cluster_kind",
            ),
        ]
```

### Cascade hook

```python
# server/donna/cortex/pipeline.py — after Step 5 cluster assignment
if entity.cluster_id and embedded:
    # Mark cluster stale + downstream narrative stale
    CortexEntity.objects.filter(
        workspace=entity.workspace,
        client_id=entity.client_id,
        project_id=entity.project_id,
        cluster_id=entity.cluster_id,
    ).exclude(id=entity.id).update(cluster_stale=True, narrative_stale=True)

    CortexPattern.objects.filter(
        workspace=entity.workspace,
        cluster_id=entity.cluster_id,
    ).update(stale=True)
```

(No CortexNarrative cascade yet — PR 3 introduces the model.)

### Migration sketch

```python
operations = [
    migrations.AddField("cortexentity", "cluster_stale", models.BooleanField(default=True)),
    migrations.AddField("cortexentity", "narrative_stale", models.BooleanField(default=True)),
    migrations.CreateModel("CortexPattern", fields=[...]),
    # CortexNarrative deferred to PR 3
]
```

### Verification

```bash
cd server
DJANGO_SETTINGS_MODULE=donna.settings .venv/bin/python -m django makemigrations cortex --check  # → exits clean
DJANGO_SETTINGS_MODULE=donna.settings .venv/bin/python -m django migrate
DJANGO_SETTINGS_MODULE=donna.settings .venv/bin/python -m django test donna.cortex.tests
# Manual: ingest a Fathom meeting → verify cluster_stale=True on neighbours, no embedding for chat-emoji entity
```

---

## PR 3 — `compile_narrative` task + `CortexNarrative` model

**Goal:** lazy Sonnet narrative compilation. Reads patterns + member entities → renders human-prose markdown wiki page per scope. Cacheable.

### Files created

| Path | Purpose |
|---|---|
| `server/donna/cortex/models.py` (extend) | Add `CortexNarrative` model |
| `server/donna/cortex/synthesis.py` | New module — `PatternExtractor` (Haiku) + `NarrativeCompiler` (Sonnet) |
| `server/donna/cortex/tasks.py` (extend) | `extract_patterns_for_cluster(workspace_id, cluster_id)` + `compile_narrative_for_scope(workspace_id, client_id, project_id)` |
| `server/donna/cortex/migrations/0003_narrative_model.py` | CortexNarrative + indexes |
| `server/donna/cortex/templates/narrative.j2` | Jinja prompt + render skeleton |
| `server/donna/cortex/tests/test_narrative_compile.py` | Synth → narrative → re-read returns cached. Mark stale → recompiles. |

### `CortexNarrative` model shape

```python
class CortexNarrative(TimestampsMixin, models.Model):
    """
    Per-scope wiki page. Sonnet-rendered prose from CortexPattern rows + member entities.
    Lazy — compiled on first read, recompiled when narrative_stale flips True.
    """
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4)
    workspace   = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    client_id   = models.UUIDField(null=True, db_index=True)
    project_id  = models.UUIDField(null=True, db_index=True)

    body_md     = models.TextField()
    pattern_ids = models.JSONField(default=list)   # which CortexPatterns informed this narrative
    entity_ids  = models.JSONField(default=list)   # which CortexEntities are cited

    storage_key = models.CharField(max_length=500) # path in SilverStorage (canonical file)
    compiled_by = models.CharField(max_length=16)  # "sonnet-v4.6"
    compiled_at = models.DateTimeField(auto_now=True)
    prompt_version = models.CharField(max_length=16)

    stale       = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "client_id", "project_id"],
                name="uq_narrative_per_scope",
            ),
        ]
```

### Task wiring

```python
# server/donna/cortex/tasks.py
@shared_task(name="cortex.extract_patterns")
def extract_patterns_for_cluster(workspace_id: str, cluster_id: str) -> None:
    """Triggered when CortexPattern.stale=True for a cluster, or by beat scan."""
    extractor = PatternExtractor()                      # Haiku
    extractor.run(workspace_id, cluster_id)             # creates / updates CortexPattern rows
    # Pattern updates flip CortexNarrative.stale via post_save signal

@shared_task(name="cortex.compile_narrative")
def compile_narrative_for_scope(workspace_id, client_id, project_id) -> None:
    """Triggered by API read or by beat scan of stale narratives."""
    compiler = NarrativeCompiler()                      # Sonnet
    compiler.run(workspace_id, client_id, project_id)   # writes CortexNarrative + SilverStorage file
```

### Reuse from existing code

| New code | Reuses |
|---|---|
| `NarrativeCompiler` | `donna.cortex.template_engine.TemplateEngine` (Jinja), `donna.cortex.storage` (SilverStorage write) |
| `PatternExtractor` | `donna.cortex.registry.TemplateRegistry` (for Pydantic-locked output), `donna.cortex.embeddings` (cluster member fetch) |
| Sonnet/Haiku client | `donna.core.llm.*` (per `model-tier-policy.md` from PR 1) — if doesn't exist, this PR creates `donna/core/llm.py` thin wrapper |
| Cascade signals | Extend Step 5 hook from PR 2 to also cascade pattern → narrative |

### Beat schedule

Add to `server/donna/settings.py` celery beat:

```python
CELERY_BEAT_SCHEDULE = {
    ...,
    "cortex.extract_stale_patterns":  {"task": "cortex.extract_patterns_fanout",  "schedule": 300},
    "cortex.compile_stale_narratives":{"task": "cortex.compile_narrative_fanout", "schedule": 600},
}
```

Fanout tasks find `stale=True` rows and enqueue per-cluster / per-scope work — same pattern as existing `recluster_fanout`.

### Verification

```bash
cd server
DJANGO_SETTINGS_MODULE=donna.settings .venv/bin/python -m django migrate
DJANGO_SETTINGS_MODULE=donna.settings .venv/bin/python -m django test donna.cortex.tests.test_narrative_compile
# Manual end-to-end:
# 1. Ingest 3 Fathom meetings for client=acme, project=onboarding
# 2. Wait for cluster_stale cascade to fire
# 3. Run extract_patterns task → CortexPattern rows appear
# 4. Read /api/v1/cortex/narrative?client=acme&project=onboarding → triggers compile_narrative if stale
# 5. Verify SilverStorage file exists, body_md cached in DB, stale=False
# 6. Ingest a 4th meeting → narrative_stale flips True
# 7. Re-read → recompile fires
celery -A donna inspect scheduled  # → confirms beat jobs registered
```

---

## Cross-PR changes to existing planning docs

After PR 1 lands:

- `server/plans/cortex/03 - contracts/04-linter-r1-r10.md` — renamed mentally to "R1-R11"; R11 added in PR 2
- `server/plans/16-remaining-work.md` — the consolidated remaining-work doc (this Narrio adoption is tracked there under §2 "Cortex — missing features")
- `server/plans/cortex/01 - architecture/03-data-model.md` — add `CortexPattern` + `CortexNarrative` to the model inventory diagram
- `server/plans/cortex/04 - flows/05-pattern-and-narrative-compile.md` — NEW flow doc (PR 3) describing the cascade

---

## Existing utilities to reuse (do not reinvent)

| Need | Reuse this | Location |
|---|---|---|
| Per-type Pydantic validation | `TemplateRegistry.get(type).extensions_model` | `donna/cortex/registry.py:30` |
| Atomic transaction | `CortexEntityRepository.save_with_reverse_edges` | `donna/cortex/repository.py` |
| SilverStorage write | `donna.cortex.storage` module | `donna/cortex/storage.py` |
| Linter pattern | `FrontmatterLinter._check_rule_N` | `donna/cortex/linter.py:58` |
| RejectCode pattern | `donna.cortex.authority.RejectCode` | `donna/cortex/authority.py:68` |
| Celery fanout pattern | `recluster_fanout` | `donna/cortex/tasks.py` |
| TimestampsMixin | `donna.core.db.models.TimestampsMixin` | `donna/core/db/models.py:5` |
| HDBSCAN + embedding stack | unchanged from current pipeline | `donna/cortex/clustering.py`, `donna/cortex/embeddings.py` |
| Jinja render | `TemplateEngine` | `donna/cortex/template_engine.py` |

---

## Risks + open items (logged as `DEF-narrio-N`)

| ID | Risk | Mitigation |
|---|---|---|
| DEF-narrio-1 | Sonnet cost at scale (every narrative recompile = N pattern tokens in prompt) | Lazy compile on read only; prompt caching via core/llm wrapper |
| DEF-narrio-2 | Cluster cascade lock contention if many entities update same cluster simultaneously | Use `SELECT FOR UPDATE SKIP LOCKED` in cascade; bulk update |
| DEF-narrio-3 | `embed_policy="if_body_len_gt"` threshold guessed (120 / 20 chars). Measure embedding noise reduction post-ship; tune. | Track skipped count via structlog field `embed_skipped=True` |
| DEF-narrio-4 | `CortexNarrative` is a new model outside the 12-type closed vocab. Could drift from spec. | ADR-0002 (PR 3) explicitly carves out "synthesis surface ≠ entity surface" |
| DEF-narrio-5 | R11 evidence rule might block legitimate edge cases (e.g., narrative auto-generated before patterns exist) | First-pass synth gets confidence="low", evidence_entity_ids=member entity ids of cluster (always non-empty) |

---

## Verification across all three PRs

End-to-end smoke (post-PR-3):

```bash
cd server
docker compose up -d postgres redis
DJANGO_SETTINGS_MODULE=donna.settings .venv/bin/python -m django migrate
DJANGO_SETTINGS_MODULE=donna.settings .venv/bin/python -m django test donna.cortex
celery -A donna worker --loglevel=info &
celery -A donna beat --loglevel=info &

# Trigger ingest via existing test fixture / management command
DJANGO_SETTINGS_MODULE=donna.settings .venv/bin/python -m django shell <<'PY'
from donna.cortex.tests.factories import ingest_fathom_meeting_fixture
ingest_fathom_meeting_fixture(client="acme", project="onboarding", count=3)
PY

# Wait for cascade + beat tick (10 min). Then:
DJANGO_SETTINGS_MODULE=donna.settings .venv/bin/python -m django shell <<'PY'
from donna.cortex.models import CortexEntity, CortexPattern, CortexNarrative
print("entities:", CortexEntity.objects.filter(client_id__isnull=False).count())
print("patterns:", CortexPattern.objects.count())
print("narratives:", CortexNarrative.objects.filter(stale=False).count())
PY
# Expect: entities=3, patterns≥1, narratives=1 with body_md non-empty
```

Spec compliance check:

```bash
grep -c "^- R" "server/plans/cortex/03 - contracts/04-linter-r1-r10.md"   # → 11
ls server/plans/decisions/ADR-000*.md | wc -l                              # → ≥2 (template + 0001)
test -f server/plans/cortex/quality-lens-template.md && echo OK
test -f server/plans/cortex/model-tier-policy.md && echo OK
```

---

## TL;DR

Three PRs. Docs first (governance), structural second (models + linter + embed policy), task third (Sonnet narrative compile).

Eight items from Narrio. None speculative — every one fills a known gap in Cortex (R6/R7/R8 deferred, synthesis layer absent) tracked in `../../16-remaining-work.md` §1–§2.

Reuses every existing utility in `donna/cortex/`. One new module (`synthesis.py`). Two new models (`CortexPattern`, `CortexNarrative`). One linter rule (R11). One TypeSpec field (`embed_policy`). Two staleness booleans. Plus docs.
