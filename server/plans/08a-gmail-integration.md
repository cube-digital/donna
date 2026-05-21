# Gmail Integration — Subscription Config

> Status: **Locked design contract.** Builds on `08-connection-pattern.md`
> (the `Connection` model + config/state/picker contract). v1 connector
> code already shipped (Phase 4 of the roadmap) — this plan adds the
> per-workspace **configuration layer** on top.

## Context

Gmail connector is already in code:
- `donna/integrations/connectors/google/mail/{provider,client,adapter,tasks}.py`
- `GoogleOAuthHandler` + `BaseGoogleClient` shared with future Drive
- Celery beat schedule `gmail-fanout-sync` ticks every 5 min

v1 sync behavior: **cold-start poll** with hard-coded
`COLD_START_WINDOW = "newer_than:1h"`. Same window for every workspace,
no user choice.

This plan replaces that hard-coded behavior with per-Connection config —
user picks **mode** (everything / last N days / specific labels-filters-domains).

## Decisions (locked)

| Choice | Decision | Why |
|---|---|---|
| Token scope | **`user`** (per-user pairing) | Personal Gmail accounts; multiple employees per workspace each connect their own |
| Default mode on first pair | **`time_window` with `days=30`** | Safe blast radius; user opts up to `everything` consciously |
| Mode set | **`everything` / `time_window` / `subscriptions`** | Three distinct UX patterns; covers user scenarios (whole inbox, recent only, filtered) |
| Subscription filters | **Labels + Queries + Domains, OR-combined** | Each is independent. User toggles labels OR specifies senders OR domain — any match ingests |
| Label discovery | **Picker endpoint** `GET /api/v1/integrations/gmail/subscription/picker/labels` → calls `users.labels.list` | Vendor data populates our UI |
| Time-window scope | **Backfill on first sync**, then `newer_than:1h` per beat tick | Avoid re-fetching same window repeatedly. Track `cold_start_done` in state |
| State shape | **Per-stream keyed** by label_id (per-stream cursor) + `_global` (used when mode=everything or time_window) | Future-proof for History API per-label cursors |

## Config schema

```python
class GmailProvider:
    slug                = "gmail"
    display_name        = "Gmail"
    category            = "email"
    oauth_provider_slug = "google"
    token_scope         = "user"

    default_config = {
        "mode": "time_window",
        "time_window_days": 30,
    }

    config_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type":    "object",
        "required": ["mode"],
        "properties": {
            "mode": {"enum": ["everything", "time_window", "subscriptions"]},
            "time_window_days": {"type": "integer", "minimum": 1, "maximum": 3650},
            "labels":  {"type": "array", "items": {"type": "string"}},
            "queries": {"type": "array", "items": {"type": "string", "maxLength": 500}},
            "domains": {"type": "array", "items": {"type": "string", "maxLength": 255}},
        },
        "allOf": [
            # time_window_days required iff mode=time_window
            {
                "if":   {"properties": {"mode": {"const": "time_window"}}},
                "then": {"required": ["time_window_days"]},
            },
            # at least one of labels/queries/domains required iff mode=subscriptions
            {
                "if":   {"properties": {"mode": {"const": "subscriptions"}}},
                "then": {"anyOf": [
                    {"required": ["labels"],  "properties": {"labels":  {"minItems": 1}}},
                    {"required": ["queries"], "properties": {"queries": {"minItems": 1}}},
                    {"required": ["domains"], "properties": {"domains": {"minItems": 1}}},
                ]},
            },
        ],
        "additionalProperties": False,
    }
```

## State shape

```jsonc
{
  "streams": {
    "_global": {
      "last_history_id": "1234567890",
      "last_synced_at":  "2026-05-20T10:00:00Z",
      "cold_start_done": true
    },
    "Label_42": {
      "last_history_id": "...",
      "last_synced_at":  "..."
    }
  },
  "global": {
    "cold_start_done": true
  }
}
```

`_global` stream holds cursor for `mode=everything` and `mode=time_window`.
Per-label cursors only populated when `mode=subscriptions` runs through
labels. Future History API per-label sync uses these.

## Sync task — mode dispatch

```python
@shared_task(name="integrations.google.mail.sync")
def sync_gmail_connection(connection_id: str) -> dict:
    from donna.integrations.models import Connection
    conn = (
        Connection.objects
        .select_for_update()
        .select_related("token")
        .get(id=connection_id, provider_slug="gmail", enabled=True)
    )
    cfg, state = conn.config, conn.state

    query = _build_query(cfg, state)
    if query is None:
        return {"skipped": "no_query"}

    provider = get_provider("gmail")
    enqueued = 0
    with provider.client(conn.token) as client:
        for entry in client.iter_all_messages(query=query):
            mid = entry.get("id")
            if not mid:
                continue
            ingest_gmail_message.delay(str(conn.workspace_id), mid)
            enqueued += 1

    _update_state_after_sync(conn, state, cfg)
    conn.last_synced_at = now()
    conn.save(update_fields=["state", "last_synced_at"])
    return {"enqueued": enqueued}


def _build_query(cfg: dict, state: dict) -> str | None:
    mode = cfg["mode"]
    cold_done = state.get("global", {}).get("cold_start_done", False)

    if mode == "everything":
        return "newer_than:1h" if cold_done else ""        # backfill on first run

    if mode == "time_window":
        days = cfg["time_window_days"]
        return "newer_than:1h" if cold_done else f"newer_than:{days}d"

    if mode == "subscriptions":
        parts: list[str] = []
        for label_id in cfg.get("labels", []):
            parts.append(f"label:{label_id}")
        for q in cfg.get("queries", []):
            parts.append(f"({q})")
        for d in cfg.get("domains", []):
            parts.append(f"from:*@{d}")
        if not parts:
            return None
        base = " OR ".join(parts)
        return f"({base}) newer_than:1h" if cold_done else f"({base})"

    return None
```

`ingest_gmail_message(workspace_id, message_id)` task **unchanged** —
still writes `DeliveryPackage` + `default_storage`.

## Beat fanout

Replace token-iteration with Connection-iteration:

```python
@shared_task(name="integrations.google.mail.fanout_sync")
def fanout_gmail_sync() -> dict:
    from donna.integrations.models import Connection
    conn_ids = (
        Connection.objects
        .filter(provider_slug="gmail", enabled=True)
        .values_list("id", flat=True)
    )
    dispatched = 0
    for cid in conn_ids:
        sync_gmail_connection.delay(str(cid))
        dispatched += 1
    return {"connections": dispatched}
```

`settings.py` Celery beat entry unchanged — same task name, same
interval.

## Picker — labels

```python
class GmailProvider:
    def picker(self, resource: str, params: dict, *, connection) -> dict:
        if resource == "labels":
            with self.client(connection.token) as client:
                resp = client.list_labels()              # GET /gmail/v1/users/me/labels
            return {
                "labels": [
                    {"id": l["id"], "name": l["name"], "type": l.get("type", "user")}
                    for l in resp.get("labels", [])
                ]
            }
        raise ValueError(f"Gmail picker has no resource '{resource}'")
```

Frontend calls
`GET /api/v1/integrations/gmail/subscription/picker/labels` → renders
checkbox tree, user picks N → `PATCH
/api/v1/integrations/gmail/subscription/` with
`{config: {mode: "subscriptions", labels: ["Label_42", "Label_17"]}}`.

## API

```
GET    /api/v1/integrations/gmail/subscription/
PATCH  /api/v1/integrations/gmail/subscription/                   # body: {config: {...}}
DELETE /api/v1/integrations/gmail/subscription/                   # deletes Connection only; OAuthToken survives

GET    /api/v1/integrations/gmail/subscription/picker/labels      # vendor data
```

PATCH validates via `GmailProvider.validate_config(config)` (which calls
`jsonschema.validate(config, self.config_schema)` + cross-field
`allOf` rules).

## UI shape (frontend reference)

```
Gmail
├── Mode  ◯ Everything   ◯ Last N days   ● Specific labels/filters
│
├── (mode=time_window)
│     Days: [ 30 ]
│
└── (mode=subscriptions)
      ├── Labels      [ Add… ] → picker modal
      │   ✓ Acme Client       (Label_42)
      │   ✓ Sales               (Label_17)
      ├── Queries     [ + Add query ]
      │   from:boss@acme.com
      ├── Domains     [ + Add domain ]
      │   acme.com
      │   *.partner-corp.com
      └── [Save]
```

## Cold-start / mode-switch behavior

| Action | Behavior |
|---|---|
| First pair | `cold_start_done=false`, time_window mode → next beat tick fetches `newer_than:30d` (or configured days) |
| After first sync | `cold_start_done=true`, subsequent ticks fetch `newer_than:1h` only |
| User switches `time_window 30d → 90d` | Reset `cold_start_done=false` so next tick re-runs backfill (fetches msgs 30-90d old) |
| User switches `time_window → subscriptions` | Reset `cold_start_done=false`; next tick backfills matching messages |
| User switches `subscriptions → everything` | Reset `cold_start_done=false`; next tick backfills all (no window) |
| User narrows (everything → subscriptions) | `cold_start_done` left as is; no backfill needed; existing `DeliveryPackage` rows for unmatched messages stay (history is history) |

`cold_start_done` lives in `state.global`. Toggled to false on
broadening config changes, true after backfill completes.

## Files to modify

| File | Change |
|---|---|
| `donna/integrations/connectors/google/mail/provider.py` | Add `config_schema`, `default_config`, `validate_config`, `picker` |
| `donna/integrations/connectors/google/mail/tasks.py` | Replace token-iteration with Connection-iteration; add `_build_query` + state management |
| `donna/integrations/connectors/google/mail/client.py` | Add `list_labels()` if not present |

## Verification (post-implementation)

```bash
cd server

# Bootstrap as today
DJANGO_SETTINGS_MODULE=donna.settings .venv/bin/python -m django integrations_bootstrap

# Verify schema validates
DJANGO_SETTINGS_MODULE=donna.settings .venv/bin/python -c "
import django; django.setup()
from donna.core.integrations import get
p = get('gmail')()
p.validate_config({'mode': 'time_window', 'time_window_days': 30})  # ok
p.validate_config({'mode': 'subscriptions', 'labels': ['Label_42']})  # ok
try:
    p.validate_config({'mode': 'subscriptions'})  # should fail: no filter
except Exception as e: print('expected validation error:', e)
"

# E2E (manual)
# 1. Pair Gmail via OAuth callback
# 2. Verify Connection row auto-created with default_config
# 3. PATCH /api/v1/integrations/gmail/subscription/ with subscriptions config
# 4. Wait one beat tick, verify DeliveryPackage rows match filter
# 5. Switch mode to everything, verify backfill triggers (cold_start_done=false)
```

## Open gaps (deferred)

1. **Per-label History API cursor** — v1 still polls `messages.list`
   per beat tick. Once `OAuthToken.metadata["history_id"]` lands, switch
   to incremental sync per label. Per-stream state shape already
   future-proofs this.
2. **Push notifications via Pub/Sub** — Gmail supports
   `users.watch()` → Pub/Sub topic. Defer; would unlock real-time
   ingest but adds infrastructure cost.
3. **AND-combined filters** — v1 ORs all filters (any match ingests).
   Add `mode: "subscriptions_and"` if real-world demand emerges.
4. **Filter validation against Gmail query syntax** — v1 accepts raw
   strings. Bad queries return zero results; harmless but confusing.
   Validation via Gmail `messages.list?q=…&maxResults=0` round-trip
   deferred.
5. **Wildcard domain expansion** — v1 emits `from:*@acme.com` for
   `acme.com`. Gmail accepts `*` only in the local part. `*.acme.com`
   (subdomain wildcard) needs expansion to `from:*@*.acme.com` (also
   supported). Confirm syntax during impl.

## Out of scope

- Per-message label apply (write-back from Donna)
- Send-as-user
- Draft creation
- Bulk-archive / bulk-delete actions
- Tests (per session policy)
- Migrations applied (per session policy)
