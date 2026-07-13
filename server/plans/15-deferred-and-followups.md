# 15 — Deferred items & follow-ups

Running list of leftovers, flags, and known-but-not-yet-fixed issues surfaced
while standing up the **staging dev loop** (mirrord + db-tunnel) and testing the
connector/agent flows. Captured **2026-07-13**.

Status legend: 🔴 open · 🟡 done-but-uncommitted (local working tree) · 🟢 done+pushed · 🔵 reference

---

## 1. Security & secret rotation (do first)

| # | Status | Item | Action |
|---|---|---|---|
| 1.1 | 🔴 | `cube-staging` IAM **secret access key** (`…SCUO` / `aolnF3X…`) printed into a session transcript (grep of `~/.aws/credentials`). | Rotate the access key in IAM. |
| 1.2 | 🔴 | Staging **DB password** + **Redis auth token** printed into a transcript (db-tunnel output). | Rotate in RDS / ElastiCache + update SSM `/staging/donna/{database,redis}/*`. |
| 1.3 | 🔴 | Admin login `admin@donna.ai` password stored in transcript **and** 1Password (`Donna Admin (staging)`). | Change the password after testing; it's a real staging **superuser**. |
| 1.4 | 🔴 | **Open redirect**: `IntegrationRegistryService.initiate_connect` 302s to any client-supplied `redirect_to` (`integrations/api/v1/oauth.py::_redirect_with_status`). Now actively used by the frontend (§3.2). | Validate `redirect_to` against an allowlist (`WEB_REDIRECT_HOST` / known origins) before redirecting. |

---

## 2. Infra / deployment (donna-cloud-infra repo)

| # | Status | Item | Action / context |
|---|---|---|---|
| 2.1 | 🟢 | HTTPS 443 listener on the donna ALB + `donna.test.qube-digital.net`. | Pushed: `argocd/apps/donna/values.yaml` (ACM `*.test.qube-digital.net` = `e532b005…`, `ssl-redirect`, host). Route53 alias A → ALB added by hand. |
| 2.2 | 🟢 | `DONNA_PUBLIC_BASE_URL` + `WEB_REDIRECT_HOST` + `CSRF_TRUSTED_ORIGINS` set for staging. | Pushed to `values.yaml`. `WEB_REDIRECT_HOST` currently = backend host; point at the real staging frontend once one is deployed. |
| 2.3 | 🔴 | **Cert + Route53 record are out-of-band** (hybrid approach). No `acm`/`route53` Terraform module exists. | Backfill to Terraform for reproducibility / on-prem parity. |
| 2.4 | 🔴 | Helm chart has **no `checksum/config` annotation** → ConfigMap changes don't roll pods (had to `kubectl rollout restart` twice this session). | Add a `checksum/config` pod-template annotation to `server/deploy/self_host/helm/templates/deployment-*.yaml`. |
| 2.5 | 🔴 | Local `docker-compose` **port mapping is wrong**: `donna-database` maps host `5551→5551` but Postgres listens on `5432` inside → host `psql` fails ("server closed the connection"). Worked around with `docker exec`. | Fix the mapping to `5551:5432` (or make PG listen on 5551). |
| 2.6 | 🔵 | `scripts/db-tunnel.sh` (socat proxy → RDS/ElastiCache) is **gitignored** in the private infra repo; shared via 1Password/Notion. Public app repo (`.gitignore`) blocks `*-tunnel.sh`. | Optional: add a pre-commit/gitleaks guard as a second wall. Runbook: `runbooks/02-local-db-tunnel.md`. |

---

## 3. Code fixes made this session (local working tree — **uncommitted**)

All in the `donna` repo `web/` unless noted. Live via Vite HMR under the mirrord
loop; **commit before they're lost.**

| # | Status | Item | Files |
|---|---|---|---|
| 3.1 | 🟡 | OAuth connect: **popup → full-page redirect** (popup was blocked — `window.open` after `await` loses user-activation; popup return also broke cross-origin in local dev). | `web/src/components/Integrations/useOAuthConnect.ts` |
| 3.2 | 🟡 | `connectIntegration(slug, redirectTo?)` now passes `redirect_to` = frontend origin so the callback returns to the SPA (backend default `/app/integrations` is relative → 404 on the API host). | `web/src/api/integrations.ts` |
| 3.3 | 🟡 | **SSE 401 loop** fixed: the notifications SSE client now calls `tryRefresh()` on 401 (was spinning forever on a stale token). `tryRefresh` exported from the API client. | `web/src/lib/sse.ts`, `web/src/api/client.ts` |
| 3.4 | 🟡 | **Stale-workspace self-heal**: on boot, validate the persisted `donna.workspace.active` against the user's real workspace list; clear it if absent (dead `X-Workspace-Id` → `Http404` → infinite "Loading…"). | `web/src/components/Shell/AppShell.tsx` |
| 3.5 | 🟡 | Dev proxy target `web/.env` `VITE_API_PROXY_TARGET` `8190 → 8000` (mirrord runserver port). | `web/.env` (local only) |

---

## 4. Backend / frontend — still open

| # | Status | Item | Action |
|---|---|---|---|
| 4.1 | 🔴 | Integrations **store swallows errors** → shows "Loading…" forever on a genuine (non-workspace) failure. | Add an `error` state + retry in `web/src/state/integrations.ts` + `views/Integrations.tsx`. |
| 4.2 | 🔴 | **Refresh stampede**: N concurrent 401s fire N `tryRefresh()` calls (saw 3 at once). Harmless today (rotation **off**), but breaks if `ROTATE_REFRESH_TOKENS` is ever enabled. | Single-flight `tryRefresh` (share one in-flight promise). |
| 4.3 | 🔴 | `ACCESS_TOKEN_LIFETIME = 15 min` → frequent expiry churn during long sessions. | Consider bumping for dev (env / chart), e.g. 60 min. |
| 4.4 | 🔵 | Under `runserver` (WSGI) the SSE stream returns `200`-then-closes every ~2s (reconnect churn). Real pod runs **uvicorn/ASGI** and holds it open. | Dev-only artifact; no action. Don't mistake for a bug. |
| 4.5 | 🟡 | **Shared-vendor connect marks all siblings connected** — connecting Gmail showed **Drive** as connected too. See §4.5-detail. **FIXED** (uncommitted): `is_connected` now keys on the per-connector `Connection` row in both `list_for_workspace` + `get_status`. Verified: gmail=CONNECTED, drive=not connected. | — |
| 4.6 | 🟡 | **mirrord + Django StatReloader** don't mix: rapid backend edits restart the child process and the mirrord layer doesn't survive the re-exec → `localhost:8000` listener dies → vite proxy `ECONNREFUSED` → **500 on every `/api` call**. | Run with `runserver --noreload` under mirrord (done); restart mirrord manually after backend edits. Documented in §7. Note: the local bind is still occasionally flaky on relaunch — a second clean restart binds. |
| 4.7 | 🟡 | **Invite 400 "Workspace context required"** — `WorkspaceMiddleware.IGNORED_PATHS` has `/api/v1/workspaces` (context-free create/list), but `startswith` also matched `/api/v1/workspaces/invitations/` (tenanted) → stripped the workspace → invite service 400'd. **FIXED** (uncommitted): added `TENANTED_UNDER_IGNORED` guard in `workspaces/middlewares.py`. Verified: invite → 201. | — |
| 4.8 | 🔴 | **No email delivery** — `EMAIL_BACKEND` defaults to `console`. Invitations / email-verify / password-reset create their rows + tokens but **no email is sent**. Fine for API testing; blocks the real invite/verify/reset UX. | Configure SMTP (`EMAIL_*`) in the chart for staging. |
| 4.9 | 🔴 | **Chat WebSocket dead under mirrord** — `runserver` (WSGI) doesn't serve `/ws/` → 404 loop; chat streaming/presence fail locally. The deployed pod (uvicorn/ASGI) is fine. | To exercise chat locally, run `runserver` via ASGI (Daphne/`uvicorn donna.asgi`) under mirrord, or test the agent via a shell (bypasses WS). |
| 4.10 | 🔴 | **React "hooks order" error in `IntegrationDetail`** after a connect state change — conditional hook usage (`web/src/views/IntegrationDetail.tsx`). Throws to the error boundary. | Move all hooks above early returns / conditionals. |
| 4.11 | 🟡 | **Anthropic key** was invalid (27-char placeholder) → agent LLM `401`. **FIXED:** valid key written to SSM `/staging/donna/anthropic/api_key` (108 chars). Conversational agent **verified working** — real grounded answer citing gmail:// + Fathom sources across 305 cortex items. **Deployed pods still need a rollout restart** to pick up the new key via ExternalSecret. | Rollout-restart the deployed pods. Rotate the key (it passed through a chat transcript). |
| 4.12 | 🔴 | **redis-py version mismatch (local vs deployed).** Local `.venv` has **7.4.0** which rejects the deployed Redis URL's `?ssl_cert_reqs=CERT_NONE` (`Invalid SSL Certificate Requirements Flag`) → `turn_lock` + channel-layer fail under mirrord. Deployed image's older redis-py accepts it. | Pin redis-py, or template the URL as `ssl_cert_reqs=none` (both versions accept lowercase). Agent turns via the Celery task need this to run locally. |

| 4.13 | 🟡 | **Cortex resource body "Failed to fetch"** — two layers: (a) `body_url` is a direct presigned S3 URL fetched cross-origin → **CORS blocked**; (b) even with CORS, the URL was **SigV2** but the bucket is **KMS-encrypted** → S3 `400 InvalidArgument` (KMS requires SigV4). **FIXED:** (a) added S3 CORS rule (applied to `tf-donna-staging-storage-…`, allows the SPA origins), (b) `signature_version=s3v4` in the S3 storage OPTIONS (`settings.py`, default on). Verified: body fetch → 200, content loads. **Deploy the settings change** so the real pod signs SigV4 too. Proper long-term: proxy the body through an authed backend endpoint. |
| 4.14 | 🟡 | **Cortex list over-fetch (slow).** The Files sidebar fired ~14 body-bearing list calls (one per type, each signing an S3 URL per row) on mount. **PARTIALLY FIXED:** added `GET /cortex/entities/counts/` (one aggregate GROUP BY) + rewired the content-type counts effect to use it. Verified: counts → 200 in one call. **Still open:** the entity-group effects (person/org×3/project) + main list still fetch full 200-item lists; lazy-load per selected category + only sign `body_url` on detail open. |

### §4.11-detail — conversational agent (use case #1) status

**Verified working (via a direct `run_graph` turn, bypassing the Redis `turn_lock`):**
- Agent graph executes: `build_state` → `build_registry` (mode-gated) → `run_graph` → `conversation_agent` node → LLM call.
- Graceful LLM-error handling (no crash; user-facing fallback text).
- Context is ready: 277 emails ingested → **379 cortex entities** for retrieval.

**Blocked only by the invalid Anthropic key (4.11).** Once a valid key is in place, re-run
`scratchpad/agent_turn_test.py` (or send a message in a channel with an `AgentSession`) to
confirm the LLM answers + calls `cortex_query`/`get_context` over the email context.

### §4.5-detail — Gmail connect also "connects" Drive

**Symptom:** connecting Gmail flips **both** Gmail and Drive to "connected" in the UI, even though only a Gmail `Connection` row exists.

**Root cause** — connection status is derived from the **shared vendor OAuth token**, not the per-connector `Connection`:

- `donna/integrations/services.py`
  - `list_for_workspace` (~L93-114): `connected_oauth_slugs = OAuthToken … .values_list("provider__slug")` → **vendor** slug (`"google"`); then `is_connected = cls.oauth_provider_slug in connected_oauth_slugs`.
  - `get_status` (~L141): `OAuthToken.objects.filter(provider__slug=cls.oauth_provider_slug).exists()`.
- Gmail **and** Drive both set `oauth_provider_slug = "google"` (one shared `ClientCredentials` row). So the moment a Google token exists, **every** Google connector reports `is_connected=True`.

**Evidence (staging RDS after the connect):** `Connection` rows = `{gmail, fathom}` — **no `drive` row** — yet Drive shows connected.

**Not the cause (ruled out):** the Gmail authorize correctly **pins** to Gmail scopes (`GmailProvider.oauth_handler` passes `connector_cls`, `core/integrations/oauth.py` `default_scopes`). The `drive.file` seen in the callback is Google returning **previously-granted** scopes on incremental re-consent — Google behaviour + prior user consent, not an authorize bug.

**Fix direction:** compute `is_connected` from the per-connector `Connection` (`Connection.objects.filter(workspace=…, provider_slug=cls.slug, enabled=True).exists()`). The vendor token means "OAuth granted for the vendor"; the `Connection` row means "this specific connector is active." Only the connector the user actually connected should show connected. Update both `list_for_workspace` and `get_status`.

---

## 5. Documentation corrections (`CLAUDE.md` is stale)

| # | Status | Item |
|---|---|---|
| 5.1 | 🔴 | `CLAUDE.md` references an `integrations_bootstrap` management command + `DONNA_OAUTH_<SLUG>_*` env seeding. **Neither exists in code.** `ClientCredentials` rows are seeded via Django admin / DB / script. Update `CLAUDE.md` (and decide whether to actually build the command). |
| 5.2 | 🔴 | `entrypoint.sh` runs only `migrate` + `collectstatic` (no bootstrap). Document the real seeding path. |

---

## 6. Testing — next steps (connector → context → agents)

| # | Status | Item |
|---|---|---|
| 6.1 | 🔴 | **Google OAuth consent test-users**: if the consent screen is in *Testing* mode, the connecting Google account must be added under *Test users* — otherwise "Access blocked". Likely next hurdle for Gmail/Drive. |
| 6.2 | 🔴 | No connectors actually connected yet — Fathom / Gmail / Drive all "Not connected" in RDS. `ClientCredentials` seeded (§ref), redirect URLs registered. |
| 6.3 | 🟡 | Fathom **backfill-on-connect** implemented (uncommitted) — the webhook is CDC (new meetings only); a connect now also backfills history. See §6.3-detail. Blocked from a live verify by Fathom rate-limit exhaustion + deployed worker running old code. |

### §6.3-detail — Fathom: ingest all past meetings on connect

**Goal:** connecting Fathom should ingest *all existing* meetings; the webhook is CDC (only meetings recorded after connect).

**Implemented (uncommitted):**
- `connectors/fathom/tasks.py::backfill_fathom_meetings` — pages `GET /meetings` (`client.iter_meetings()`) and enqueues one `ingest_fathom_meeting` per recording. Idempotent (ingest upserts by `(workspace, provider, provider_item_id)`).
- `connectors/fathom/provider.py::on_connect` — fires the backfill via `transaction.on_commit(...)` after the connect commits (webhook registration unchanged).
- `ingest_fathom_meeting` hardened: normalises the id (`/meetings` items carry `recording_id`, webhook carries `id`/`meeting_id`; `meeting.setdefault("id", recording_id)`) and prefers an inline transcript/summary when present.

**Findings during live test (documented, need follow-up):**
1. **Fathom rate-limits the recordings API → 429.** A backfill of N meetings makes ~N transcript fetches; bursting trips the limit. Added `rate_limit="6/m"` + `autoretry_for=(httpx.HTTPStatusError,)` with backoff to `ingest_fathom_meeting`. The `/meetings` list item's `transcript` field is **null** (only the per-recording endpoint returns it), so the inline-transcript optimisation doesn't avoid the call — rate-limit + retry is the real lever.
2. **Deployed worker runs the old image** — it lacks `backfill_fathom_meetings` and the retry/rate-limit config, so the auto-on-connect path only works once this is **deployed** (or a local mirrord worker runs the new code).
3. During testing the shared Fathom app's rate window got **exhausted** by repeated runs — a clean live verify needs a cooldown.

**To verify live later:** deploy (or run a local mirrord `celery worker`), let the Fathom rate window reset, connect Fathom (or run `backfill_fathom_meetings`), watch `DeliveryPackage(provider_item_type="meeting")` climb.
| 6.4 | 🔴 | Then: build the context/cortex layer from ingested `DeliveryPackage`s → stress-test the conversational + draft agents. |
| 6.5 | 🔴 | **Web-research tool** (greenfield): add `web_search` `DonnaTool` (Tavily recommended) → register in `chat/agents/tools/factory.py` (`taint_safe=False`). For Q&A + draft augmentation. |

---

## 7. Staging dev loop — reference (working)

- **db-tunnel** (`donna-cloud-infra/scripts/db-tunnel.sh [staging|prod]`): socat proxy pods → `kubectl port-forward` → local Postgres/Redis against managed RDS/ElastiCache. Ctrl-C tears down.
- **mirrord** (`server/.mirrord.json`): `mirrord exec -f .mirrord.json -- .venv/bin/python manage.py runserver 0.0.0.0:8000`. `steal` incoming + pod `env` + `fs: local` → local code serves `donna.test.qube-digital.net` traffic (incl. OAuth callbacks) with the pod's staging env (SECRET_KEY, RDS, Redis). No ArgoCD conflict (agent-based, doesn't patch the Deployment).
  - Requires `collectstatic` locally for `/admin` (whitenoise manifest storage + `DEBUG=false`).
  - Requires `awsume cube-staging` + `aws eks update-kubeconfig --name tf-donna-staging --region eu-west-1` in the shell first.
- **OAuth app creds**: SSM `/staging/donna/oauth/{fathom,google}/{client_id,client_secret,redirect_uri}` + 1Password `Donna` vault (`Donna OAuth — Fathom/Google (staging)`). Fernet key that encrypts `ClientCredentials` in the local docker DB = `SECRET_KEY` in `server/env/.env.docker`; staging RDS rows re-encrypted under the staging `SECRET_KEY` (SSM `/staging/donna/secret`).
- **Admin**: `admin@donna.ai` (superuser) — 1Password `Donna Admin (staging)`. Rotate (§1.3).
- **Workspace** in RDS: `cube-digital` (`61c4a4ba-8d93-4776-8488-a72f56e08783`).
