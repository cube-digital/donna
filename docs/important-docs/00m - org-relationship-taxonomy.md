# 00m — Org Relationship Taxonomy + Classifier

**Status:** Proposed 2026-06-19 · Companion to [00f](./00f%20-%20silver-completion-plan.md), [00i](./00i%20-%20silver-implementation-reference.md).

## Why

Cortex spec §3.2 originally defined `org.relationship ∈ {self, client}`. Reality (cube-digital workspace, 2026-06-19) demonstrated this is too coarse:

- **Animawings** (airline used for travel) tagged as `client` → vault file lands under `clients/animawings/org.md` → agent answers "list our clients" with airlines.
- **Reshape** (co-build partner) → same path, same misleading bucket.
- **Cube-digital** (the workspace owner) → tagged `client` → emails land under `clients/cube-digital/` instead of workspace root.

The folder hierarchy is a **contract** with both Obsidian browsers and the LLM. A wrong path is a wrong belief.

## Taxonomy

| Value | Definition | Signals |
|---|---|---|
| **`self`** | The workspace owner's own org | Auto-detected: workspace primary domain equals org domain |
| **`client`** | Org you bill / serve / deliver to | Bidirectional emails, "SoW", "invoice we sent", "milestone", "deliverable" |
| **`partner`** | Co-build / co-sell / referral partners | Bidirectional emails, "let's co-host", "joint customer", "white-label", "split", "partnership" |
| **`vendor`** | Services you consume (SaaS, suppliers, travel) | `noreply@` / `notifications@` / `billing@` sender; inbound-heavy; "receipt", "your booking", "invoice we received", "payment confirmed"; known SaaS domain |
| **`peer`** | Industry contacts, prospects-in-conversation, non-transactional | Light bidirectional; no commercial vocab |
| **`unknown`** | Not yet classified; default for first-touch orgs | New org with <3 emails |

**Closed enum.** New values require a spec update — keeps folder routing + agent prompts stable.

## Classifier ladder

Per-workspace job. Runs at org-spawn time + nightly re-classification.

### Tier A — Rule-based (free, deterministic)

Fires first. Catches the obvious ~60-70%.

1. **Self detection.** Workspace `primary_domain` field (new, per-workspace setting). If org's `email_domains` overlaps → `self`.

2. **Vendor sender pattern.** Any of the org's first-5 senders match `^(noreply|no-reply|notifications?|alerts?|billing|support|do[-_]?not[-_]?reply|hello|contact|info|team|automated|hello)@` → `vendor`.

3. **Curated vendor allowlist.** A maintained `donna/cortex/data/known_vendors.txt` of well-known SaaS/services (AWS, GitHub, Stripe, airlines, OTAs, etc.). Domain hit → `vendor`. Bootstrapped from a static list; community PRs welcome.

4. **Direction asymmetry.** Compute over last 90 days:
   - `inbound = count(emails where org is sender)`
   - `outbound = count(emails where org domain in to/cc)`
   - If `inbound > 5 AND outbound == 0` → `vendor`
   - If `inbound > 0 AND outbound > 0 AND ratio in [0.3, 3.0]` → eligible for client/partner (still need Tier B)

5. **Vocabulary regex** (cheap pre-LLM signal):
   - `\b(invoice|receipt|payment|order|booking|reservation)\b` heavily in body → vendor bias
   - `\b(milestone|deliverable|SoW|statement of work|scope)\b` → client bias
   - `\b(partnership|co-(?:host|build|sell)|joint customer|reseller)\b` → partner bias

### Tier B — LLM judgment (cheap, ~$0.02/workspace)

For orgs not classified by Tier A. Haiku reads:
- Org title + domains
- 5–10 sampled email subjects + first 200 chars of body
- Direction stats (inbound/outbound counts)

Returns structured JSON:
```json
{"relationship": "client|partner|vendor|peer", "confidence": 0.0-1.0, "reasoning": "..."}
```

Threshold to apply: `confidence >= 0.7`. Below threshold → leave as `unknown`, surface in review queue.

### Tier C — Manual override (always wins)

Future UI: per-org dropdown. Stored in `org.extensions.relationship_locked = true` so future re-classifier runs skip locked orgs.

## Folder routing (vault)

```
vault/<workspace_id>/
  _index.md
  _log.md
  org.md                          ← relationship=self (workspace-owner)
  clients/<slug>/
    org.md
    _index.md
    emails/YYYY/MM/<slug>.md
    docs/<slug>.md
    decisions/<slug>.md
    projects/<slug>/project.md
  partners/<slug>/
    org.md
    emails/YYYY/MM/<slug>.md
    docs/<slug>.md
  vendors/<slug>/
    org.md
    emails/YYYY/MM/<slug>.md      ← receipts, booking confs, invoices
  peers/<slug>/
    org.md
    emails/YYYY/MM/<slug>.md
  emails/YYYY/MM/                 ← relationship=unknown OR no-org match
  people/<slug>.md
  concepts/<slug>.md
```

**`folders.org` resolver** branches on `extensions.relationship`:

```python
def org(*, type, occurred_at, extensions, client_slug, project_slug) -> str:
    rel = (extensions or {}).get("relationship", "unknown")
    own_slug = (extensions or {}).get("slug")
    if rel == "self":
        return ""                                # workspace root
    bucket = {"client": "clients", "partner": "partners",
              "vendor": "vendors", "peer": "peers"}.get(rel, "unknown")
    return f"{bucket}/{own_slug}" if own_slug else bucket
```

**Email folder resolver** (`folders.temporal("emails")`) uses the email's `client_id` org's `relationship` to choose the bucket prefix. New helper `folders.scoped_temporal("emails")` looks up `extensions.scoped_relationship` (cached from the email's client org) and emits the right prefix (`clients/<x>/emails/YYYY/MM`, `partners/<x>/emails/...`, `vendors/<x>/emails/...`).

## Agent integration

### `cortex_query` gets a `relationship` filter

```python
class QueryArgs(BaseModel):
    text: str
    type: EntityType | None = None
    relationship: Literal["client", "partner", "vendor", "peer"] | None = None
    ...
```

`CortexService.query` joins through the entity's `client_id` → org → `extensions.relationship` and filters. Agent calls:

```
cortex_query(text="active engagements", type="email", relationship="client")
```

→ vendor noise filtered out at the query layer; no LLM-side reasoning needed.

### System prompt addition (00j prompt builder)

> Orgs have one of these relationships: **client** (we bill/serve them), **partner** (we co-build/co-sell), **vendor** (we consume their service — airlines, SaaS, suppliers), **peer** (industry contact). Do NOT conflate these. When the user asks about "clients" they mean `relationship=client` only — vendors and partners are different categories. Use the `relationship` filter on `cortex_query` when the question is bounded to one category.

3-sentence addition. Free. Catches the misleading paths.

### Default scope behaviour

`cortex_query` with no `relationship` filter returns all orgs equally. Agents that want "what's relevant to my business right now" should default to `client + partner` (excluding vendor noise). Document in the system prompt:

> If the user's question is vague ("any updates"), default to `relationship in (client, partner)`. Vendors only when the user explicitly asks about invoices, bookings, infrastructure, or names a vendor.

## Reclassification triggers

1. **Org spawn** — Tier A runs synchronously inside `_spawn_org`.
2. **Nightly batch** (`cortex.reclassify_orgs` beat task) — re-runs Tier A + B for any org with `relationship_locked=false`. Catches:
   - Newly-collected email volume (vendor → was misclassified as client)
   - Vocabulary signals from recent emails
   - Curated allowlist updates
3. **Manual** — `cortex_sync --reclassify-orgs --workspace=<slug>` for ad-hoc bulk runs.

## Data model

`OrgExtensions` (Pydantic, `cortex/schemas.py`):

```python
class OrgExtensions(BaseModel):
    model_config = ConfigDict(extra="allow")
    slug: str
    legal_name: str | None = None
    email_domains: list[str] = Field(default_factory=list)
    industry: str | None = None
    relationship: Literal["self", "client", "partner", "vendor", "peer", "unknown"] = "unknown"
    relationship_confidence: float = 0.0
    relationship_basis: str = ""        # "rule:noreply" | "rule:allowlist" | "rule:direction" | "rule:vocab" | "llm:haiku" | "manual"
    relationship_locked: bool = False   # True → manual override; classifier skips
    relationship_evidence: list[str] = Field(default_factory=list)  # short bullet trail for audit
```

`Workspace.primary_domain` (new field):
```python
primary_domain = models.CharField(max_length=255, blank=True, default="")
```
Set during onboarding (or inferred from owner's email). Used by Tier A self-detection.

## Migration plan

1. Add `Workspace.primary_domain` migration (default empty; backfill via UI / one-shot script).
2. Extend `OrgExtensions` schema (new optional fields — no migration needed, JSONB).
3. Implement Tier A classifier (`donna/cortex/relationship_classifier.py`).
4. Wire into `_spawn_org`: run classifier on spawn, store result.
5. Add `folders.scoped_temporal()` helper + branch `folders.org` on relationship.
6. Add `cortex.reclassify_orgs` beat task.
7. Add `cortex_sync --reclassify-orgs` flag.
8. Add `relationship` filter to `cortex_query` (`CortexService.query` + `QueryArgs`).
9. Update 00j chat agent prompt (taxonomy + default-scope guidance).
10. Backfill cube-digital: set workspace primary_domain → re-run classifier on existing 24 orgs → re-render vault.

Tier B (LLM) ships in a second pass once Tier A baseline is measured.

## Open decisions

| # | Question | Default |
|---|---|---|
| 1 | Render vendor emails at all? | Yes, under `vendors/<slug>/emails/...` (browsable, segregated) |
| 2 | Should peer be a real bucket or fold into client? | Real bucket — agent needs the distinction |
| 3 | How does user trigger manual override? | Phase 7: API endpoint + Bruno; longer term: UI dropdown |
| 4 | Should `cortex_query` default exclude vendors when no filter? | No — explicit, not magic. Agent's system prompt teaches the default behaviour. |
| 5 | Re-classification cadence | Nightly via beat; manual via CLI; on-spawn synchronously |

## Anti-goals

- **No new org type.** `relationship` is a property of `org`, not a new entity type. Closed enum keeps schema stable.
- **No machine-learning classifier in v1.** TF-IDF + LogReg ships at Phase 6 tier-B+ for doc_type; relationship classification reuses LLM tier B until enough labeled data justifies a learned model.
- **No domain-reputation API calls.** All Tier A signals are local (sender patterns, allowlist, direction stats, vocab regex). Network-free.


## Future signals (Phase 6, 2026-06-19)

Tier A + B v1 hit a recall ceiling on outbound-only / weak-signal orgs (cube-digital had 11 unknowns after both tiers ran). Manual CSV correction unblocks the present, but the long-tail fix is cluster-aware classification + integration enrichment. Lives in Phase 6 maintenance (see [00f §10](./00f%20-%20silver-completion-plan.md)).

### Cluster signals (free — clusters already computed)

1. **Cluster-cohort vocabulary** — aggregate vocab regex over EVERY entity in clusters the org appears in, not just its own emails. SoW/milestone language across a whole cluster of "Migration project" emails ⇒ stronger client signal than a 3-email vocab score.

2. **Cluster co-occurrence with self** — orgs whose clusters frequently include the `self` org's entities ⇒ joint work (partner/client). Orgs in clusters isolated from `self` ⇒ transactional (vendor).

3. **Cluster name as anchor** — Haiku already names every cluster. `cluster_name="Invoices"` / `"Booking confirmations"` ⇒ vendor; `cluster_name="Project deliverables"` / `"Migration kickoff"` ⇒ client. Free signal.

4. **Cluster diversity per org** — entropy of cluster spread. Wide spread (org touches many topics) ⇒ deep relationship. Narrow (one cluster of receipts) ⇒ vendor.

5. **Cluster-anchored Haiku judgment** — instead of feeding the LLM 5 random emails, feed cluster summaries: `"Org Z appears in: 'Migration project planning' (12 emails), 'Status updates' (8), 'Invoice processing' (3)"`. Same Tier B cost, far higher recall.

6. **Label propagation** — orgs sharing >40% cluster overlap with a manually-confirmed client ⇒ strong client prior. Few-shot from `relationship_locked=True` rows across the whole workspace.

### Integration signals (extra connectors needed)

| Source | Signal | Strength |
|---|---|---|
| Slack / Teams DMs | per-org channel co-membership, DM frequency | bidirectional vs broadcast |
| Calendar | recurring meetings = client/partner; one-off = peer | medium |
| **Stripe / QuickBooks / Xero** | invoice direction — we billed → client; they billed → vendor | **strongest** (ground truth) |
| CRM (HubSpot, Salesforce, Pipedrive) | `Account.type`, `Deal.stage` | direct ground truth |
| LinkedIn / Crunchbase | industry, headcount, public partnership announcements | weak prior |
| Public website "Customers" / "Partners" page scrape | the org lists OUR org as customer or partner | medium |

### Scheduling

Goes into the **Phase 6 nightly batch** (`cortex.reclassify_orgs` task). Eval-gated: ship behind the harness, measure ladder hit-rate per tier (A / B / B+cluster / manual), only promote when before/after Recall improves on the relationship-labeling golden fixture. Existing manual locks always win — classifier upgrades only touch `relationship_locked=False` rows.

Estimated effort: ~1 day for cluster signals (1–4), ~0.5 day for Haiku integration (5), ~0.5 day for label propagation (6). Integration-side enrichers ship as separate connector projects, not in Phase 6.

## References

- [00f §13 open decisions](./00f%20-%20silver-completion-plan.md) — relationship-taxonomy entry to be added there pointing here
- [00i §3 Phase 2](./00i%20-%20silver-implementation-reference.md) — `OrgExtensions` Pydantic model
- [00j chat agent](./00j%20-%20agent-implementation-reference.md) — system prompt taxonomy lines
- [Spec §3.2](../../server/plans/02-data-model.md) — org type definition (needs amendment to broaden `relationship`)
