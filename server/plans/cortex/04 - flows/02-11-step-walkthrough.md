# 11-Step Pipeline Walkthrough (Plain English)

The complete `CortexWriter.write(dp)` walk in plain English. Each step
opens with "why", then "how", then "concrete example".

**Recurring example:** Fathom meeting `"Acme onboarding call"`.

```python
DeliveryPackage(
    provider           = "fathom",
    provider_item_type = "meeting",
    provider_item_id   = "rec-abc123",
    workspace_id       = ws-qube,
    title              = "Acme onboarding call",
    occurred_at        = 2026-06-03T14:00:00Z,
    metadata = {
        "host":       {"name": "Alice", "email": "alice@acme.com"},
        "attendees":  [
            {"name": "Alice", "email": "alice@acme.com", "role": "host"},
            {"name": "Bob",   "email": "bob@example.com"},
        ],
        "duration_min": 30,
    },
    storage_key = "ws-qube/fathom/meetings/rec-abc123.json",
)
```

Body text after step 1: `# Acme onboarding call\n\nDiscussed Stripe
integration next.`

## Step 1 — OCR / markdownify

**Why:** every source format → uniform markdown. Cortex only speaks
markdown.

**How:** `_body_for(dp)` reads the blob from `default_storage`. JSON
shape → adapter.to_markdown(). Binary shape → OCR fallback chain.

**Example:** Fathom adapter sees JSON → returns transcript as markdown.

### Output
```markdown
# Acme onboarding call

Discussed Stripe integration next.
```

## Step 2 — Type resolve + TypeSpec lookup

**Why:** different content shapes need different rules. Look up the
contract for this type.

**How:** `PROVIDER_TYPE_MAP["meeting"] → "meeting"`, then
`registry.get("meeting") → MeetingSpec`.

**Example:**
```python
type_spec = TypeSpec(
    type="meeting",
    extensions_model=MeetingExtensions,
    fit_model=None,                        # provider satisfies nav fields
    template_path="meeting.j2",
    nav_fields=["attendees"],
    folder_resolver=TemporalFolderResolver(bucket="meetings"),
    version="meeting@v1",
)
```

## Step 3 — Deterministic frontmatter fill

**Why:** Fathom already knows host, attendees, duration. No LLM tax.

**How:** `_build_extensions(dp, type_spec)` copies from `dp.metadata`:

```python
extensions = {
    "attendees": [
        {"name": "Alice", "email": "alice@acme.com", "role": "host"},
        {"name": "Bob",   "email": "bob@example.com", "role": None},
    ],
    "duration_min": 30,
    "recording_url": None,
}
```

Anti-hallucination root cause: provider-known facts never flow through
an LLM.

## Step 4 — Fitter fallback (Haiku)

**Why:** generic web clip / Drive PDF without provider metadata?
Then (and only then) call the LLM, locked to Pydantic schema.

**How:**

```python
if not linter.has_required_nav_fields(extensions, ["attendees"]):
    if type_spec.fit_model is not None:
        fit = self.fitter.fit(body_md, type_spec.fit_model)
        extensions = merge(extensions, fit)
```

**Example:** meeting has `attendees`, nav-fields satisfied → **skip
fitter**. No LLM call.

Compare with a `doc` ingest: nav fields `["doc_type"]` missing → call
HaikuFitter with `DocExtensions` as `response_format`. Pydantic Literal
locks the value to one of 16 doc types.

## Step 5 — Embed + cluster_assign

**Why:** turn body into vector; find the closest cluster within scope.

**How:** Two-stage if embeddings enabled:

```python
embedding = self.embedder.embed(body_md)   # → 384-dim list
cluster_id, cluster_name = self.clusterer.assign(embedding, scope)
```

**Example:** vector `[0.12, -0.05, 0.31, ...]`. Closest centroid in
workspace = cluster `Customer Onboarding` (cosine 0.87). Result:

```python
extensions["cluster_name"] = "Customer Onboarding"
new_entity.cluster_id      = <uuid-of-that-cluster>
new_entity.doc_embedding   = [0.12, -0.05, ...]
```

If embeddings disabled or cold-start workspace → `(None, None)`.

## Step 6 — Folder placement

**Why:** every row gets ONE canonical filesystem location.

**How:**

```python
parent_path = type_spec.folder_resolver.canonical_path(
    type=cortex_type,
    occurred_at=dp.occurred_at,
    extensions=extensions,
    client_slug=...,   # resolved from scope
    project_slug=...,
)
slug = _build_slug(dp, body_md)
```

**Example:**
- `client_slug = None` (meeting not yet promoted to client scope)
- `project_slug = None`
- TemporalFolderResolver(`bucket="meetings"`):
  → `parent_path = "meetings/2026/06"`
- `slug = "2026-06-03-acme-onboarding-call-a4b2c8e1"`

(If/when the agent promotes this to client scope:
`client_slug="acme"`, `project_slug="onboarding"`, then:
`parent_path = "clients/acme/projects/onboarding/meetings/2026/06"`.)

## Step 7 — Render body via Jinja

**Why:** wrap verbatim body in uniform frontmatter + Source footer.

**How:**

```python
body_md_final = self.engine.render(
    type_spec,
    data=extensions,
    body_input=body_md,
    title=dp.title,
    occurred_at=dp.occurred_at,
    source_uri="fathom://meeting/rec-abc123",
    bronze_storage_key="ws-qube/fathom/meetings/rec-abc123.json",
)
```

**Example output:**

```markdown
---
type: meeting
title: Acme onboarding call
occurred_at: 2026-06-03 14:00:00+00:00
parent_path: meetings/2026/06
slug: 2026-06-03-acme-onboarding-call-a4b2c8e1
template_version: meeting@v1
attendees:
  - "Alice <alice@acme.com> (host)"
  - "Bob <bob@example.com>"
duration_min: 30
cluster_name: "Customer Onboarding"
---

# Acme onboarding call

Discussed Stripe integration next.

Source: fathom://meeting/rec-abc123 (ws-qube/fathom/meetings/rec-abc123.json)
```

## Step 8 — Build entity (unsaved)

**Why:** package everything into the ORM object and hash the body for
idempotency.

**How:**

```python
content_hash = sha256(body_md_final)
new_entity = CortexEntity(
    workspace_id   = ws-qube,
    type           = "meeting",
    author         = "donna",
    source         = "fathom://meeting/rec-abc123",
    bronze_storage_key = "ws-qube/fathom/meetings/rec-abc123.json",
    occurred_at    = 2026-06-03T14:00:00Z,
    client_id      = None,
    project_id     = None,
    cluster_id     = <cluster-uuid>,
    doc_embedding  = [...384 floats...],
    confidence     = "high",
    last_synthesized = today,
    title          = "Acme onboarding call",
    body_md        = body_md_final,
    content_hash   = sha256(...),
    extensions     = extensions,
)
```

Not yet persisted.

## Step 9 — Entity extraction + resolution

**Why:** meeting mentions Alice + Bob + Acme. Find/spawn typed entity
rows; bind them via `entity_refs`.

**How:**

```python
candidates = self.extractor.extract(entity=new_entity, context=ctx)
for cand in candidates:
    target_id = self.resolver.resolve(cand, scope)
    entity_refs.append(str(target_id))
new_entity.entity_refs = entity_refs
```

**Example trace:**

```
Extractor (ProviderMetadataExtractor):
  → ExtractedEntity(type=person, label=Alice, email=alice@acme.com, conf=1.0, origin=provider)
  → ExtractedEntity(type=person, label=Bob, email=bob@example.com, conf=1.0, origin=provider)
  → ExtractedEntity(type=org, label=Acme, domain=acme.com, conf=0.9, origin=provider)
  → ExtractedEntity(type=org, label=Example, domain=example.com, conf=0.9, origin=provider)

Resolver:
  Alice  → existing person row alice-uuid (match by email)
  Bob    → no match → SPAWN new person row bob-uuid
  Acme   → existing org row acme-uuid (match by domain)
  Example→ no match → SPAWN new org row example-uuid

→ new_entity.entity_refs = [alice-uuid, bob-uuid, acme-uuid, example-uuid]
```

Spawned rows ship with `author="donna"`, `source="cortex://spawn/<id>"`,
`confidence="medium"`, body ending in `Spawned by: cortex-resolver`.

## Step 10 — Linter gate

**Why:** last line of defence before persistence.

**How:** `linter.check(new_entity)` runs 11 individual checks; raises
`LinterError(code, message)` on any failure.

**Example outcomes:**

| Scenario | Lint result |
|---|---|
| Meeting with attendees, occurred_at, source footer | ✅ pass |
| Meeting with empty body_md | ❌ `MISSING_SOURCE_FOOTER` |
| Meeting with `attendees=[]` | ❌ would fail nav-field check (but step 4 fitter would have run first; this is the safety net) |
| Doc without `doc_type` | ❌ `MISSING_REQUIRED_EXTENSION` |
| Note without `note_type` | ❌ `MISSING_REQUIRED_EXTENSION` |
| Concept with `sources.length < 2` | ❌ `INSUFFICIENT_EVIDENCE` |

For our meeting example: ✅ pass.

## Step 11 — Atomic persist

**Why:** insert the meeting + apply every reverse-edge update in ONE
Postgres transaction. Half-graphs forbidden.

**How:**

```python
return self.repo.save_with_reverse_edges(new_entity)
```

Inside `save_with_reverse_edges`:

```python
with transaction.atomic():
    entity.save()                                    # INSERT row

    for target_id in entity.sources:
        _append_applied_in(target_id, entity.id)     # → target.applied_in[]

    for target_id in entity.supersedes:
        _assign_superseded_by(target_id, entity.id)  # → target.superseded_by

    for target_id in entity.contradicts:
        _append_contradicts(target_id, entity.id)    # → target.contradicts[]
```

**Example end state:**

```
cortex_entities table:
  meeting_uuid    type=meeting  entity_refs=[alice-uuid, bob-uuid, acme-uuid, example-uuid]
                                sources=[]   supersedes=[]   contradicts=[]
  alice-uuid      type=person   (existing, unchanged)
  bob-uuid        type=person   (NEW — spawned in step 9)
  acme-uuid       type=org      (existing, unchanged)
  example-uuid    type=org      (NEW — spawned in step 9)
```

No `applied_in` writes for the meeting's `entity_refs` — that reverse
direction is derived at read time (see [`../03 - contracts/02-9-edges.md`](../03%20-%20contracts/02-9-edges.md)).

## TL;DR — Why each step

| # | Step | One-line value |
|---|---|---|
| 1 | OCR / markdownify | bytes → uniform markdown |
| 2 | TypeSpec lookup | pick the right rules for this type |
| 3 | Deterministic frontmatter | trust provider metadata (no LLM tax) |
| 4 | Fitter fallback | LLM only fills gaps, Pydantic-locked |
| 5 | Embed + cluster_assign | dynamic taxonomy from embeddings |
| 6 | Folder placement | every row has ONE canonical home |
| 7 | Render body | uniform shape → fast agent comparison |
| 8 | Build entity | content hash → idempotent re-ingest |
| 9 | Extract + resolve | mentions become typed edges → unified namespace |
| 10 | Linter gate | bad data blocked before it lands |
| 11 | Atomic persist | bidirectional graph stays consistent |
