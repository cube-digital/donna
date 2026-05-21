# Google Drive Integration

> Status: **Locked design contract.** Builds on `08-connection-pattern.md`
> + `08a-gmail-integration.md`. Reuses `GoogleOAuthHandler` and
> `BaseGoogleClient` from the Google vendor folder.

## Context

After Gmail, Drive is the second Google connector. Same OAuth (`google`
vendor slug, shared `OAuthToken` row), new product (`drive` connector
slug, new `Connection` row).

Use case: ingest **user-selected files and folders** into Donna's
context. Some users want the **whole drive**; some want **specific
folders** (e.g., `/Engineering/`); some want **just a few files**. v1 is
read-only ingest; write-back (Donna saves docs to Drive) is v2.

## Decisions (locked)

| Choice | Decision | Why |
|---|---|---|
| Vendor layout | **`connectors/google/drive/`** (nested under existing Google folder) | Shares OAuth + `BaseGoogleClient` with Gmail |
| Token scope | **`user`** | Personal Drive accounts; per-employee selection |
| Selection UX | **Hybrid: Google Picker for files + custom browser for folders** | Files: Picker is clean. Folders: need our own browser because Picker doesn't expose recursive selection well |
| OAuth scope strategy | **Progressive: start with `drive.file` only → upgrade to `drive.readonly` when user wants folder-watch** | Casual users never see the "see all your Drive" scary consent. Power users opt in |
| Default mode on pair | **`subscriptions`, empty file/folder list** | No surprise full-drive pulls. User must explicitly add what to ingest |
| Mode set | **`everything` / `subscriptions`** (no `time_window` — see Open gaps) | Drive's changes API doesn't have a natural time filter |
| Change detection | **Poll `changes.list` per Connection, Celery beat 5min** | Same shape as Gmail. Watch+Pub/Sub deferred |
| File-type coverage v1 | **Google Docs/Sheets/Slides (export to text) + PDFs (binary store, defer text)** | Office/media too messy for v1 |
| Shared Drives | **Included v1** (one extra param on every Drive API call) | Real users have docs in Shared Drives; low code cost |
| Subscription granularity | **File OR Folder (with recursive flag)** | Two clean primitives. v1 ignores wildcard glob support |
| Write-back | **Deferred to v2** but request `drive.file` at scope-upgrade time | Architecture-ready when agent actions land |

## Config schema

```python
class DriveProvider:
    slug                = "drive"
    display_name        = "Google Drive"
    category            = "documents"
    oauth_provider_slug = "google"           # shares OAuthToken with Gmail
    token_scope         = "user"

    default_config = {
        "mode": "subscriptions",
        "files":   [],
        "folders": [],
    }

    config_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type":    "object",
        "required": ["mode"],
        "properties": {
            "mode": {"enum": ["everything", "subscriptions"]},
            "files":   {
                "type":  "array",
                "items": {"type": "string", "maxLength": 64},   # Drive file IDs
            },
            "folders": {
                "type":  "array",
                "items": {
                    "type": "object",
                    "required": ["id", "recursive"],
                    "properties": {
                        "id":        {"type": "string", "maxLength": 64},
                        "name":      {"type": "string", "maxLength": 255},
                        "recursive": {"type": "boolean"},
                        "drive_id":  {"type": ["string", "null"], "maxLength": 64},   # Shared Drive ID
                    },
                    "additionalProperties": False,
                },
            },
        },
        "allOf": [
            # `mode=everything` requires `drive.readonly` scope on the token
            # (validated at PATCH time by validate_config, not declarable in pure JSON Schema)
        ],
        "additionalProperties": False,
    }
```

## OAuth scope progression

```
┌──────────────────────────────────────────────────────────────────────┐
│  Step 1: Initial connect (default flow)                              │
│                                                                       │
│  User clicks "Connect Drive" (first time)                            │
│    OAuth requests scope: drive.file                                  │
│    Consent screen says: "View and manage Google Drive files and     │
│      folders that you have opened or created with this app"         │
│    Casual users see only this — no scary message                    │
│                                                                       │
│  Capabilities at drive.file:                                         │
│    ✓ Picker returns file/folder IDs; app gets read access            │
│    ✓ User can add individual files via Picker                        │
│    ✗ Cannot browse user's Drive tree (would need drive.readonly)    │
│    ✗ Cannot watch folders for new files (drive.file only sees       │
│      explicitly picked items, not folder descendants added later)   │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              │ User wants folder watching
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Step 2: Scope upgrade (opt-in)                                      │
│                                                                       │
│  POST /api/v1/integrations/drive/subscription/upgrade-scope          │
│    Returns: {auth_url}                                               │
│  Frontend redirects user to auth_url                                 │
│    Google re-prompts requesting drive.readonly + drive.file          │
│    Consent says: "See all your Google Drive files"                  │
│    User confirms with eyes open                                      │
│                                                                       │
│  Capabilities at drive.readonly + drive.file:                        │
│    ✓ All of above                                                    │
│    ✓ Custom folder browser (files.list?q='folder_id' in parents)    │
│    ✓ Recursive watch via changes.list                                │
│    ✓ Subscribe folders + recursive flag                              │
└──────────────────────────────────────────────────────────────────────┘
```

Token's `scope` field updates on upgrade callback. `validate_config`
rejects `mode=everything` or any folder subscription if token lacks
`drive.readonly`:

```python
def validate_config(self, config: dict, *, connection) -> dict:
    jsonschema.validate(config, self.config_schema)

    scopes = set((connection.token.scope or "").split())
    needs_readonly = (
        config["mode"] == "everything"
        or bool(config.get("folders"))
    )
    if needs_readonly and "https://www.googleapis.com/auth/drive.readonly" not in scopes:
        raise ValidationError(
            "Folder watching and 'everything' mode require drive.readonly scope. "
            "Call POST /subscription/upgrade-scope to grant it."
        )
    return config
```

## State shape

```jsonc
{
  "streams": {
    "1AbC...":  {"file_modified_time": "...", "last_synced_at": "..."},
    "1XyZ...":  {"folder_change_token": "...", "last_synced_at": "..."}
  },
  "global": {
    "drive_change_token": "page-token-xyz",
    "cold_start_done":    true
  }
}
```

`global.drive_change_token` is the page token from `changes.list` for
the whole drive (used by `mode=everything` or as a top-level cursor when
folder-cursors are stale).

## Sync task

```python
@shared_task(name="integrations.google.drive.sync")
def sync_drive_connection(connection_id: str) -> dict:
    from donna.integrations.models import Connection
    conn = (
        Connection.objects
        .select_for_update()
        .select_related("token")
        .get(id=connection_id, provider_slug="drive", enabled=True)
    )
    cfg, state = conn.config, conn.state
    provider = get_provider("drive")

    with provider.client(conn.token) as client:
        if cfg["mode"] == "everything":
            enqueued = _sync_everything(client, conn, state)
        else:  # subscriptions
            enqueued = _sync_subscriptions(client, conn, cfg, state)

    conn.last_synced_at = now()
    conn.save(update_fields=["state", "last_synced_at"])
    return {"enqueued": enqueued}


def _sync_everything(client, conn, state):
    page_token = state.setdefault("global", {}).get("drive_change_token")
    if not page_token:
        page_token = client.get_changes_start_token()
        state["global"]["drive_change_token"] = page_token
    enqueued = 0
    for change in client.iter_changes(page_token, include_corpora="allDrives"):
        if change.get("removed"):
            continue
        file_id = change.get("fileId")
        if file_id:
            ingest_drive_file.delay(str(conn.workspace_id), str(conn.token_id), file_id)
            enqueued += 1
    state["global"]["drive_change_token"] = client.last_change_token
    return enqueued


def _sync_subscriptions(client, conn, cfg, state):
    enqueued = 0
    # Direct file subscriptions
    for file_id in cfg.get("files", []):
        ingest_drive_file.delay(str(conn.workspace_id), str(conn.token_id), file_id)
        enqueued += 1
    # Folder subscriptions
    for folder in cfg.get("folders", []):
        for file_id in client.iter_folder_descendants(folder["id"], recursive=folder["recursive"]):
            ingest_drive_file.delay(str(conn.workspace_id), str(conn.token_id), file_id)
            enqueued += 1
    return enqueued
```

`ingest_drive_file(workspace_id, token_id, file_id)`:
- Fetch full metadata via `files.get`
- If Google-native (`mimeType in {application/vnd.google-apps.document, .spreadsheet, .presentation}`): `files.export?mimeType=text/plain` → store
- If PDF: `files.get?alt=media` → store binary
- If Office/media: store metadata + raw bytes; defer extraction
- Upsert `DeliveryPackage(workspace, "drive", file_id, ...)`

## Beat fanout

```python
@shared_task(name="integrations.google.drive.fanout_sync")
def fanout_drive_sync() -> dict:
    from donna.integrations.models import Connection
    ids = (
        Connection.objects
        .filter(provider_slug="drive", enabled=True)
        .values_list("id", flat=True)
    )
    for cid in ids:
        sync_drive_connection.delay(str(cid))
    return {"connections": ids.count()}
```

Add to `settings.py`:
```python
CELERY_BEAT_SCHEDULE["drive-fanout-sync"] = {
    "task":     "integrations.google.drive.fanout_sync",
    "schedule": env.int("DONNA_DRIVE_SYNC_INTERVAL", default=300),
}
```

## Picker — two endpoints

```python
class DriveProvider:
    def picker(self, resource: str, params: dict, *, connection) -> dict:
        with self.client(connection.token) as client:
            if resource == "browse":
                # Custom folder browser (needs drive.readonly)
                parent  = params.get("parent")   # folder ID or "root"
                drive_id = params.get("drive_id")  # Shared Drive ID, optional
                resp = client.list_children(parent=parent or "root", drive_id=drive_id)
                return {
                    "items": [
                        {
                            "id":         f["id"],
                            "name":       f["name"],
                            "mime_type":  f["mimeType"],
                            "is_folder":  f["mimeType"] == "application/vnd.google-apps.folder",
                            "modified":   f.get("modifiedTime"),
                        }
                        for f in resp.get("files", [])
                    ],
                    "next_page_token": resp.get("nextPageToken"),
                }
            if resource == "drives":
                # List Shared Drives (needs drive.readonly)
                resp = client.list_shared_drives()
                return {"drives": [{"id": d["id"], "name": d["name"]} for d in resp.get("drives", [])]}
        raise ValueError(f"Drive picker has no resource '{resource}'")
```

Frontend usage:

```
GET /api/v1/integrations/drive/subscription/picker/drives
    → list of Shared Drives + My Drive

GET /api/v1/integrations/drive/subscription/picker/browse?parent=root
    → top-level of My Drive

GET /api/v1/integrations/drive/subscription/picker/browse?parent=1XyZ&drive_id=0AbCd
    → contents of folder 1XyZ inside Shared Drive 0AbCd
```

User clicks folder checkbox → frontend collects file/folder IDs →
`PATCH /api/v1/integrations/drive/subscription/` with full config blob.

For Picker-style file picking (cleaner UX for ad-hoc files): frontend
embeds Google Picker JS API directly, posts selected IDs to PATCH. No
new backend endpoint.

## API

```
GET    /api/v1/integrations/drive/subscription/
PATCH  /api/v1/integrations/drive/subscription/                       # update config (validated)
DELETE /api/v1/integrations/drive/subscription/                       # delete Connection only; token survives

POST   /api/v1/integrations/drive/subscription/upgrade-scope          # returns auth URL with drive.readonly + drive.file

GET    /api/v1/integrations/drive/subscription/picker/drives          # list Shared Drives
GET    /api/v1/integrations/drive/subscription/picker/browse          # folder contents (params: parent, drive_id)
```

`upgrade-scope` is a Drive-specific `@action` on `ConnectionViewSet` (or
a new method on `DriveProvider` invoked through a generic
`/subscription/action/:name` endpoint). v1: hard-code it as Drive-specific.

## Adapter (`DriveFileAdapter`)

Raw shape: `files.get(fileId, fields="*")` response.

```python
class DriveFileAdapter(BaseAdapter):
    def external_id(self) -> str:
        return self.raw["id"]

    def title(self) -> str:
        return self.raw.get("name") or "(untitled)"

    def occurred_at(self) -> datetime:
        # Use modifiedTime; fall back to createdTime
        ts = self.raw.get("modifiedTime") or self.raw.get("createdTime")
        return parse_rfc3339(ts) if ts else now()

    def to_json(self) -> dict:
        return self.raw

    def to_text(self) -> str:
        # Populated by ingest task after files.export call;
        # adapter walks raw["_donna_exported_text"] if present
        return self.raw.get("_donna_exported_text", "")

    def metadata(self) -> dict:
        return {
            "mime_type":      self.raw.get("mimeType"),
            "size":           self.raw.get("size"),
            "owners":         [o.get("emailAddress") for o in self.raw.get("owners", [])],
            "modified_time":  self.raw.get("modifiedTime"),
            "created_time":   self.raw.get("createdTime"),
            "parents":        self.raw.get("parents", []),
            "drive_id":       self.raw.get("driveId"),
            "web_view_link":  self.raw.get("webViewLink"),
            "trashed":        self.raw.get("trashed", False),
            "starred":        self.raw.get("starred", False),
        }
```

## File-type handling v1

| mimeType | v1 behavior |
|---|---|
| `application/vnd.google-apps.document` | Export `text/plain` + `text/html`; store both; `to_text` returns plain |
| `application/vnd.google-apps.spreadsheet` | Export `text/csv` per sheet; store concatenated |
| `application/vnd.google-apps.presentation` | Export `text/plain`; store |
| `application/pdf` | `files.get?alt=media` → store binary; `to_text` defers (PDF extraction = open gap) |
| `application/vnd.google-apps.folder` | Skip (folders aren't ingested as items; their descendants are) |
| Other (Office docx/xlsx, images, video) | v1: store binary + metadata only; `to_text` empty |

## Storage layout

```
{workspace_id}/google/drive/files/{file_id}.json    # raw metadata
{workspace_id}/google/drive/files/{file_id}.txt     # extracted text (when available)
{workspace_id}/google/drive/files/{file_id}.bin     # binary blob (PDFs, Office files)
```

Idempotent overwrite same as Gmail.

## Files to create

| File | Purpose |
|---|---|
| `donna/integrations/connectors/google/drive/__init__.py` | Module marker |
| `donna/integrations/connectors/google/drive/provider.py` | `DriveProvider` with `config_schema`, `default_config`, `validate_config`, `picker`, `client`, `oauth_handler`, `adapter_for` |
| `donna/integrations/connectors/google/drive/client.py` | `DriveClient(BaseGoogleClient)` with `list_children`, `list_shared_drives`, `iter_changes`, `iter_folder_descendants`, `get_file`, `export_file`, `download_file_media`, `get_changes_start_token` |
| `donna/integrations/connectors/google/drive/adapter.py` | `DriveFileAdapter(BaseAdapter)` |
| `donna/integrations/connectors/google/drive/tasks.py` | `sync_drive_connection`, `fanout_drive_sync`, `ingest_drive_file` |

No new framework code. `donna/core/integrations/*` unchanged.

## Files to modify

| File | Change |
|---|---|
| `donna/settings.py` | Add `drive-fanout-sync` to `CELERY_BEAT_SCHEDULE` |
| `donna/integrations/connectors/google/oauth.py` | Add `upgrade_scope_auth_url(token, additional_scopes)` helper if not already present (re-uses existing flow with `include_granted_scopes=true`) |

## Verification (post-implementation)

```bash
cd server

# 1. Boot check
DJANGO_SETTINGS_MODULE=donna.settings .venv/bin/python -m django check

# 2. Connector registered
DJANGO_SETTINGS_MODULE=donna.settings .venv/bin/python -c "
import django; django.setup()
from donna.core.integrations import all_loaded
print(sorted(c.slug for c in all_loaded()))
"
# expect: ['drive', 'fathom', 'gmail']

# 3. Bootstrap sees Drive in scope union with Gmail
DJANGO_SETTINGS_MODULE=donna.settings .venv/bin/python -m django integrations_bootstrap
# Inspect OAuthProvider(slug='google').scopes — should now union
# gmail.modify + drive.file (+ drive.readonly after upgrade)

# 4. E2E (manual, requires browser)
# - Pair Google (initial scope = drive.file only)
# - Connection auto-created with default_config (subscriptions, empty)
# - GET /subscription/picker/browse?parent=root → empty/some items at drive.file
# - PATCH /subscription/ with {files: [...]} (file subs work at drive.file)
# - PATCH /subscription/ with {folders: [...]} → ValidationError (needs readonly)
# - POST /subscription/upgrade-scope → auth URL
# - User completes upgrade in browser
# - Retry folder PATCH → succeeds
# - Wait beat tick → DeliveryPackage rows created
```

## Open gaps (deferred)

1. **PDF text extraction.** v1 stores PDFs as binary; `to_text` returns
   empty. Defer text extraction (need pypdf or pdfplumber).
2. **Office file extraction (docx, xlsx, pptx).** v1 stores binary +
   metadata only. Defer.
3. **Time-window mode.** Drive's changes API has no native "older than
   X" filter. Would require enumerating + client-filter on
   `modifiedTime`. Defer.
4. **Push notifications (Watch + Pub/Sub).** Real-time ingest. Defer;
   beat polling fine for v1.
5. **Wildcard / glob path subscriptions.** "Watch `**/*.pdf` in this
   folder." Defer; folder + recursive flag covers most cases.
6. **Write-back.** `files.create`, `files.update`, `files.copy`.
   Architecture-ready (token has `drive.file` scope from day one) but
   no endpoints v1.
7. **Permission-change-aware revocation.** If a shared file is
   un-shared with the user, current code keeps the `DeliveryPackage`
   row. v2: detect 404 on next sync, mark archived.
8. **Conflict resolution.** Two users in a workspace pair Drive, both
   watch the same Shared Drive folder. `changes.list` runs per
   Connection → same file ID processed twice → idempotent upsert
   absorbs. Wasteful but harmless. v2: per-vendor dedup of in-flight
   file IDs.
9. **Drive scopes union with Gmail in `integrations_bootstrap`.**
   `OAuthProvider(slug="google").scopes` must union from all
   connectors. Verify existing bootstrap handles this correctly when
   Drive connector lands.

## Out of scope

- Write-back (deferred to v2)
- PDF / Office text extraction
- Per-permission audit log
- Selective sync of just metadata (always full file in v1)
- Tests (per session policy)
- Migrations applied (per session policy)
