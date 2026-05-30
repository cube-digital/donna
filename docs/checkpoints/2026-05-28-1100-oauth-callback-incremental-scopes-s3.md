# 2026-05-28 11:00 — OAuth Callback / Incremental Scopes / S3 Storage

## Summary & Overview

Session resolved a chain of integration framework bugs starting from "no
integration registered under slug 'google'" through to Gmail messages
landing in MinIO. Three structural fixes:

1. OAuth handler scopes pin to the calling connector (not unioned across
   the vendor) so Gmail's consent doesn't request Drive scopes.
2. OAuth callback URL treats slug as vendor (`google`), not connector
   (`gmail`/`drive`) — connector identity rides in signed state.
3. Google `Flow` auto-PKCE disabled (lib default flipped to True in
   recent versions) — restored narrio-style confidential-client flow.

Plus operational fixes: storage backend swapped to MinIO/S3, worker +
beat picked up source mount, `created` log key collision, `redis`/`cache`
service-name mismatch in env.

Ended with Gmail sync ingesting two messages into `donna-dev` bucket.
Drive needs subscriptions configured before sync enqueues anything.
Fathom token still carries `whsec_*` (webhook secret) in `client_secret`
— OAuth path will fail until real OAuth client_secret pasted.

## Key Learnings

- **`include_granted_scopes=true` + single-token-per-vendor design** —
  Required together. Without `include_granted_scopes`, second connect
  (Drive after Gmail) returns a token with only Drive scope. Because
  `OAuthToken.update_or_create` keys on `(provider, user)` and the
  `provider` row is vendor-scoped (`google`), that token overwrites the
  Gmail one → Gmail API breaks. With `include_granted_scopes`, Google
  unions previously-granted scopes into the new token and consent shows
  both — full disclosure side-effect we accept.
- **`creds.scopes` vs `flow.oauth2session.token['scope']`** —
  `google.oauth2.credentials.Credentials.scopes` mirrors what was
  *requested*, not what was *granted*. After
  `flow.fetch_token`, the granted-scope source of truth is the raw token
  response at `flow.oauth2session.token["scope"]`. We stored requested
  scopes for a while, which made the admin view misleading even though
  the token itself had the correct grants on Google's side.
- **`google_auth_oauthlib.Flow` autogenerate_code_verifier default flipped to True** —
  Recent lib versions set `autogenerate_code_verifier=True` in
  `Flow.__init__`. `Flow.authorization_url()` then adds a `code_challenge`
  to the authorize URL, and Google's token endpoint then demands a
  matching `code_verifier` on exchange. We were building a fresh `Flow`
  per call → verifier from the authorize flow died with that instance →
  exchange got `(invalid_grant) Missing code verifier`. Narrio works on
  an older lib version where the default was `False`.
- **PKCE for confidential clients is optional but lib-default opt-in** —
  Two valid fixes: implement PKCE end-to-end (verifier in signed state),
  or disable auto-PKCE in `_flow()` and stay on `client_secret_basic`.
  We chose the second (option A) to match narrio.
- **OAuth callback URL = vendor slug, connector slug rides in state** —
  One Google OAuth client means one registered redirect URI. Gmail and
  Drive both call back to `.../google/oauth/callback`. The connector
  being connected is `state_payload["slug"]`. The URL slug only needs
  to match `cls.oauth_provider_slug` for the connector found by state.
- **PKCE state-decoding doesn't need a handler** — `signing.dumps` salt
  is framework-level. `BaseOAuthHandler.verify_state` was made
  `@staticmethod` so the callback view can decode state before knowing
  which `ClientCredentials` row to use.
- **Self-hosted S3 config is a single env-var pattern** — Every project
  (n8n, Mastodon, Outline, Penpot, Plausible, Directus, Nextcloud,
  Supabase) uses the same shape: provider switch + S3 block with
  endpoint_url, access_key, secret_key, bucket, region,
  addressing_style, use_ssl. Donna already matches. Operator points
  `DONNA_S3_ENDPOINT_URL` at any S3-compatible service (real S3, R2,
  B2, Wasabi, MinIO, SeaweedFS, Garage, LocalStack) without code
  changes.

## Solutions & Fixes

- **`POST /api/v1/integrations/google/connect/` → 404 "no integration registered under slug 'google'"** →
  `google` is a vendor folder, not a connector. Registered slugs are
  `gmail`, `drive`, `fathom`. Use `gmail`/`drive` connect endpoints
  instead. Root cause: confusing the vendor slug (`oauth_provider_slug`)
  with the connector slug.
- **Gmail consent showed Drive scopes too (unwanted scope union on first connect)** →
  `BaseOAuthHandler.__init__` now accepts optional `connector_cls`.
  `default_scopes` returns only pinned connector's scopes when set;
  unions otherwise. Each provider's `oauth_handler()` factory passes
  `type(self)`. Root cause: `default_scopes` unioned across all
  connectors sharing the credentials row.
- **OAuth callback hit `/google/oauth/callback` → `Not Found: unknown integration 'google'`** →
  `RegistryService.handle_callback` now decodes signed state first,
  reads connector slug from `state_payload["slug"]`, verifies URL slug
  matches `cls.oauth_provider_slug`. `Connection.provider_slug` now
  uses connector slug, not URL vendor slug. `verify_state` made
  `@staticmethod`. View + URL docs updated to call the path slug
  "vendor_slug". Root cause: callback view treated URL slug as
  connector slug.
- **Google token exchange `(invalid_grant) Missing code verifier`** →
  `GoogleOAuthHandler._flow()` now sets
  `flow.autogenerate_code_verifier = False` + `flow.code_verifier = None`.
  Root cause: `google_auth_oauthlib.Flow.__init__` default flipped to
  `True` in our installed version → authorize URL grew a `code_challenge`
  → exchange (built on a fresh `Flow`) had no verifier to replay.
- **Stored `OAuthToken.scope` only showed `drive.file` after second consent** →
  `GoogleOAuthHandler.exchange_code` now reads
  `flow.oauth2session.token.get("scope")` for actually-granted scopes
  with `" ".join(creds.scopes or [])` as fallback. Root cause:
  `creds.scopes` returns the requested scope list, not the granted one.
  Existing token's access/refresh still work for both scopes (Google's
  view) — only our local string was short.
- **`PermissionError: [Errno 13] Permission denied: '/app'` during Gmail ingest** →
  `DONNA_FILESYSTEM_ROOT` was `/app/var/storage` but WORKDIR is
  `/opt/donna`. Updated to `/opt/donna/var/storage`, but ultimately
  superseded by switching to S3 backend.
- **Celery worker `Cannot connect to redis://redis:6379/0`** →
  Compose service is named `cache`, not `redis`. Updated
  `CELERY_BROKER_URL=redis://cache:6379/0` in `env/.env.docker`.
  Required `docker compose up -d --force-recreate worker beat` —
  `restart` doesn't reload `env_file`.
- **`KeyError: "Attempt to overwrite 'created' in LogRecord"`** —
  `logger.info(..., extra={"created": ...})` collides with stdlib
  `LogRecord` built-in field. Renamed key to `row_created` in Gmail,
  Drive, and Fathom ingestion tasks (`extra` dicts only — return values
  unchanged).
- **Worker still running pre-fix code after host edit** →
  `worker` + `beat` services had no `volumes:` block; only `server` did.
  Added `./donna:/opt/donna/donna` mount to both in
  `docker-compose.yml`. Source reload now applies to Celery side too.
- **MinIO setup for local S3 dev** →
  Added `storage` (`minio/minio`) + `storage-init` (`minio/mc`) services
  to compose. `DONNA_S3_*` env vars wired. Verified end-to-end:
  default_storage = `S3Storage`, health-check write succeeds, Gmail
  ingest now writes to `donna-dev/<workspace_id>/google/mail/messages/`.

## Decisions Made

- **Option A (disable auto-PKCE) over Option B (full PKCE)** — chose
  parity with narrio + simpler code over RFC-recommended PKCE posture.
  Reversible — code that briefly implemented PKCE end-to-end was
  reverted.
- **Single Connection row per (workspace, user, connector_slug)** —
  retained existing model. Drive uses connector slug `drive`, Gmail uses
  `gmail`. Both pointing at the same `OAuthToken` (shared Google vendor
  row) is OK by design.
- **Callback URL = vendor slug** — chose vendor-level callback URL
  (one redirect URI in Google Cloud) over per-connector URLs (would
  require listing gmail + drive + calendar paths in Google Cloud's
  authorized URIs). State payload carries connector identity.
- **`include_granted_scopes="true"` stays on** — required for single
  shared OAuthToken design. Cosmetic side-effect (consent shows all
  granted scopes) accepted.
- **MinIO for local dev S3** — chose MinIO over SeaweedFS/Garage/
  LocalStack for now. User flagged MinIO restrictions; awaiting choice
  before swapping. Pattern in compose is generic — env vars don't
  change.
- **Don't bump task list with the small refactors** — existing 61
  completed tasks reflect a previous milestone. New work was bug-fix
  scope inside completed phases; opted not to clutter the list.

## Pending Tasks

- [ ] **Decide local S3 dev container.** Reply to "MinIO not available"
  with which of {MinIO-stay, SeaweedFS, Garage, LocalStack} to wire.
  All work via existing `DONNA_S3_*` env vars — only the compose
  service changes.
- [ ] **Reconnect Gmail or Drive** to refresh `OAuthToken.scope` string
  to the full granted-scope union. Current row was created before the
  `flow.oauth2session.token["scope"]` fix.
- [ ] **Fix Fathom `ClientCredentials.client_secret`** — currently
  contains `whsec_zT…` (webhook signing secret). Paste the real OAuth
  client_secret from Fathom dashboard. Re-run sanity check:
  ```
  docker compose exec -T server python manage.py shell -c "
  import httpx
  from donna.integrations.models import ClientCredentials
  c = ClientCredentials.objects.filter(slug='fathom').first()
  r = httpx.post('https://fathom.video/external/v1/oauth2/token',
      data={'grant_type':'authorization_code','code':'fake','redirect_uri':c.redirect_uri},
      auth=(c.client_id, c.client_secret or ''), timeout=10.0)
  print(r.status_code, r.text)"
  ```
  Expected after fix: `400 invalid_grant` instead of `401 invalid_client`.
- [ ] **Configure Drive subscriptions** so `sync_drive_connection`
  enqueues something. Currently returns `{'enqueued': 0, 'mode': 'subscriptions'}`.
  PATCH `/api/v1/integrations/drive/subscription/` with picker-selected
  folder IDs.
- [ ] **Test Fathom webhook ingestion** once OAuth is fixed. Either
  send a signed test webhook to
  `/api/v1/integrations/fathom/webhook/callback` or invoke
  `ingest_fathom_meeting.delay(workspace_id, meeting_id)` directly.
- [ ] **Verify Celery beat is firing** Gmail + Drive fanouts on the
  configured interval (`DONNA_GMAIL_SYNC_INTERVAL=300`,
  `DONNA_DRIVE_SYNC_INTERVAL=300`). Tail `docker compose logs beat`.
- [ ] **Run migrations to drop legacy columns** if not already done —
  `authorize_url`, `token_url`, `default_scopes` were removed from
  `ClientCredentials` model earlier in the milestone.

## Errors & Workarounds

- **`null value in column "authorize_url"` IntegrityError** — schema
  still had dropped columns. Workaround: `docker compose run --rm server python manage.py makemigrations integrations && docker compose run --rm server python manage.py migrate`.
- **`oauth_callback_state_invalid`** — SECRET_KEY rotating on each
  container restart because `.env` was missing it (default = fresh
  `secrets.token_urlsafe()`). Workaround: set persistent SECRET_KEY in
  `env/.env.docker`. Side effect: `EncryptedTextField` ciphertext
  invalidated, requiring re-paste of admin credentials.
- **`(invalid_client)` from Fathom token endpoint with both Basic and body auth** —
  not an auth-method issue. Workaround: identified `whsec_*` prefix in
  `client_secret` field is Stripe/Svix-style webhook signing secret
  convention, not OAuth client secret. Pending real OAuth secret paste.
- **`InsecureKeyLengthWarning: HMAC key is 24 bytes`** — same root
  cause as state-invalid. Fixed by setting persistent SECRET_KEY.
- **`TemplateDoesNotExist drf_spectacular/swagger_ui.html`** —
  `drf_spectacular` missing from `INSTALLED_APPS`. Added.
- **`PermissionError: 'celerybeat-schedule'`** — CWD not writable for
  beat container. Workaround: `--schedule=/tmp/celerybeat-schedule` in
  compose command.
- **`Cannot connect to redis://redis:6379/0: Error -2 ... Name or service not known`** —
  compose service is `cache`. Fixed `CELERY_BROKER_URL` env to
  `redis://cache:6379/0`.
- **`KeyError("Attempt to overwrite 'created' in LogRecord")`** —
  `extra={"created": ...}` collides with stdlib LogRecord. Renamed to
  `row_created` in all three ingestion tasks.
- **`docker compose exec -T storage-init …`** failed with
  `service "storage-init" is not running` — `storage-init` is a
  one-shot, not a long-running service.

## Files Modified

- `server/donna/core/integrations/oauth.py` —
  `BaseOAuthHandler.__init__` accepts `connector_cls=None`;
  `default_scopes` per-connector when pinned; `_primary_connector()`
  helper; `verify_state` → `@staticmethod`.
- `server/donna/integrations/services.py` —
  `handle_callback` decodes state first, treats URL slug as vendor,
  uses connector slug for `Connection.provider_slug`. Removed PKCE
  passthrough that briefly existed.
- `server/donna/integrations/urls.py` — docstring clarified that
  callback path takes vendor slug.
- `server/donna/integrations/api/v1/oauth.py` — module docstring
  rewritten to explain vendor-slug callback + connector-in-state.
- `server/donna/integrations/connectors/google/oauth.py` —
  `_flow()` disables `autogenerate_code_verifier`;
  `exchange_code()` reads `flow.oauth2session.token["scope"]` for
  granted-scope source of truth.
- `server/donna/integrations/connectors/google/mail/provider.py` —
  `oauth_handler` passes `connector_cls=type(self)`.
- `server/donna/integrations/connectors/google/drive/provider.py` —
  same.
- `server/donna/integrations/connectors/fathom/provider.py` — same.
- `server/donna/integrations/connectors/google/mail/tasks.py` —
  `extra={"created": …}` → `row_created`.
- `server/donna/integrations/connectors/google/drive/tasks.py` — same.
- `server/donna/integrations/connectors/fathom/tasks.py` — same.
- `server/env/.env.docker` — `CELERY_BROKER_URL=redis://cache:6379/0`,
  `DONNA_FILESYSTEM_ROOT=/opt/donna/var/storage`,
  `DONNA_STORAGE_BACKEND=s3` + full `DONNA_S3_*` block (MinIO local).
- `server/docker-compose.yml` — added `storage` (MinIO) +
  `storage-init` (mc) services + `minio_data` volume; added
  `volumes: ./donna:/opt/donna/donna` to `worker` and `beat`.

## Blockers & External Dependencies

- **Fathom OAuth dashboard access** — user must reveal the real OAuth
  client_secret (not the `whsec_*` webhook secret) to unblock Fathom
  end-to-end testing. Unblocks when: real client_secret pasted into
  admin and sanity check returns `400 invalid_grant`.
- **MinIO container availability** — user said "MinIO not available
  anymore". Pending choice between SeaweedFS / Garage / LocalStack /
  real cloud S3 before finalizing local dev compose. Unblocks when:
  user picks one of those.
