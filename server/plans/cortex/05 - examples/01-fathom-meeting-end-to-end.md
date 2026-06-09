# Example 1 — Fathom Meeting End-to-End

Walk one Fathom meeting from webhook to persisted CortexEntity row.
Every value annotated.

## The trigger

Fathom POSTs to Donna's webhook when a recording completes:

```http
POST /webhooks/fathom HTTP/1.1
X-Fathom-Signature: hmac-sha256 abc123...
Content-Type: application/json

{
  "event": "recording.completed",
  "recording": {
    "id": "rec-abc123",
    "title": "Acme onboarding call",
    "started_at": "2026-06-03T14:00:00Z",
    "duration_seconds": 1800
  }
}
```

The webhook handler verifies HMAC, then enqueues
`integrations.fathom.ingest_meeting(workspace_id, recording_id)`.

## Inside the Celery task

```python
@shared_task(name="integrations.fathom.ingest_meeting")
def ingest_meeting(workspace_id: str, recording_id: str) -> dict:
    # 1. Fetch from Fathom API
    raw = fathom_client.get_recording(recording_id)

    # 2. Write blob to bronze storage
    storage_key = f"{workspace_id}/fathom/meetings/{recording_id}.json"
    default_storage.save(storage_key, ContentFile(json.dumps(raw).encode()))

    # 3. Upsert DeliveryPackage row
    metadata = {
        "host": {"name": "Alice Smith", "email": "alice@acme.com"},
        "attendees": [
            {"name": "Alice Smith", "email": "alice@acme.com", "role": "host"},
            {"name": "Bob Lee", "email": "bob@example.com", "role": "attendee"},
        ],
        "duration_min": 30,
        "recording_url": "https://fathom.example/r/abc123",
        "fathom_meeting_id": "rec-abc123",
    }
    package, created = DeliveryPackage.objects.update_or_create(
        workspace_id=workspace_id,
        provider="fathom",
        provider_item_id=recording_id,
        defaults={
            "provider_item_type": "meeting",
            "title": "Acme onboarding call",
            "occurred_at": datetime(2026, 6, 3, 14, 0, tzinfo=timezone.utc),
            "metadata": metadata,
            "storage_key": storage_key,
        },
    )

    # 4. Cortex hop
    cortex_entity = CortexWriter().write(package)
    return {"cortex_entity_id": str(cortex_entity.id)}
```

## Inside CortexWriter.write(package)

### Step 1 — OCR / markdownify

```python
body_md = "# Acme onboarding call\n\nDiscussed Stripe integration..."
```

Fathom JSON shape → adapter renders transcript as markdown.

### Step 2 — TypeSpec lookup

```python
cortex_type = "meeting"
type_spec = MeetingSpec(
    extensions_model=MeetingExtensions,
    fit_model=None,
    template_path="meeting.j2",
    nav_fields=["attendees"],
    folder_resolver=TemporalFolderResolver(bucket="meetings"),
    version="meeting@v1",
)
```

### Step 3 — Deterministic frontmatter

```python
extensions = {
    "attendees": [
        {"name": "Alice Smith", "email": "alice@acme.com", "role": "host"},
        {"name": "Bob Lee",     "email": "bob@example.com", "role": "attendee"},
    ],
    "duration_min": 30,
    "recording_url": "https://fathom.example/r/abc123",
}
```

### Step 4 — Fitter

`nav_fields=["attendees"]`, attendees present → SKIP fitter. No LLM
call.

### Step 5 — Embed + cluster_assign

```python
# Sampled input — MeetingSpec uses uniform_sampler.
# Full body is short here (one paragraph), so sampler returns it as-is.
embedding = self.embedder.embed_entity(
    title="Acme onboarding call",
    body_md=body_md,
    sampler=meeting_spec.embedding_sampler,   # uniform_sampler
)
# → [0.12, -0.05, 0.31, ..., 0.04]  (384-dim, normalised)

scope = Scope(workspace_id=ws-qube, client_id=None, project_id=None)

cluster_id, cluster_name = self.clusterer.assign(embedding, scope)
# → (uuid-xyz-123, "Customer Onboarding")

extensions["cluster_name"] = "Customer Onboarding"
```

### Step 6 — Folder placement

```python
client_slug, project_slug = (None, None)   # not yet scoped to client

parent_path = type_spec.folder_resolver.canonical_path(
    type="meeting",
    occurred_at=datetime(2026, 6, 3, 14, 0, ...),
    extensions=extensions,
    client_slug=None,
    project_slug=None,
)
# → "meetings/2026/06"

slug = "2026-06-03-acme-onboarding-call-a4b2c8e1"
extensions["parent_path"] = "meetings/2026/06"
extensions["slug"]        = "2026-06-03-acme-onboarding-call-a4b2c8e1"
```

### Step 7 — Render body via Jinja

`body_md_final`:

```markdown
---
type: meeting
title: Acme onboarding call
occurred_at: 2026-06-03 14:00:00+00:00
parent_path: meetings/2026/06
slug: 2026-06-03-acme-onboarding-call-a4b2c8e1
template_version: meeting@v1
attendees:
  - "Alice Smith <alice@acme.com> (host)"
  - "Bob Lee <bob@example.com> (attendee)"
duration_min: 30
recording_url: "https://fathom.example/r/abc123"
cluster_name: "Customer Onboarding"
---

# Acme onboarding call

Discussed Stripe integration...

Source: fathom://meeting/rec-abc123 (ws-qube/fathom/meetings/rec-abc123.json)
```

### Step 8 — Build entity (unsaved)

```python
new_entity = CortexEntity(
    id                 = <auto uuid>,
    workspace_id       = ws-qube,
    type               = "meeting",
    author             = "donna",
    source             = "fathom://meeting/rec-abc123",
    bronze_storage_key = "ws-qube/fathom/meetings/rec-abc123.json",
    content_hash       = "sha256:a4b2c8e1...",
    occurred_at        = 2026-06-03 14:00:00+00:00,
    client_id          = None,
    project_id         = None,
    cluster_id         = uuid-xyz-123,
    doc_embedding      = [0.12, -0.05, ...],
    confidence         = "high",
    last_synthesized   = 2026-06-03,
    title              = "Acme onboarding call",
    body               = FileField(<rendered body written to SilverStorage>),
    body_byte_size     = len(body_md_final.encode("utf-8")),
    extensions         = extensions,
)
# Note: rendered body goes to S3 / filesystem at:
#   cortex/ws-qube/meeting/<entity-uuid>.md
# The PG row only carries a 500-char path pointer + byte size.
```

### Step 9 — Entity extraction + resolution

```
Provider extractor:
  → ExtractedEntity(type=person, label="Alice Smith", email=alice@acme.com,
                    confidence=1.0, origin=provider)
  → ExtractedEntity(type=person, label="Bob Lee", email=bob@example.com,
                    confidence=1.0, origin=provider)
  → ExtractedEntity(type=org, label="Acme", domain=acme.com,
                    confidence=0.9, origin=provider)
  → ExtractedEntity(type=org, label="Example", domain=example.com,
                    confidence=0.9, origin=provider)

Resolver:
  Alice  → existing person row alice-uuid (matched by email)
  Bob    → no match → SPAWN new person row bob-uuid
  Acme   → existing org row acme-uuid (matched by domain)
  Example→ no match → SPAWN new org row example-uuid

→ new_entity.entity_refs = [alice-uuid, bob-uuid, acme-uuid, example-uuid]
```

Two new rows spawned. Both have:

```python
{
    "author": "donna",
    "source": "cortex://spawn/<uuid>",
    "bronze_storage_key": "",
    "confidence": "medium",
    "body_md": "# Bob Lee\n\n_Spawned by the Cortex resolver._\n\nSpawned by: cortex-resolver",
    "extensions": {
        "full_name": "Bob Lee",
        "primary_email": "bob@example.com",
        "cross_workspace_aliases": ["Bob Lee"],
    },
}
```

### Step 10 — Linter gate

All checks pass:
- type ∈ 12-value Literal ✅
- author ∈ {donna, human, agent} ✅
- occurred_at present ✅
- scope valid (client_id null → project_id must also be null ✅)
- Pydantic extensions valid against MeetingExtensions ✅
- supersedes deduped ✅
- cross_refs is list ✅
- no ad-hoc edge keys ✅
- body footer starts with `Source:` ✅
- meeting has no `INSUFFICIENT_EVIDENCE` rule
- no `MISSING_REQUIRED_EXTENSION` for meeting type

→ Pass.

### Step 11 — Atomic persist

```sql
BEGIN;
INSERT INTO cortex_entities (id, workspace_id, type, ..., entity_refs)
  VALUES (..., '["alice-uuid","bob-uuid","acme-uuid","example-uuid"]');

-- No sources, supersedes, contradicts → no reverse-edge updates
COMMIT;
```

The two new spawned rows (bob, example) were INSERTed during step 9's
`Resolver._spawn()` calls — already in the DB before step 11.

## Final state — Postgres after the write

```
cortex_entities table:
  id                 type      title                        author   source                          extensions.parent_path
  ----------------------------------------------------------------------------------------------------------------------------
  meeting-uuid       meeting   Acme onboarding call         donna    fathom://meeting/rec-abc123     meetings/2026/06
  alice-uuid         person    Alice Smith                  donna    cortex://spawn/<uuid>           people
  bob-uuid (NEW)     person    Bob Lee                      donna    cortex://spawn/<uuid>           people
  acme-uuid          org       Acme                         donna    cortex://spawn/<uuid>           clients/acme
  example-uuid (NEW) org       Example                      donna    cortex://spawn/<uuid>           clients/example
```

## What an agent can now do

### Query 1 — "what meetings happened in June?"

```sql
SELECT * FROM cortex_entities
WHERE workspace_id = 'ws-qube'
  AND type = 'meeting'
  AND occurred_at >= '2026-06-01' AND occurred_at < '2026-07-01';
```

Returns the Acme onboarding meeting (plus any other June meetings).

### Query 2 — "show me everything about Acme"

```sql
SELECT * FROM cortex_entities
WHERE workspace_id = 'ws-qube'
  AND entity_refs @> '["acme-uuid"]'
ORDER BY occurred_at DESC;
```

GIN index on `entity_refs`. Returns the Acme onboarding meeting (and
any other Cortex row mentioning Acme).

### Query 3 — "show me Alice's recent activity"

```sql
SELECT * FROM cortex_entities
WHERE workspace_id = 'ws-qube'
  AND entity_refs @> '["alice-uuid"]'
ORDER BY occurred_at DESC
LIMIT 30;
```

Same GIN index. Returns every row mentioning Alice.

### Query 4 — "what's clustered as Customer Onboarding?"

```sql
SELECT * FROM cortex_entities
WHERE workspace_id = 'ws-qube'
  AND cluster_id = 'uuid-xyz-123'
ORDER BY occurred_at DESC;
```

Index on `cluster_id`. Returns every row in the Customer Onboarding
cluster.

## Final body_md (what an Obsidian user sees)

```markdown
---
type: meeting
title: Acme onboarding call
occurred_at: 2026-06-03 14:00:00+00:00
parent_path: meetings/2026/06
slug: 2026-06-03-acme-onboarding-call-a4b2c8e1
template_version: meeting@v1
attendees:
  - "Alice Smith <alice@acme.com> (host)"
  - "Bob Lee <bob@example.com> (attendee)"
duration_min: 30
recording_url: "https://fathom.example/r/abc123"
cluster_name: "Customer Onboarding"
---

# Acme onboarding call

Discussed Stripe integration...

Source: fathom://meeting/rec-abc123 (ws-qube/fathom/meetings/rec-abc123.json)
```

Predictable shape. Provenance pointer. Closed-vocab frontmatter.
Verbatim body. The agent compares this exactly the same way it
compares any other meeting in the workspace.
