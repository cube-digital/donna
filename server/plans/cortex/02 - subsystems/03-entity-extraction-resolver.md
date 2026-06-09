# Subsystem 3 — Entity Extraction + Resolution

**Concern:** for every Silver row we ingest, surface the **people /
orgs / projects / concepts** it mentions and bind them to typed
entity rows. This is what gives the agent the unified namespace —
"show me everything about Acme" — without storing duplicate copies.

## Plain English

A meeting talks about Alice (alice@acme.com) and a Stripe integration.
That meeting is, on its own, just a bag of text. But when we record it
in Cortex we want:

- A typed `person` row for Alice (so any future row mentioning her
  joins via `entity_refs` → her id)
- A typed `org` row for Acme (so the workspace can navigate
  `05 - People & Orgs/acme` and see everything Acme-related)
- A typed `concept` row for Stripe (so future content about Stripe
  joins this concept)

If those rows already exist, we link to them; if not, we **spawn**
them with full provenance.

End result: meeting carries `entity_refs = [alice_id, bob_id, acme_id]`.
The reverse view — "all rows mentioning Acme" — is derived at read
time via `find_referencing(acme_id, workspace_id)`.

## Two-stage pipeline

```
DeliveryPackage (with metadata)
       │
       ▼
   Extractor (chain of responsibility)
       │
       │  emits ExtractedEntity[] candidates
       ▼
   Resolver
       │
       │  → matches existing row OR spawns new one
       ▼
   target_id (UUID)
       │
       │  → writer appends to entity.entity_refs[]
       ▼
   CortexEntity persisted
```

## Stage 1 — Extractor (Chain of Responsibility)

`CompositeExtractor` runs registered extractors in order and dedupes
their output.

```python
class CompositeExtractor:
    def __init__(self, *extractors): ...

    def extract(self, *, entity, context):
        seen = set()
        merged = []
        for ext in self._extractors:
            for cand in ext.extract(entity=entity, context=context):
                key = (cand.type, cand.email, cand.domain, cand.label)
                if key in seen: continue
                seen.add(key)
                merged.append(cand)
        return merged
```

Default chain:

1. `ProviderMetadataExtractor` — deterministic, free, high-confidence
2. `GLiNERExtractor` (optional) — body-text NER, lower confidence,
   catches mentions the provider didn't tag

### `ProviderMetadataExtractor`

Walks `adapter.metadata()` for known shapes:

| Source | Field | Emits |
|---|---|---|
| Fathom | `host` (dict with email) | person candidate |
| Fathom | `participants[]` / `attendees[]` | person candidates |
| Gmail | `sender` | person candidate |
| Gmail | `recipients[]` / `to[]` / `cc[]` | person candidates |
| Drive | `owner` | person candidate |
| derived | non-public email domain | org candidate |

Public email domains (`gmail.com`, `yahoo.com`, `outlook.com`, etc.)
are filtered out — no spurious "Gmail Inc" or "Yahoo Inc" org rows.

```python
class ProviderMetadataExtractor:
    def extract(self, *, entity, context):
        meta = context.adapter_metadata or {}
        out = []

        for source in ("host", "sender", "owner"):
            obj = meta.get(source)
            if isinstance(obj, dict) and obj.get("email"):
                out.append(self._person(obj))

        for source in ("participants", "recipients", "to", "cc", "attendees"):
            for item in meta.get(source) or []:
                out.append(self._person(item))

        # Derive orgs from non-public domains
        for cand in list(out):
            if cand.email and "@" in cand.email:
                domain = cand.email.split("@", 1)[1].lower()
                if domain not in _PUBLIC_EMAIL_DOMAINS:
                    out.append(self._org(domain))
        return out
```

Confidence = `1.0` (provider-known) for persons, `0.9` for derived
orgs.

### `GLiNERExtractor` (optional, lazy-loaded)

Generalist NER trained on `["person", "org", "project", "concept"]`
labels. Runs on the body markdown after step 1 (OCR) so it sees
arbitrary text.

```python
class GLiNERExtractor:
    DEFAULT_MODEL = "urchade/gliner_medium-v2.1"

    def extract(self, *, entity, context):
        results = model.predict_entities(
            entity.body_md, ["person", "org", "project", "concept"],
            threshold=0.5,
        )
        return [ExtractedEntity(
            type=hit["label"], label=hit["text"], confidence=hit["score"],
            span=(hit["start"], hit["end"]), origin="gliner",
        ) for hit in results]
```

Off by default in the writer (`enable_gliner=False`) because it adds a
gliner+torch download. Workspaces opt in.

### `ExtractedEntity` dataclass

```python
@dataclass(frozen=True)
class ExtractedEntity:
    type: Literal["person", "org", "project", "concept"]
    label: str
    email: str | None
    domain: str | None
    confidence: float
    span: tuple[int, int] | None
    origin: Literal["provider", "gliner", "haiku_hint"]
```

## Stage 2 — Resolver

`DeterministicResolver.resolve(candidate, scope) → UUID`.

Match-or-spawn logic per type:

### `person`

| Step | Lookup |
|---|---|
| 1 | `extensions.primary_email == candidate.email` |
| 2 | `extensions.cross_workspace_aliases CONTAINS candidate.label` |
| 3 | **spawn** new person row |

Person rows are workspace-scoped (cross-client per spec §6).

### `org`

| Step | Lookup |
|---|---|
| 1 | `extensions.email_domains CONTAINS candidate.domain` |
| 2 | `extensions.cross_workspace_aliases CONTAINS candidate.label` |
| 3 | **spawn** new org row with `relationship: "client"` |

Spawned orgs default to `relationship: client`. Human/admin promotes
to `vendor` / `partner` / `internal` / `self` later via MCP API.

### `project` / `concept`

Alias-only lookup (no email/domain key). Spawn on miss.

### Spawn shape (every spawned row)

```python
def _spawn(self, *, entity_type, scope, title, body, extensions, ident, ...):
    spawn_id = uuid4()
    source_uri = f"cortex://spawn/{spawn_id}"
    content_hash = sha256(f"{entity_type}:{ident}")
    return CortexEntity.objects.get_or_create(
        workspace_id=scope.workspace_id,
        content_hash=content_hash,
        defaults={
            "id": spawn_id,
            "type": entity_type,
            "author": "donna",                # connector pipeline = donna
            "source": source_uri,             # cortex://spawn/...
            "bronze_storage_key": "",         # no bronze blob for spawned rows
            "occurred_at": now(),
            "client_id": ..., "project_id": ...,
            "title": title,
            "body_md": body,                  # ends with "Spawned by: cortex-resolver"
            "confidence": "medium",           # not human-verified
            "last_synthesized": today(),
            "extensions": extensions,
        },
    )
```

Every spawned row is **lint-valid**: has body footer
(`Spawned by: cortex-resolver`), has provenance, has typed extensions.

## Why `entity_refs` (not `applied_in` on the target) at write time

Spec §4 + spec §7 R9:

| Forward edge written by writer | Reverse | Maintenance |
|---|---|---|
| `entity_refs` (meeting mentions Alice) | NONE at write time | derived at read via `find_referencing` |

Reason: high cardinality. If Alice is mentioned in 5000 rows, her
`applied_in` would be 5000 UUIDs in JSONB → slow updates, big rows.

The query "every row mentioning Alice" uses the GIN index on
`entity_refs`:

```sql
SELECT * FROM cortex_entities
WHERE workspace_id = ? AND entity_refs @> '["alice-uuid"]'
ORDER BY occurred_at DESC;
```

GIN containment is O(log N) — cheap.

The three reverse edges that ARE maintained (`applied_in`,
`superseded_by`, `contradicts`) cover lower-cardinality relationships
where the back-pointer is queried much more often than the forward
side is updated.

## Concrete walk

```
Fathom meeting "Acme onboarding call"
  metadata: host=alice@acme.com, participants=[alice, bob@example.com]
       │
       ▼
ProviderMetadataExtractor:
  → ExtractedEntity(type=person, label="Alice", email=alice@acme.com, origin=provider)
  → ExtractedEntity(type=person, label="Bob", email=bob@example.com, origin=provider)
  → ExtractedEntity(type=org, label="Acme", domain=acme.com, origin=provider)
  → ExtractedEntity(type=org, label="Example", domain=example.com, origin=provider)
       │
       ▼
GLiNERExtractor (if enabled):
  → ExtractedEntity(type=concept, label="Stripe integration", origin=gliner)
       │
       ▼
CompositeExtractor dedupes:
  → 4 candidates (no duplicates this time)
       │
       ▼
DeterministicResolver per candidate:
  Alice  → existing person row → alice_id
  Bob    → no match → spawn person row → bob_id (NEW)
  Acme   → existing org row → acme_id
  Example→ no match → spawn org row "Example" → example_id (NEW)
       │
       ▼
entity_refs = [alice_id, bob_id, acme_id, example_id]
       │
       ▼
CortexEntity.entity_refs persisted
```

Two new rows in the workspace, all four ids in the meeting's
`entity_refs`. Future query "everything about Acme" via
`find_referencing(acme_id)` returns this meeting (and any other row
that referenced Acme).

## Concept spawning has a catch

Spec §7.2 hard-reject: concept with `sources.length < 2` →
`INSUFFICIENT_EVIDENCE`.

When the extractor surfaces "Stripe" from one meeting:
- We don't have 2 sources yet
- The resolver spawns the concept anyway (so the row exists)
- The linter would normally reject — but spawned concepts come in
  through `objects.create()` (bypasses CortexWriter)

This is a deliberate gap: spawned concepts are essentially "seeds"
waiting for human verification. Future R6 logic will gate them into
the curated layer once enough evidence accumulates.

## Failure modes

| Failure | Behaviour |
|---|---|
| Provider metadata is missing | extractor returns `[]`; writer continues |
| GLiNER not installed (and `enable_gliner=True`) | `ImportError` at first call |
| Email is malformed | filtered out (`@` check) |
| Workspace doesn't have a `self` org yet | new orgs spawn as `relationship: "client"` (safe default) |
| Multiple concurrent writes spawn the same Alice | `get_or_create` on `(workspace, content_hash)` → one wins, others get same row |

## Why deterministic > LLM-based resolution

| Approach | Pros | Cons |
|---|---|---|
| LLM ("is this Alice@acme.com the same as @alice from email X?") | flexible | non-deterministic, expensive, hallucinates |
| Deterministic (email primary, alias secondary) | predictable, free, reproducible | misses obvious cases (typos) |

Cortex picks deterministic for v1. LLM-based fallback is left as a
Resolver swap point — a workspace can register
`LLMResolver` via `extensions/typespecs/<workspace>/` to opt in.
