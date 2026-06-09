# Reject Codes

Closed-vocab error codes carried by every `LinterError`. Locked
surface — adding requires spec amendment.

Code: `donna/cortex/authority.py:RejectCode`.

## The 13 codes

| Code | When | Hard reject? |
|---|---|---|
| `MISSING_REQUIRED_EXTENSION` | doc missing `doc_type`, note missing `note_type`, decision missing `context_sources` | ✅ yes |
| `INSUFFICIENT_EVIDENCE` | concept with `sources.length < 2` | ✅ yes |
| `DUPLICATE` | `content_hash` collision; returns existing `entity_id` | ✅ yes |
| `MISSING_ENTITY_REFS` | named entities in body unbound (R-ER warning) | ⚠️ warning |
| `IMPLICIT_CONTRADICTION` | body claims X but newer Silver says ¬X without `supersedes` | ⚠️ warning (R7 future) |
| `UNKNOWN_EDGE_TYPE` | ad-hoc edge field name in `extensions` | ✅ yes |
| `MISSING_SOURCE_FOOTER` | last body line ≠ `Source:` / `Spawned by:` | ✅ yes |
| `MISSING_OCCURRED_AT` | R2 violation — no event time | ✅ yes |
| `MISSING_SYNTHESIZED_AT` | R2 violation — no synthesis time (auto-set; rare) | ✅ yes |
| `INVALID_SCOPE` | `project_id` non-null but `client_id` is null | ✅ yes |
| `INVALID_CROSS_REF_SCOPE` | R4 violation — cross-scope `cross_refs` | ⚠️ warning |
| `INVALID_TYPE` | type not in the 12-value Literal | ✅ yes |
| `INVALID_AUTHOR` | author not in `{donna, human, agent}` | ✅ yes |
| `PYDANTIC_INVALID` | Pydantic `model_validate` raised for non-missing-field reasons (wrong type, off-vocab Literal, etc.) | ✅ yes |

## Why closed codes

| Concern | Open string error | Closed `RejectCode` |
|---|---|---|
| MCP API maps to HTTP error | per-message parsing | stable error code |
| Client-side UX | "varies" | switch on code |
| Telemetry | high cardinality | bounded set, dashboards work |
| Tests | brittle string match | enum comparison |
| i18n | hard | translate per code |

Locking the codes lets the Obsidian plugin, the CLI, the MCP API, and
the Donna chat UI all map the same reject to a meaningful action
without parsing error strings.

## Carried on every error

```python
class LinterError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
```

Caller:

```python
try:
    linter.check(entity)
except LinterError as exc:
    response.error = {
        "code": exc.code,
        "message": exc.message,
    }
```

## Where each fires

| Code | Module | Method |
|---|---|---|
| `MISSING_REQUIRED_EXTENSION` | linter.py | `_check_extensions`, `_check_required_doc_type`, `_check_required_note_type`, `_check_required_context` |
| `INSUFFICIENT_EVIDENCE` | linter.py | `_check_required_evidence` |
| `DUPLICATE` | repository.py (via PG unique constraint) | `save_with_reverse_edges` |
| `MISSING_ENTITY_REFS` | (deferred R7) | TBD |
| `IMPLICIT_CONTRADICTION` | (deferred R7) | TBD |
| `UNKNOWN_EDGE_TYPE` | linter.py | `_check_known_edges` |
| `MISSING_SOURCE_FOOTER` | linter.py | `_check_source_footer` |
| `MISSING_OCCURRED_AT` | linter.py | `_check_temporal` |
| `INVALID_SCOPE` | linter.py | `_check_scope` |
| `INVALID_CROSS_REF_SCOPE` | (deferred — repository scope check) | TBD |
| `INVALID_TYPE` | linter.py | `_check_type` |
| `INVALID_AUTHOR` | linter.py | `_check_author` |
| `PYDANTIC_INVALID` | linter.py | `_check_extensions`, `_check_supersedes`, `_check_cross_refs` |

## Concrete error examples

### Drive PDF without doc_type

```
LinterError: MISSING_REQUIRED_EXTENSION:
  extensions invalid for doc:
  1 validation error for DocExtensions
    doc_type
      Field required [type=missing, ...]
```

### Concept spawned from a single mention

```
LinterError: INSUFFICIENT_EVIDENCE:
  concept requires at least 2 sources
```

### Body without Source footer

```
LinterError: MISSING_SOURCE_FOOTER:
  body_md must end with 'Source: <key>' or 'Spawned by: <id>'
```

### Note without note_type

```
LinterError: MISSING_REQUIRED_EXTENSION:
  note requires extensions.note_type
```

### Pydantic Literal violation

```
LinterError: PYDANTIC_INVALID:
  extensions invalid for org:
  1 validation error for OrgExtensions
    relationship
      Input should be 'client', 'vendor', 'partner', 'competitor',
      'internal' or 'self' [type=literal_error, input_value='customer', ...]
```

## Future: lint dry-run

Spec §10.2 includes `cortex.linter_check(payload)` as an MCP method —
clients can validate before committing. Returns:

```json
{
  "valid": false,
  "errors": [
    {"code": "MISSING_REQUIRED_EXTENSION", "message": "..."},
    ...
  ],
  "warnings": [
    {"code": "MISSING_ENTITY_REFS", "message": "..."},
    ...
  ]
}
```

Currently unwired (P9).

## Reject codes vs HTTP status

When MCP API ships (P9), the mapping is:

| Code | HTTP status |
|---|---|
| `MISSING_REQUIRED_EXTENSION` | 400 |
| `INSUFFICIENT_EVIDENCE` | 400 |
| `MISSING_SOURCE_FOOTER` | 400 |
| `MISSING_OCCURRED_AT` | 400 |
| `INVALID_SCOPE` | 400 |
| `INVALID_TYPE` | 400 |
| `INVALID_AUTHOR` | 400 |
| `PYDANTIC_INVALID` | 422 |
| `UNKNOWN_EDGE_TYPE` | 422 |
| `DUPLICATE` | 409 |
| `MISSING_ENTITY_REFS` | 200 + warnings |
| `IMPLICIT_CONTRADICTION` | 200 + warnings |
| `INVALID_CROSS_REF_SCOPE` | 200 + warnings |
