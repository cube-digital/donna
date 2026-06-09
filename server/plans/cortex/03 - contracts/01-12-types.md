# 12 Canonical Types

Spec §3 defines a **closed Literal taxonomy** of twelve entity types.
Adding a new one requires a spec amendment + ADR. No ad-hoc types.

## The taxonomy

```python
EntityType = Literal[
    # Accrued (connector-written)
    "meeting", "email", "chat", "doc", "ticket", "clip", "note",
    # Curated (human / agent authored)
    "person", "org", "project", "concept", "decision",
]
```

## Why two flavours

| Property | Accrued | Curated |
|---|---|---|
| Source | connector pipeline | human or agent |
| Volume | high (1000s/workspace) | low (10s-100s) |
| Authority | low to medium | high |
| `author` default | `donna` | `human` |
| Mutable? | immutable after first write (R1) | immutable after first write (R1) |
| Decay rule | confidence decays per R8 | curated rows decay slower |
| Typical edges | `entity_refs` outbound | `applied_in` inbound (citation magnet) |

Lifecycle is captured via `type` + `author`, not via a separate Gold
layer (spec §2 rejected the Gold split — same table, same edges).

## Accrued types

### `meeting`

| Field | Detail |
|---|---|
| Sources | Fathom, Zoom, Meet, Teams, Whereby |
| Required nav | `attendees` |
| Sub-discriminator | none |
| Required extensions | `attendees: List[Attendee]`, `duration_min: int` |

```python
class MeetingExtensions(BaseModel):
    attendees: list[Attendee] = Field(default_factory=list)
    duration_min: int | None = None
    recording_url: str | None = None
```

### `email`

| Field | Detail |
|---|---|
| Sources | Gmail, Outlook, IMAP |
| Granularity | one entity per **thread** (NOT per message) |
| Required nav | `thread_id` |
| Required extensions | `thread_id: str`, `participants_emails: List[Participant]` |

### `chat`

| Field | Detail |
|---|---|
| Sources | Slack, WhatsApp, Discord, Telegram, Signal |
| Granularity | one entity per day per channel |
| Required nav | `channel` |
| Required extensions | `channel: str`, `participants: List[str]` |

### `doc`

| Field | Detail |
|---|---|
| Sources | Google Drive, Notion, SharePoint, OneDrive, Dropbox |
| Required nav | `doc_type` (R-hard-reject if missing) |
| Sub-discriminator | `doc_type` (16-value closed Literal) |
| Required extensions | `doc_type`, `mime`, `author_email` |

### `ticket`

| Field | Detail |
|---|---|
| Sources | Jira, Linear, GitHub Issues, Asana, ClickUp |
| Required nav | `provider`, `external_id`, `status` |
| Sub-discriminator | `provider` (5-value closed Literal) |
| Required extensions | `provider`, `external_id`, `status` |

### `clip`

| Field | Detail |
|---|---|
| Sources | Web Clipper, Pocket, Readwise, Raindrop |
| Required nav | `url`, `why_captured` |
| Required extensions | `url`, `why_captured`, `captured_by` |

### `note`

| Field | Detail |
|---|---|
| Sources | manual via MCP or UI (or agent post-meeting) |
| Required nav | `note_type` (R-hard-reject if missing) |
| Sub-discriminator | `note_type` (5-value closed Literal) |
| Required extensions | `note_type`, `why`, optional `is_open_question` |

## Curated types

### `person`

| Field | Detail |
|---|---|
| Origin | spawned by extractor OR human |
| Scope | cross-client allowed (spec §6 exception) |
| Path | always `people/<slug>` at workspace root |
| Required extensions | `full_name`, optional `primary_email`, `role`, `employer_org_id`, `cross_workspace_aliases` |

### `org`

| Field | Detail |
|---|---|
| Origin | spawned by extractor OR human |
| Scope | cross-everything when `relationship: self`; per-client otherwise |
| Sub-discriminator | `relationship` (6-value closed Literal) |
| Invariant | exactly ONE per workspace carries `relationship: self` |
| Required extensions | `relationship`, `legal_name`, `email_domains`, `industry` |

### `project`

| Field | Detail |
|---|---|
| Origin | always human or agent |
| Scope | the row IS the scope (`(workspace_id, client_id)` mandatory) |
| Sub-discriminator | `status` (4-value closed Literal) |
| Required extensions | `status`, optional `target_ship_date`, `repo_url`, `deployed_url`, `stack` |
| Replaces | the old per-project `Architecture.md` convention |

### `concept`

| Field | Detail |
|---|---|
| Origin | human OR agent-synthesised |
| Scope | cross-project allowed (spec §6 exception) |
| Sub-discriminator | `maturity` (3-value closed Literal: seed/growing/evergreen) |
| Hard reject | `INSUFFICIENT_EVIDENCE` if `sources.length < 2` |

### `decision` (ADR)

| Field | Detail |
|---|---|
| Origin | always human |
| Scope | per `(workspace, client, project)` |
| Sub-discriminator | `adr_status` (proposed/accepted/superseded) |
| Required extensions | `adr_status`, `deciders`, `context_sources` (R-hard-reject if missing) |
| Numbering | `ADR-NNNN` for client work, `ADR-W001` for workspace-internal |

## Sub-discriminator vocabularies

Locked closed Literal types — Pydantic rejects ad-hoc values.

### `doc_type` (16)

```
offer · requirements · spec · contract · handover · technical_analysis
internal_memo · presentation · signed_document · runbook · plan
integration_spec · checkpoint · architecture_note · design_note · other
```

### `note_type` (5)

```
brainstorm · checkpoint · journal · action_item · open_question
```

### `org.relationship` (6)

```
client · vendor · partner · competitor · internal · self
```

### `project.status` (4)

```
proposed · active · shipped · archived
```

### `concept.maturity` (3)

```
seed · growing · evergreen
```

### `decision.adr_status` (3)

```
proposed · accepted · superseded
```

### `ticket.provider` (5)

```
jira · linear · github · asana · clickup
```

## Authority weighting

`TYPE_AUTHORITY` registry gives a numeric weight to each
(type, sub-discriminator) pair for conflict resolution (R5):

| Top of the stack | Weight |
|---|---|
| `decision` | 100 |
| `doc:contract` | 95 |
| `doc:signed_document` | 95 |
| `doc:offer` | 80 |
| `project` | 75 |
| `doc:spec` / `doc:requirements` | 70 |
| `concept` | 65 |
| `person` / `org` | 60 |
| `meeting` | 55 |

| Bottom of the stack | Weight |
|---|---|
| `chat` | 30 |
| `doc:other` | 25 |
| `clip` | 20 |
| `note:journal` | 15 |

Full registry: [`05-type-authority.md`](./05-type-authority.md)

## Why 12, not 5 or 50

| Count | Trade |
|---|---|
| Very few (5) | Loses semantic distinctions — meetings and emails both end up "messages" |
| Many (50+) | Long tail; agents have to learn 50 layouts; sub-discriminators not needed |
| **12** | Each type maps to a distinct connector capability + a distinct user mental model |

The 12 emerged from auditing what content types Donna actually
encounters across qube-digital + Docupal + Narrio workspaces. Spec §3
locks the count.

## Workspace extensions (per spec §12)

A workspace can add type-specific fields via
`_meta/extensions/typespecs/<workspace>/<type>.py`:

```python
# Example: qube-digital doc extensions
class QubeDocExtensions(DocExtensions):
    legal_jurisdiction: str | None = None  # for contracts
    signed_party: str | None = None
    contract_type: str | None = None
    client_engagement_id: UUID | None = None
```

These are **additive** to the canonical extensions — they cannot
rename or remove canonical fields. Loaded at workspace boot.
