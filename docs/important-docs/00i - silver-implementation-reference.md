# Silver Implementation Reference — developer handbook

> **Audience:** developers implementing the
> [Silver Layer Completion Plan](./00f%20-%20silver-completion-plan.md)
> (the *what/why* — 7 phases, ~19 working days). This doc is the *how*:
> file-by-file change maps and **target-state code** per phase, so
> implementation never re-derives the 2026-06-11/12 design decisions.
>
> **Status:** drafted 2026-06-12 from the approved implementation
> blueprint. Code blocks are starting points written against verified
> current signatures — refine while implementing, keep the contracts.
>
> **Companions:** [`00a`](./00a%20-%20how-it-comes-together.md) narrative ·
> [`00b`](./00b%20-%20design-debate-qa.md) pushbacks ·
> [`00f`](./00f%20-%20silver-completion-plan.md) master plan ·
> [`00g`](./00g%20-%20mcp-implementation-guide.md) MCP deep-dive ·
> [`00h`](./00h%20-%20ask-donna-roadmap.md) Q&A critical path ·
> [`00j`](./00j%20-%20agent-implementation-reference.md) chat agent handbook.

**Settled design inputs** (all dated 2026-06-11/12, recorded in 00f):
scope ladder T0–T4 + pipeline reorder, canonical adapter models
(narrio pattern), classifier tiers A/B/B+/C, linter **slim** +
TYPE_AUTHORITY stays, `CortexWriter → CortexPipeline`, `types.py`
collapse, extractor split, ocr-shim deletion, `(None, project)` scope
relaxation.

**Verified code facts this doc builds on:** `_build_extensions`
if-chain (`pipeline.py:313–368`), `HaikuFitter` `text[:8000]`
(`template_engine.py:67`), Drive unwired, bronze delete+save,
`BaseAdapter` contract (`external_id/title/occurred_at/to_json`
required), `DeliveryPackage(provider, provider_item_id,
provider_item_type, title, occurred_at, metadata, storage_key)`,
`CortexEntityManager` in `models.py`, `BaseService(current_user,
company)`.

---

## §0 Orientation

- Three-planes recap + invariants box: scope boundary, suggestion-only inference (T0 exception), heads-only reads, files-as-truth, bronze immutability.
- **Module fate map** (the doc's anchor table):

| File today | Fate | Phase |
|---|---|---|
| `models.py` (manager inside) | manager → `managers.py` | 0 |
| `repository.py` | already deleted (manager) | done |
| `templates/*.py` ×12 | → one `types.py` | 0 |
| `registry.py` | shrinks to TypeSpec + dict | 0 |
| `folders.py` classes ×9 | → plain functions | 0 |
| `storage.py`, `SilverEntity`, `ClusteringService`, `DerivedNamespaceView` | delete (+ `__main__` demo fallout, `test_derived_view.py`) | 0 |
| `linter.py` | slim (4 checks stay) | 0 prep, 2 final |
| `authority.py` | stays | — |
| `ocr.py` | delete (sidecar replaces) | 1 |
| `pipeline.py` `CortexWriter` | rename `CortexPipeline`, reorder, `_build_extensions` deleted | 0 rename, 2+4 surgery |
| `entities.py` extractors | pure parts → `core/extractors/entities/` | 0 |
| `core/integrations/adapter.py` | `to_text/to_markdown` dropped; `BaseEntityAdapter` added | 1–2 |

## §1 Phase 0 (~2d) — cleanup + cheap correctness

**`donna/cortex/managers.py` (new)** — move `CortexEntityManager` verbatim from models.py; models.py imports it. ~5-line diff shown.

**`donna/cortex/types.py` (new — replaces 12 template .py files):**

```python
"""Declarative TypeSpec table — single source for all 12 types."""
from donna.cortex import folders, schemas
from donna.cortex.embeddings import (
    fixed_window_sampler, head_heavy_sampler, head_tail_sampler, uniform_sampler,
)
from donna.cortex.registry import TypeSpec, register_type

SPECS: tuple[TypeSpec, ...] = (
    TypeSpec("meeting",  schemas.MeetingExtensions,  None,                 "meeting.j2",  ["attendees"], folders.temporal("meetings"), "meeting@v1",  uniform_sampler),
    TypeSpec("email",    schemas.EmailExtensions,    None,                 "email.j2",    [],            folders.temporal("emails"),   "email@v1",    head_heavy_sampler),
    TypeSpec("chat",     schemas.ChatExtensions,     None,                 "chat.j2",     [],            folders.chat,                 "chat@v1",     head_heavy_sampler),
    TypeSpec("doc",      schemas.DocExtensions,      schemas.DocExtensions,"doc.j2",      ["doc_type"],  folders.flat("docs"),         "doc@v1",      head_tail_sampler),
    TypeSpec("ticket",   schemas.TicketExtensions,   None,                 "ticket.j2",   [],            folders.ticket,               "ticket@v1",   head_heavy_sampler),
    TypeSpec("clip",     schemas.ClipExtensions,     None,                 "clip.j2",     [],            folders.flat("clips"),        "clip@v1",     fixed_window_sampler),
    TypeSpec("note",     schemas.NoteExtensions,     schemas.NoteExtensions,"note.j2",    ["note_type"], folders.flat("notes"),        "note@v1",     fixed_window_sampler),
    TypeSpec("person",   schemas.PersonExtensions,   None,                 "person.j2",   [],            folders.person,               "person@v1",   fixed_window_sampler),
    TypeSpec("org",      schemas.OrgExtensions,      None,                 "org.j2",      [],            folders.org,                  "org@v1",      fixed_window_sampler),
    TypeSpec("project",  schemas.ProjectExtensions,  None,                 "project.j2",  [],            folders.project,              "project@v1",  fixed_window_sampler),
    TypeSpec("concept",  schemas.ConceptExtensions,  None,                 "concept.j2",  [],            folders.concept,              "concept@v1",  fixed_window_sampler),
    TypeSpec("decision", schemas.DecisionExtensions, None,                 "decision.j2", [],            folders.decision,             "decision@v1", head_tail_sampler),
)

for spec in SPECS:
    register_type(spec)
```

`apps.py ready()` → `import donna.cortex.types  # noqa: F401` (discovery walk deleted).

**`folders.py` — classes → functions** (same kwargs contract, `TypeSpec.folder_resolver` becomes a callable):

```python
def temporal(bucket: str) -> FolderFn:
    def path(*, type, occurred_at, extensions, client_slug, project_slug) -> str:
        scope = _scope_prefix(client_slug, project_slug)
        if occurred_at is None:
            return _join(scope, bucket, "unknown")
        year, month = _year_month(occurred_at)
        return _join(scope, bucket, year, month)
    return path

def flat(bucket: str) -> FolderFn: ...
def chat(*, extensions, client_slug, project_slug, **_) -> str: ...      # chats/<channel>
def ticket(*, extensions, client_slug, project_slug, **_) -> str: ...    # tickets/<provider>
def person(**_) -> str: return "people"
def concept(**_) -> str: return "concepts"
def org(*, extensions, client_slug, **_) -> str: ...                     # self → "" | clients/<slug>
def project(*, client_slug, project_slug, **_) -> str: return _scope_prefix(client_slug, project_slug)
def decision(*, client_slug, project_slug, **_) -> str: ...              # <scope>/decisions
```

**`donna/cortex/doc_classifier.py` (new) — tier A full implementation:**

```python
"""doc_type classification ladder. Phase 0 ships tier A; B in Phase 4; B+ in Phase 6."""
import re
from dataclasses import dataclass

@dataclass(frozen=True)
class Classification:
    doc_type: str | None
    confidence: float
    basis: str          # "mime" | "filename" | "anchor" | "knn" | "tfidf" | "llm"

_MIME_MAP = {
    "application/vnd.ms-powerpoint": "presentation",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "presentation",
}
_FILENAME_SIGNALS = [               # (compiled regex on filename, doc_type)
    (re.compile(r"\b(nda|non.disclosure)\b", re.I), "contract"),
    (re.compile(r"\b(contract|agreement|sow|statement.of.work)\b", re.I), "contract"),
    (re.compile(r"\b(invoice)\b", re.I), "other"),
    (re.compile(r"\b(offer|proposal)\b", re.I), "offer"),
    (re.compile(r"\b(runbook|playbook)\b", re.I), "runbook"),
    (re.compile(r"\b(spec|specification)\b", re.I), "spec"),
]
_BODY_ANCHORS = [                   # (regex on body, doc_type, confidence)
    (re.compile(r"\bWHEREAS\b.*\bIN WITNESS WHEREOF\b", re.S), "contract", 0.95),
    (re.compile(r"\bRevision History\b.*\bTable of Contents\b", re.S | re.I), "spec", 0.8),
    (re.compile(r"^#+\s*Runbook\b", re.M | re.I), "runbook", 0.85),
]

class HeuristicDocClassifier:
    def classify(self, *, filename: str = "", mime: str = "", body_md: str = "") -> Classification:
        if mime in _MIME_MAP:
            return Classification(_MIME_MAP[mime], 0.95, "mime")
        for rx, dt in _FILENAME_SIGNALS:
            if rx.search(filename):
                return Classification(dt, 0.85, "filename")
        head_tail = body_md[:4000] + body_md[-2000:]
        for rx, dt, conf in _BODY_ANCHORS:
            if rx.search(head_tail):
                return Classification(dt, conf, "anchor")
        return Classification(None, 0.0, "anchor")
```

**Linter slim — final `FrontmatterLinter`** (removed checks move to
the canonical Pydantic models, Phase 2 — see §3):

```python
class FrontmatterLinter:
    """Slim gate: only invariants Pydantic can't express (decision 2026-06-11).

    Removed → enforced by canonical models at the adapter boundary (Phase 2):
    _check_type, _check_author, _check_temporal, _check_extensions,
    _check_required_{evidence,context,doc_type,note_type}.
    """
    def check(self, entity, body_md: str | None = None) -> None:
        self._check_scope(entity)          # leak guard — relaxed rule below
        self._check_supersedes(entity)     # no dup targets
        self._check_known_edges(entity)    # vs KNOWN_EDGE_FIELDS (fixed)
        self._check_source_footer(entity, body_md)

    def _check_scope(self, entity) -> None:
        # 2026-06-11: (client_id=None, project_id=set) now ALLOWED —
        # workspace-internal projects file at projects/<slug>/. The only
        # invalid state left: nothing. Check retained as extension point +
        # cross-scope ref validation when cross_refs present.
        ...
    def _check_known_edges(self, entity) -> None:
        unknown = set((entity.extensions or {})) & KNOWN_EDGE_FIELDS
        if unknown:
            raise LinterError(RejectCode.UNKNOWN_EDGE_TYPE, f"edge fields in extensions: {sorted(unknown)}")
```

**Correctness fixes (snippets in doc):**
- `HaikuFitter.fit` — replace `text[:8000]` with sampler: `sampled = sampler("", text)` (sampler passed in or `head_tail_sampler` default).
- Cosine floor: `HDBSCANClusterer.__init__(..., min_similarity: float = 0.55)`; in `assign()`: `if best_score < self._min_similarity: return None, None`.
- `_spawn` through linter + manager (replace `row.save(); row.body.save(...)` double-write with `CortexEntity.objects.save_with_reverse_edges(row, body_bytes=...)` after `FrontmatterLinter().check(row, body_md=body)`).
- Reverse-edge writers: missing target → `logger.warning(...)` + `if settings.DEBUG: raise`.
- `core/extractors/entities/` move: `base.py` (protocol), `provider.py`, `gliner.py`, `composite.py` — import-path table; `DeterministicResolver` stays in cortex.

**Phase 0 tests list** (concrete test functions, ~12 names with assertion intent).

## §2 Phase 1 (~2d)

**Versioned bronze keys** — helper + connector diff:

```python
def bronze_key(ws_id, provider, kind, item_id, content: bytes) -> str:
    sha8 = hashlib.sha256(content).hexdigest()[:8]
    return f"{ws_id}/{provider}/{kind}/{item_id}/{sha8}.json"
# tasks: NEVER default_storage.delete(key) before save — new content → new key.
# DeliveryPackage.storage_key updated to newest version.
```

**`.extracted.md` sidecar** at ingest + `_body_for()` rewrite (prefer sidecar → canonical-payload render → core OCR fallback) + delete `cortex/ocr.py`.

**Two-tier dedup at step 2½** (exact block, lives in reordered pipeline):

```python
source_uri = self._source_uri(dp)
content_hash = hashlib.sha256(raw_body.encode()).hexdigest()
head = (CortexEntity.objects
        .filter(workspace_id=dp.workspace_id, source=source_uri, superseded_by__isnull=True)
        .first())
if head is not None:
    if head.content_hash == content_hash:
        return head                                  # replay — full stop, nothing else runs
    supersedes = [str(head.id)]                      # new version
```

**Supersession side effect** in `CortexEntityManager._assign_superseded_by`: ancestor `doc_embedding=None; cluster_id=None` (body untouched — R1).

**Heads-only migration** (partial indexes):

```python
migrations.AddIndex("cortexentity", models.Index(
    fields=["workspace", "type", "-occurred_at"],
    condition=Q(superseded_by__isnull=True), name="cortex_heads_type_time"))
```

## §3 Phase 2 (~2d)

**Pattern source (user-designated reference): `narrio/narrio/core/adapters/`** —
the doc mirrors its idioms exactly: `BaseAdapter[T].from_source(raw) -> T | None`
generic ABC; canonical Pydantic models carrying `source` + `source_id`
provenance; a `parsers.py` of provider-agnostic coercion helpers
(`parse_optional_datetime/int/bool`, `normalize_url`) plugged in via
`field_validator(mode="before")` so messy provider payloads (HubSpot
"true"/"false" strings, Z-suffixed dates) normalize at the model boundary.

**Layout (new):**

```
donna/core/integrations/canonical/
├── __init__.py        # re-exports
├── models.py          # the canonical Pydantic models below
├── parsers.py         # ported narrio parsers (datetime/int/bool/url coercion)
└── base.py            # BaseAdapter[T]
```

**`base.py`:**

```python
T = TypeVar("T")

class BaseAdapter(ABC, Generic[T]):
    """Transforms source-specific raw data into one canonical model.

    One adapter per (provider, entity). Mirrors narrio core.adapters.
    """
    provider: ClassVar[str]            # "fathom" | "gmail" | "hubspot" …
    canonical_type: ClassVar[str]      # discriminator value it emits

    @abstractmethod
    def from_source(self, raw: dict[str, Any]) -> T | None:
        """Return the canonical instance, or None when raw is unusable
        (caller logs + skips — no half-built models)."""
        ...
```

**`models.py`** (pattern below — replicate for all 10 canonical
types; narrio-style `field_validator(mode="before")` coercion):

```python
class CanonicalBase(BaseModel):
    model_config = ConfigDict(extra="allow")        # provider extras ride along
    source: str                                     # provider slug — provenance
    source_id: str                                  # provider's stable id
    title: str
    occurred_at: datetime | None = None

    @field_validator("occurred_at", mode="before")
    @classmethod
    def _dt(cls, v): return parse_optional_datetime(v) if isinstance(v, str) else v

class CanonicalMeeting(CanonicalBase):
    canonical_type: Literal["meeting"] = "meeting"
    attendees: list[Attendee] = Field(default_factory=list)
    duration_min: int | None = None
    recording_url: str | None = None

    @field_validator("duration_min", mode="before")
    @classmethod
    def _mins(cls, v): return parse_optional_int(v)

class CanonicalDoc(CanonicalBase):
    canonical_type: Literal["doc"] = "doc"
    doc_type: DocType | None = None                 # None → classifier ladder fills
    mime: str | None = None
    owner_email: str | None = None
    parent_folder: str | None = None                # T0 scope signal

class CanonicalProject(CanonicalBase):              # CRM Deal lands here
    canonical_type: Literal["project"] = "project"
    status: ProjectStatus = "proposed"
# … CanonicalEmail/Chat/Ticket/Clip/Note/Org/Person same pattern
CanonicalEntity = Annotated[Union[...], Field(discriminator="canonical_type")]
```

**Concrete adapter example (Fathom):**

```python
class FathomMeetingAdapter(BaseAdapter[CanonicalMeeting]):
    provider = "fathom"
    canonical_type = "meeting"

    def from_source(self, raw: dict[str, Any]) -> CanonicalMeeting | None:
        if not raw.get("id"):
            return None
        return CanonicalMeeting(
            source="fathom", source_id=str(raw["id"]),
            title=raw.get("title") or "Untitled",
            occurred_at=raw.get("started_at"),          # str → validator coerces
            attendees=[Attendee(name=a.get("name"), email=a.get("email"))
                       for a in raw.get("attendees", [])],
            duration_min=(raw.get("duration_seconds") or 0) // 60 or None,
            recording_url=raw.get("recording_url"))
# HubSpot adapter set: CompanyAdapter→CanonicalOrg, DealAdapter→CanonicalProject(status="proposed"),
# ContactAdapter→CanonicalPerson — multi-entity sync = a list of BaseAdapter[T] per provider.
```

**`DeliveryPackage` migration**: add `canonical_type = CharField(16)`; canonical JSON stored in existing `metadata` field (no second JSON column). Pipeline: `canonical = parse_canonical(dp)`; `extensions = canonical.model_dump(exclude={"external_id","title","occurred_at","source_provider","canonical_type"})`; **delete `_build_extensions` + `_merge_fit` shrinkage**; `_attendees/_participants/_emails` helpers die.

**Drive wiring** — mirror Gmail lines 114–126 + `DriveDocAdapter` emitting `CanonicalDoc`.

**Linter slim lands here** (canonical models now enforce what the removed checks did).

## §4 Phase 3 (~1d) — cluster identity continuity

```python
def _recluster_scope(scope: Scope) -> None:
    old = clusterer._compute_centroids(scope)                  # {uuid: (centroid, name)}
    remap = clusterer.recluster(scope)                          # {entity_id: new_label_uuid|None}
    new_centroids = _centroids_by_label(remap, scope)
    matches: dict[UUID, UUID] = {}                              # new_uuid → old_uuid (greedy ≥0.80)
    for new_id, c_new in sorted_by_size(new_centroids):
        best_old, score = argmax_cosine(c_new, old, exclude=matches.values())
        if score >= 0.80:
            matches[new_id] = best_old
    for entity_id, label in remap.items():
        final = matches.get(label, label)
        name = old[matches[label]][1] if label in matches else HaikuNamer().name(samples(label))
        CortexEntity.objects.filter(id=entity_id).update(cluster_id=final,
            extensions=jsonb_set("cluster_name", name))
```

Tests: shuffle-stability (every UUID+name survives), genuine split (dominant keeps UUID, exactly one new), Haiku called only for unmatched (mock).

## §5 Phase 4 (~4.5d) — the big section

**5a. Reordered `CortexPipeline.write()`** (annotated skeleton — final step order):

```python
def write(self, dp: DeliveryPackage) -> CortexEntity:
    canonical = parse_canonical(dp)                                      # Phase 2
    body_md = self._body_for(dp, canonical)                              # 1 sidecar-first
    type_spec = self.registry.get(canonical.canonical_type)              # 2
    head_or_none = self._dedup(dp, body_md)                              # 2½ bail early
    if isinstance(head_or_none, CortexEntity): return head_or_none
    extensions = canonical_extensions(canonical)                          # 3
    extensions = self._fit_missing(extensions, type_spec, body_md)        # 4 (ladder A→…→C for doc)
    refs, spawned = self._extract_and_resolve(body_md, canonical)         # 4½ moved up
    scope, suggestion = self.scope_resolver.resolve(dp, canonical, refs)  # 4¾ T0 writes / T1+ suggest
    parent_path, slug = self._place(type_spec, canonical, extensions, scope)  # 5 real slugs
    body_final = self.engine.render(...)                                  # 6 refs → [[wikilinks]]
    entity = self._build_entity(..., suggested_scope=suggestion)          # 7
    self.linter.check(entity, body_md=body_final)                         # 8 slim gate
    entity = CortexEntity.objects.save_with_reverse_edges(entity, body_bytes=body_final.encode())  # 9
    transaction.on_commit(lambda: enrich_entity.delay(str(entity.id)))    # 10 → Task 2 (5e):
    return entity                                                         #    embed/cluster/T2/GLiNER async
```

**5b. `donna/cortex/scope.py` (new) — the ladder:**

```python
@dataclass(frozen=True)
class ScopeSuggestion:
    client_id: UUID | None
    project_id: UUID | None
    basis: str            # "provider-direct" | "participant-domain" | "llm-contextual"
    confidence: float

class ScopeResolver:
    def resolve(self, dp, canonical, refs) -> tuple[Scope, ScopeSuggestion | None]:
        ws = dp.workspace_id
        direct = self._t0_provider_direct(dp, canonical)        # mapping table, human-confirmed
        if direct:
            return Scope(ws, direct.client_id, direct.project_id), None   # T0 WRITES
        t1 = self._t1_participants(ws, canonical)               # domains → org rows
        return Scope(ws), t1                                    # suggestion only

    def _t1_participants(self, ws, canonical) -> ScopeSuggestion | None:
        domains = {e.split("@",1)[1].lower() for e in _emails(canonical)} \
                  - _PUBLIC_EMAIL_DOMAINS - {self._self_domain(ws)}
        orgs = [o for d in domains for o in CortexEntity.objects.filter(
                    workspace_id=ws, type="org",
                    extensions__email_domains__contains=[d],
                    extensions__relationship="client")]
        if len({o.id for o in orgs}) != 1:
            return None                                          # silence over guessing
        client = orgs[0]
        project = self._alias_match(ws, client.id, canonical.title)
        return ScopeSuggestion(client.id, project and project.id, "participant-domain",
                               0.7 if project is None else 0.8)
```

**T2 — cluster assist** (runs after step 5, once the embedding
exists; sanity-check, never a source of record):

```python
def t2_adjust(self, t1: ScopeSuggestion | None, embedding, ws) -> ScopeSuggestion | None:
    """Conflict matrix (00f §4c): agree → boost; silent → keep;
    T1-silent+cluster-says → review-flag only; disagree → suppress."""
    cluster_scope = self._dominant_scope_of_nearest_centroid(embedding, ws)  # Scope | None
    if t1 is None:
        if cluster_scope is not None:
            self._flag_for_review(ws, cluster_scope)        # no suggestion written
        return None
    if cluster_scope is None:
        return t1                                           # baseline confidence
    if (cluster_scope.client_id, cluster_scope.project_id) == (t1.client_id, t1.project_id):
        return replace(t1, confidence=min(t1.confidence + 0.15, 0.95))
    return None                                             # mismatch = noise → suppress
```

**T3 — Haiku contextual** (only when T1+T2 silent; closed candidate
list — can never invent a name; abstain allowed):

```python
class ScopePick(BaseModel):
    client_id: UUID | None = None
    project_id: UUID | None = None
    abstain: bool = False

def t3_llm(self, ws, body_md, canonical) -> ScopeSuggestion | None:
    candidates = list(CortexEntity.objects.filter(
        workspace_id=ws, type__in=("org", "project")).values("id", "type", "title"))
    if not candidates:
        return None                                          # cold workspace → skip
    prompt = _T3_PROMPT.format(candidates=json.dumps(candidates, default=str),
                               body=head_tail_sampler("", body_md, max_chars=3000))
    pick = HaikuFitter().fit(prompt, ScopePick)              # structured output
    if pick.abstain or pick.client_id is None:
        return None
    return ScopeSuggestion(pick.client_id, pick.project_id,
                           "llm-contextual", 0.5)            # always below T1
```

**Promotion path** (`CortexService.update_entity` PATCH accepting
`client_id`/`project_id` — the deliberate act):

```python
def promote_scope(self, entity, *, client_id, project_id) -> CortexEntity:
    entity.client_id, entity.project_id = client_id, project_id
    spec = self.registry.get(entity.type)
    client_slug, project_slug = self._scope_slugs(entity)
    new_parent = spec.folder_resolver(type=entity.type, occurred_at=entity.occurred_at,
        extensions=entity.extensions, client_slug=client_slug, project_slug=project_slug)
    old_name = entity.body.name
    body = entity.load_body()
    entity.extensions["parent_path"] = new_parent
    entity.body.save(name=f"{entity.id}.md", content=ContentFile(body.encode()), save=False)
    default_storage.delete(old_name)                          # silver moves; bronze never
    if entity.doc_embedding is not None:                      # re-cluster in new scope
        entity.cluster_id, name = self.clusterer.assign(
            entity.doc_embedding, Scope(entity.workspace_id, client_id, project_id))
        entity.extensions["cluster_name"] = name
    entity.extensions.pop("suggested_scope", None)            # consumed
    entity.save()
    return entity
```

**5c. `CortexService(BaseService)` — 8 methods + RRF query** (signatures + the SQL):

```sql
WITH filtered AS (
  SELECT id FROM cortex_entities
  WHERE workspace_id = %(ws)s AND superseded_by IS NULL
    AND (%(type)s IS NULL OR type = %(type)s)
    AND (%(doc_type)s IS NULL OR extensions->>'doc_type' = %(doc_type)s)
    AND (%(client)s IS NULL OR client_id = %(client)s)          -- metadata FIRST
), graph AS (SELECT id, row_number() OVER (...) rk FROM filtered WHERE entity_refs @> %(refs)s),
   vec   AS (SELECT id, row_number() OVER (ORDER BY doc_embedding <=> %(q)s) rk FROM filtered ...),
   kw    AS (SELECT id, row_number() OVER (ORDER BY ts_rank(tsv, query) DESC) rk FROM filtered ...)
SELECT id, SUM(1.0/(60+rk)) AS rrf FROM (...) GROUP BY id
ORDER BY rrf DESC, authority DESC, occurred_at DESC LIMIT %(k)s;
```

`tsvector` generated-column migration + DRF wiring per 03-conventions (PATCH-only, `service_class`, `StandardJSONRenderer`).

**5d. MCP server skeleton** (`cortex/mcp/server.py`, fastmcp, 8 tools 1:1, `--read-only` → 4, stdio + streamable-http, `DONNA_WORKSPACE_ID` binding) — condensed from 00g with working tool example:

```python
@mcp.tool()
def cortex_query(text: str, type: str | None = None, doc_type: str | None = None,
                 client_id: str | None = None, limit: int = 10) -> list[dict]:
    """Hybrid search. Filters run before similarity. Returns heads only."""
    return [e.summary() for e in _svc().query(text=text, type=type,
            doc_type=doc_type, client_id=client_id, limit=limit)]
```

**5e. Write-path split: persist fast, enrich async** (00f §4d — two
tasks; architecture decision 2026-06-12):

`CortexPipeline.write()` (Task 1) drops step 5 entirely — no model
load on the write path. The connector task dispatches enrichment
after commit:

```python
# donna/cortex/pipeline.py — end of write(), replaces the step-5 block
entity = CortexEntity.objects.save_with_reverse_edges(entity, body_bytes=body_final.encode())
transaction.on_commit(lambda: enrich_entity.delay(str(entity.id)))
return entity
```

```python
# donna/cortex/tasks.py (new task — Task 2)
@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def enrich_entity(self, entity_id: str) -> None:
    """Model-bound enrichment: embedding, cluster, T2 scope assist, GLiNER.

    Idempotent. Skips rows superseded while queued. Never touches the
    body file (R1) — everything it writes is plane-2 index state.
    """
    entity = (CortexEntity.objects
              .filter(id=entity_id, superseded_by__isnull=True)
              .first())
    if entity is None:
        return                                          # superseded/deleted — no-op

    spec = TemplateRegistry().get(entity.type)
    body = entity.load_body()

    embedding = BGESmallEmbedder().embed_entity(
        title=entity.title, body_md=body, sampler=spec.embedding_sampler)
    scope = Scope(entity.workspace_id, entity.client_id, entity.project_id)
    cluster_id, cluster_name = HDBSCANClusterer().assign(embedding, scope)

    # T2 scope assist lives HERE — it needs the embedding.
    resolver = ScopeResolver()
    suggestion = resolver.t2_adjust(
        _stored_suggestion(entity), embedding, entity.workspace_id)

    if getattr(settings, "CORTEX_ENABLE_GLINER", False):
        extra = GLiNERExtractor().extract(entity=entity, context=ExtractContext({}))
        entity.entity_refs = _merge_refs(entity.entity_refs, resolver, extra, scope)

    entity.doc_embedding = embedding
    entity.cluster_id = cluster_id
    entity.extensions["cluster_name"] = cluster_name
    if suggestion is not None:
        entity.extensions["suggested_scope"] = asdict(suggestion)
    else:
        entity.extensions.pop("suggested_scope", None)   # T2 suppressed it
    entity.save(update_fields=[
        "doc_embedding", "cluster_id", "entity_refs", "extensions", "updated_at"])
```

Consequences encoded with the split:
- **`cluster_name` leaves the body templates** — plane-2 datum inside
  an immutable plane-1 artifact was a layering bug; `_index.md` and
  query results surface it from `extensions`.
- Backfill = bulk `enrich_entity.delay(...)` over ids; the
  `cortex_sync --reindex-embeddings` command becomes a thin enqueuer.
- Tests: persist path asserts no model import (mock
  `sentence_transformers` import hook); enrich on superseded row
  no-ops; on_commit ordering; double-enrich idempotent.

**5f. Classifier tier B** (kNN over pgvector — same PR as 4c):

```python
def knn_doc_type(embedding, ws_id, k=7, floor=0.6) -> Classification:
    rows = (CortexEntity.objects
        .filter(workspace_id=ws_id, type="doc", superseded_by__isnull=True,
                extensions__doc_type__isnull=False, doc_embedding__isnull=False)
        .annotate(dist=CosineDistance("doc_embedding", embedding))
        .order_by("dist").values_list("extensions__doc_type", "dist")[:k])
    votes = defaultdict(float)
    for dt, dist in rows:
        if (sim := 1 - dist) >= floor: votes[dt] += sim
    if not votes: return Classification(None, 0.0, "knn")
    best, score = max(votes.items(), key=lambda kv: kv[1])
    return Classification(best, min(score / sum(votes.values()), 0.99), "knn")
```

## §6 Phase 5 (~3d) — shipped 2026-06-19

**Files added/changed:**

| Path | Role |
|---|---|
| `donna/cortex/vault_renderer.py` (new, ~310 lines) | `VaultRenderer` + `_augment_frontmatter` + `parse_frontmatter` + `vault_root_for` |
| `donna/cortex/scope.py` (edited) | added `scope_slugs_for(scope)` (extracted from `pipeline._scope_slugs`) |
| `donna/cortex/managers.py` (edited) | `_render_and_flag` post-commit hook in `save_with_reverse_edges` |
| `donna/cortex/tasks.py` (edited) | `flush_vault_indexes` Celery task (drains `vault:dirty:*` Redis sets via SPOP) |
| `donna/cortex/management/commands/cortex_sync.py` (edited) | added `--render` (eager) + `--rebuild` (walk vault → reconstruct rows) |
| `donna/settings.py` (edited) | `CORTEX_VAULT_ENABLED` env flag; beat entry `cortex-flush-vault-indexes`; test-mode auto-swap to `InMemoryStorage` |
| `donna/cortex/tests/test_vault_renderer.py` (new) | 12 tests including frontmatter round-trip + rebuild round-trip |
| `server/scripts/cleanup_test_residue.sh` (new) | safety net for any pre-Phase-5 FS residue |

**Layout produced:**

```
vault/<workspace_id>/
  _index.md                     ← workspace-root overview
  _log.md                       ← workspace-root append log
  emails/2026/MM/<slug>.md
  meetings/2026/MM/<slug>.md
  people/<slug>.md
  concepts/<slug>.md
  clients/<slug>/
    org.md
    emails/2026/MM/<slug>.md
    docs/<slug>.md
    decisions/<slug>.md
    projects/<slug>/
      project.md
      emails/2026/MM/<slug>.md
      ...
```

**Hook fires on every entity save** (post-commit, best-effort):

```python
# managers.py — appended to save_with_reverse_edges atomic block
transaction.on_commit(lambda: _render_and_flag(entity))

def _render_and_flag(entity):
    if not settings.CORTEX_VAULT_ENABLED: return
    renderer = VaultRenderer()
    renderer.render_entity(entity)
    renderer.append_log(entity.workspace_id, scope_prefix, {...})
    redis.sadd(f"vault:dirty:{ws_id}", parent_path)
```

**Beat task drains dirty-set:** `cortex.flush_vault_indexes` (default 5min) `SCAN`s `vault:dirty:*` keys → `SPOP`s each folder → renders `_index.md`. Atomic claim-then-process; re-dirty during render caught on next run.

**Augmented frontmatter** (so rebuild can reconstruct rows):

```yaml
---
type: email
title: ...
occurred_at: ...
parent_path: ...
slug: ...
id: <uuid>                ← injected by VaultRenderer (idempotent)
content_hash: <sha256>    ← injected by VaultRenderer (idempotent)
---
```

**Rebuild path:**

```bash
# Render → wipe → rebuild
python -m django cortex_sync --render --workspace=cube-digital
python -m django cortex_sync --rebuild --workspace=cube-digital
# Recovers display-grade rows; embeddings/clusters via:
python -m django cortex_sync --reindex-embeddings --rebuild-clusters
```

**Deviation from original plan:** the proposed `Workspace.vault_render_mode: off | live | on_demand` field was dropped as YAGNI. Single global `CORTEX_VAULT_ENABLED` env flag instead. Per-workspace toggle deferred until a real use case appears (decision 2026-06-19).

**Outstanding:** edge data (`sources` / `applied_in` / `supersedes` / `contradicts`) NOT yet in vault frontmatter — rebuild restores display-grade rows but not the entity graph. Requires Jinja template additions across `cortex/templates/*.j2` to ship.

**Real-world validation (cube-digital):** 278 head entities → vault. Wipe + rebuild → 278 rows recreated, 0 errors.

## §7 Phase 6 (~4.5d)

Maintenance task code skeletons:

```python
@shared_task
def decay_confidence():           # R8
    cutoff = date.today() - timedelta(days=180)
    CortexEntity.objects.filter(last_synthesized__lt=cutoff, confidence="high").update(confidence="medium")
    ...

@shared_task
def train_doc_classifier():       # tier B+ per workspace
    for ws in workspaces_with_labels(min_per_class=50):
        X, y = labeled_doc_bodies(ws)
        pipe = Pipeline([("tfidf", TfidfVectorizer(ngram_range=(1,2), max_features=50_000)),
                         ("clf", LogisticRegression(max_iter=1000))])
        pipe.fit(X, y)            # <1s CPU; cached per (ws, label_count)
        _CLASSIFIER_CACHE[ws.id] = pipe
# fit step: proba = pipe.predict_proba([sampled])[0]; below threshold → Haiku (tier C)
```

R6 resynth queryset, R7 entailment sweep (pairwise within cluster ∪ refs-overlap, chain-skip), `propose_structures` (tight unscoped cluster → review-queue proposal), eval harness layout (`golden_questions.py` YAML, `runners.py` Recall@10/MRR, per-tier classifier hit-rate report).

## §8 Cross-phase reference

- Phase 7 stretch table (link to 00f; CortexChunk design NOT duplicated).
- Cross-phase test strategy + container invocation (`docker exec donna-server bash -lc "cd /opt/donna && DATABASE_HOST=donna-database uv run python -m django test donna.cortex"`); host-mount breakage note.
- Pushback→phase map synced from 00f §13. Glossary (scope tuple, head, planes, T0–T4, tiers A–C).

## Conventions used in this doc

- Every code block is headed by its target path and either `(new)` or
  `(replaces lines X–Y)` relative to the 2026-06-12 tree.
- Code is written against verified current signatures — no invented
  collaborators. `TypeSpec` positional order matches the `registry.py`
  dataclass field order.
- Linter sections encode the **slim** decision; removed checks are
  listed with their new Pydantic home (canonical models, Phase 2).
- Decisions are dated (2026-06-11/12) and reference 00b pushback
  numbers where applicable.

## Implementation verification checklist (run per phase)

1. **Tests green in the container** (host FS mount is broken — see
   §8): `docker exec donna-server bash -lc "cd /opt/donna &&
   DATABASE_HOST=donna-database uv run python -m django test
   donna.cortex"`.
2. **No stale imports**: `grep -rn` for the deleted/moved symbol
   (e.g. `CortexWriter`, `templates/<type>.py` imports,
   `_build_extensions`) returns nothing outside this doc.
3. **Spec sync**: any contract change (linter slim, scope relaxation,
   canonical payloads in `DeliveryPackage`) lands as a SPEC.md / plans
   amendment in the same PR — the plans are the live design contract
   (repo rule).
4. **00f ledger**: tick the matching pushback row + phase status in
   [`00f §13`](./00f%20-%20silver-completion-plan.md) when a phase closes.
