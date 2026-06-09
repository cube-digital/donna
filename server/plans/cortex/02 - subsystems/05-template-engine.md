# Subsystem 5 — Template Engine + Linter

**Concern:** every entity type is rendered through a Jinja template
that fits to a strong convention. Predictable shape → fast agent
comparison.

## Plain English

Two meetings, same shape. Two emails, same shape. Two ADRs, same
shape. **Predictability** lets agents compare rows without learning
twelve different layouts.

The template engine takes raw body markdown + extensions dict +
provenance and emits the final `body_md` that gets stored in the
`cortex_entities.body_md` column:

```markdown
---
type: meeting                           ← closed Literal
title: Acme onboarding call
occurred_at: 2026-06-03 14:00:00+00:00
parent_path: clients/acme/projects/onboarding/meetings/2026/06
slug: 2026-06-03-acme-onboarding-call-a4b2c8e1
template_version: meeting@v1
attendees:
  - "Alice <alice@acme.com> (host)"
  - "Bob <bob@example.com> (attendee)"
duration_min: 30
cluster_name: "Customer Onboarding"
---

# Acme onboarding call

[raw body content from OCR/adapter — verbatim]

Source: fathom://meeting/rec-abc (ws/fathom/meetings/rec-abc.json)
```

Three guaranteed parts: **closed-vocab frontmatter** + **verbatim body**
+ **Source footer**.

## TypeSpec — the contract

```python
@dataclass(frozen=True)
class TypeSpec:
    type: EntityType
    extensions_model: type[BaseModel]   # Pydantic — locks frontmatter shape
    fit_model: type[BaseModel] | None   # Pydantic — what HaikuFitter fills
    template_path: str                  # "meeting.j2" relative to templates/
    nav_fields: list[str]               # required keys in extensions
    folder_resolver: FolderResolver
    version: str                        # "meeting@v1"
```

Twelve TypeSpecs total — one per type:

| Type | Pydantic model | Jinja template | fit_model | nav fields |
|---|---|---|---|---|
| meeting | `MeetingExtensions` | `meeting.j2` | None | `[attendees]` |
| email | `EmailExtensions` | `email.j2` | None | `[thread_id]` |
| chat | `ChatExtensions` | `chat.j2` | None | `[channel]` |
| doc | `DocExtensions` | `doc.j2` | `DocExtensions` | `[doc_type]` |
| ticket | `TicketExtensions` | `ticket.j2` | None | `[provider, external_id, status]` |
| clip | `ClipExtensions` | `clip.j2` | None | `[url, why_captured]` |
| note | `NoteExtensions` | `note.j2` | `NoteExtensions` | `[note_type]` |
| person | `PersonExtensions` | `person.j2` | None | `[]` |
| org | `OrgExtensions` | `org.j2` | None | `[relationship]` |
| project | `ProjectExtensions` | `project.j2` | None | `[status]` |
| concept | `ConceptExtensions` | `concept.j2` | None | `[maturity]` |
| decision | `DecisionExtensions` | `decision.j2` | None | `[adr_status]` |

## Registry — discovered at startup

```python
# donna/cortex/templates/meeting.py
MeetingSpec = TypeSpec(
    type="meeting",
    extensions_model=MeetingExtensions,
    fit_model=None,
    template_path="meeting.j2",
    nav_fields=["attendees"],
    folder_resolver=TemporalFolderResolver(bucket="meetings"),
    version="meeting@v1",
)
register_type(MeetingSpec)
```

`donna.cortex.apps.CortexConfig.ready()` walks
`donna/cortex/templates/` for `*.py` modules and imports each. Each
module's `register_type(...)` call populates the registry singleton.

Same pattern as connector discovery in
`donna/integrations/apps.py:ready()`.

```python
class TemplateRegistry:
    def get(self, type_: str) -> TypeSpec: ...
    def types(self) -> list[str]: ...
    def all(self) -> dict[str, TypeSpec]: ...
```

## TemplateEngine — Jinja2 with StrictUndefined

```python
class TemplateEngine:
    def __init__(self, template_dir=None):
        self._env = Environment(
            loader=FileSystemLoader(str(template_dir or TEMPLATE_DIR)),
            undefined=StrictUndefined,        # missing var → raise
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(self, type_spec, *, data, body_input, title, occurred_at,
               source_uri, bronze_storage_key):
        template = self._env.get_template(type_spec.template_path)
        payload = data.model_dump(mode="json") if isinstance(data, BaseModel) else dict(data)
        return template.render(
            data=payload, body=body_input,
            title=title, occurred_at=occurred_at,
            source_uri=source_uri,
            bronze_storage_key=bronze_storage_key,
            type_spec=type_spec,
        )
```

`StrictUndefined` is a deliberate choice. If a template references
`data.attendees` and the field is missing, the renderer raises
instead of silently writing nothing. **Fail loud beats fail silent.**

## Template anatomy (the meeting example)

```jinja
---
type: meeting
title: {{ title }}
{% if occurred_at %}occurred_at: {{ occurred_at }}{% endif %}
parent_path: {{ data.parent_path }}
slug: {{ data.slug }}
template_version: meeting@v1
{% if data.attendees %}attendees:
{% for a in data.attendees %}  - "{{ a.name or a.email }}{% if a.email %} <{{ a.email }}>{% endif %}{% if a.role %} ({{ a.role }}){% endif %}"
{% endfor %}{% endif %}
{% if data.duration_min %}duration_min: {{ data.duration_min }}{% endif %}
{% if data.recording_url %}recording_url: "{{ data.recording_url }}"{% endif %}
{% if data.cluster_name %}cluster_name: "{{ data.cluster_name }}"{% endif %}
---

# {{ title }}

{{ body }}

Source: {{ source_uri }} ({{ bronze_storage_key }})
```

Three things every template guarantees:

1. **Closed-vocab frontmatter block** — agents parse the YAML to filter
2. **Verbatim body** — `{{ body }}` is the OCR/adapter output, untouched
3. **Source footer** — last line is `Source: <uri> (<bronze_key>)` for
   audit + linter R3 check

## Fitters — the LLM escape hatch

Two fitters ship:

### `NoOpFitter` (default)

```python
class NoOpFitter:
    def fit(self, text, fit_model):
        raise NotImplementedError("NoOpFitter cannot fill")
```

Refuses. Used when `TypeSpec.fit_model is None` (meeting/email/chat/…)
because provider metadata always satisfies nav fields.

### `HaikuFitter`

```python
class HaikuFitter:
    DEFAULT_MODEL = "anthropic/claude-3-5-haiku-latest"

    def fit(self, text, fit_model):
        provider = LLMFactory.create(model=self._model)
        response = provider.chat(
            messages=[{"role": "user", "content": prompt + text[:8000]}],
            temperature=0.0,
            response_format=fit_model,    # LiteLLM Pydantic hook
        )
        return fit_model.model_validate_json(response.content)
```

Used for `doc` and `note` types where provider metadata may be
incomplete (a Drive PDF often doesn't tag itself as `doc_type=plan`).
Pydantic `response_format` keeps the LLM honest — Literal vocabularies
locked at the model level.

## When the fitter runs

Pipeline step 4:

```python
if not self.linter.has_required_nav_fields(extensions, type_spec.nav_fields):
    if type_spec.fit_model is not None:
        try:
            fit = self.fitter.fit(body_md, type_spec.fit_model)
            extensions = self._merge_fit(extensions, fit)
        except NotImplementedError:
            pass  # NoOpFitter — linter will reject downstream if truly missing
```

Two short-circuits:

1. **All nav fields present** → skip fitter (Fathom + Gmail land here)
2. **TypeSpec declares `fit_model=None`** → skip fitter (no LLM ever)

Only the intersection ("nav fields missing AND fit_model declared")
calls Haiku.

## Linter — the gate

```python
class FrontmatterLinter:
    def check(self, entity):
        self._check_type(entity)
        self._check_author(entity)
        self._check_temporal(entity)
        self._check_scope(entity)
        self._check_extensions(entity)
        self._check_supersedes(entity)
        self._check_cross_refs(entity)
        self._check_known_edges(entity)
        self._check_source_footer(entity)
        self._check_required_evidence(entity)
        self._check_required_context(entity)
        self._check_required_doc_type(entity)
        self._check_required_note_type(entity)
```

Eleven checks, each raises `LinterError(code: RejectCode, message)`.

Spec §7.2 hard rejects:

| Reject code | When |
|---|---|
| `MISSING_REQUIRED_EXTENSION` | doc missing `doc_type`, note missing `note_type`, decision missing `context_sources` |
| `INSUFFICIENT_EVIDENCE` | concept with sources.length < 2 |
| `DUPLICATE` | `content_hash` collision (returns existing id) |
| `MISSING_ENTITY_REFS` | named entities in body unbound (warning) |
| `IMPLICIT_CONTRADICTION` | body claims X but newer Silver says ¬X without `supersedes` |
| `UNKNOWN_EDGE_TYPE` | ad-hoc edge field name |
| `MISSING_SOURCE_FOOTER` | last body line ≠ `Source:` / `Spawned by:` |
| `MISSING_OCCURRED_AT` | R2 violation |
| `INVALID_SCOPE` | `project_id` non-null while `client_id` is null |

Full table: [`../03 - contracts/04-linter-r1-r10.md`](../03%20-%20contracts/04-linter-r1-r10.md)

## Anti-hallucination invariants

| Source | Field | Rule |
|---|---|---|
| `adapter.metadata()` | participants, occurred_at, sender, … | Deterministic Jinja interpolation; LLM forbidden |
| `adapter.to_markdown()` (or OCR output) | body content | Rendered verbatim |
| Haiku fit | optional `tldr`, missing nav fields | Pydantic Literal locks values; additive only |
| Body footer | bronze back-reference | Every body_md ends with `Source: <uri>` (or `Spawned by: <id>`) |
| Bidirectional edges | `sources` + reverse `applied_in` | Same Postgres txn; linter rejects partial writes |

Spec §5 + R1: silver immutable after first write. Only auto-maintained
reverse edges may be appended post-write.

## Why three contracts, aligned

| Contract | Locked by | Linter check |
|---|---|---|
| Pydantic frontmatter model | `extensions_model` per TypeSpec | `_check_extensions` |
| Jinja template | `template_path` per TypeSpec | template render with StrictUndefined |
| Literal closed vocab | `Literal[...]` in schemas.py | Pydantic raises on unknown value |

All three move together — version bump on the TypeSpec = synchronized
update of all three for that type. Old rows preserved (immutable per
R1); new rows go through the new contract.
