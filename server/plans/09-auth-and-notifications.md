# Authentication + Notifications — narrio cherry-pick (shipped)

> Status: **shipped** (model code lands, migrations deferred per session
> policy). Reference module: `/Users/ristoc/Workspaces/narrio/narrio/narrio/`.

## Context

`donna/authentication/` carried integration-OAuth models
(`OAuthProvider`, `OAuthToken`) but no user login flow. `donna/notifications/`
was a hollow stub. We populated both modules by cherry-picking from
narrio's production code, keeping only what fits Donna v1.

Two new capabilities landed:

1. **User authentication** — email/password signup + signin, password
   reset (3-step), email verification, Google login as a second sign-in
   path. JWT-based via `rest_framework_simplejwt`.
2. **In-app notifications** — persistent DB feed + **SSE realtime push**
   (per-user channel only at this stage — workspace fan-in lands in
   [10-realtime-layer.md](10-realtime-layer.md)).

## Locked decisions

| Choice | Decision |
|---|---|
| JWT library | `rest_framework_simplejwt` (already in `DEFAULT_AUTHENTICATION_CLASSES`) |
| Signup payload shape | `{email, password, full_name}` (Donna's User has `full_name`, not first/last) |
| Email verification gate | Soft — user can sign in but `User.email_verified=False`; frontend nags. Hard gating deferred until real abuse appears |
| Google login token storage | Do NOT persist Google's refresh token at login — only identity. (Future: add separate `LoginOAuthToken` if continuous API access needed) |
| Google login redirect | `WEB_REDIRECT_HOST/login/callback?refresh_token=…&redirect_uri=…` (narrio shape) |
| Email backend (v1) | Django `console` backend in dev, `smtp` in prod. Settings-driven. No Sendgrid templates |
| Notification scope (v1) | `(user, workspace)` — workspace nullable for global notifications; workspace-scope routing lands in 10 |
| SSE transport | Django async view + `StreamingHttpResponse` via uvicorn (already in deps); Redis pubsub channel `user-{id}-notifications` |
| `email_verified` field | Added to `User` model (boolean + timestamp) |

## What we took from narrio (and what we dropped)

| narrio file | Status |
|---|---|
| `authentication/models.ResetPasswordToken` | ✅ copied (`donna/authentication/models.ResetPasswordToken`) |
| `authentication/models.OAuthToken` | ❌ Donna already has its own for integrations |
| `authentication/settings.api_settings` | ✅ copied; extended for email-verify TTL/limits |
| `authentication/signals.py` | ✅ + `email_verify_request` signal |
| `authentication/receivers.py` | ➖ rewrote with Django `send_mail`, dropped Sendgrid template IDs |
| `authentication/services.AuthService` | ✅ slim — handler dispatch only; dropped HubSpot/Calendar helpers + `_handle_invitations` |
| `authentication/handlers/base.BaseOAuthHandler` | ✅ copied |
| `authentication/handlers/google_login.py` | ✅ adapted — dropped CompanyMembership + GoogleOAuthProvider import; uses `google_auth_oauthlib.flow.Flow` directly |
| `authentication/handlers/hubspot.py` | ❌ HubSpot is narrio-specific |
| `authentication/handlers/google_calendar.py` | ❌ Donna's integration Gmail/Drive cover Google API access |
| `authentication/api/v1/serializers.py` | ✅ adapted — uses `full_name`, dropped `_handle_invitations` |
| `authentication/api/v1/views.py` | ✅ subset — SignUp + Reset (×3) + Google (×2). Added new EmailVerify (×2). Skipped HubSpot + Calendar |
| `notifications/models.Notification` | ✅ swapped `team`/`company` FKs for nullable `workspace` |
| `notifications/managers.NotificationManager` | ✅ dropped `for_team`/`for_company`, added `for_workspace` |
| `notifications/services/notification.NotificationService` | ✅ copied; trimmed team/company kwargs |
| `notifications/schemas.NotificationPayload` | ✅ copied verbatim |
| `notifications/views.py` | ✅ list / mark-read / mark-all-read / SSE |

## Files landed

```
donna/users/models.py                       EXTEND  + email_verified, email_verified_at
donna/authentication/
├── settings.py                              NEW   api_settings (TTL/length/limits)
├── models.py                                EXTEND + ResetPasswordToken, EmailVerificationToken
├── signals.py                               NEW   3 signals
├── receivers.py                             NEW   Django send_mail receivers
├── apps.py                                  EXTEND wire receivers in ready()
├── handlers/__init__.py                     NEW
├── handlers/base.py                         NEW   BaseOAuthHandler
├── handlers/google_login.py                 NEW   GoogleLoginHandler
├── services.py                              NEW   AuthService (handler dispatch)
├── api/v1/serializers.py                    NEW   SignUp + CustomTokenObtainPair + Reset + Verify
├── api/v1/views.py                          NEW   10 endpoints
└── urls.py                                  NEW

donna/notifications/
├── models.py                                NEW   Notification + NotificationStatus
├── managers.py                              NEW   NotificationManager
├── schemas.py                               NEW   NotificationPayload
├── services.py                              NEW   NotificationService (DB + SSE)
├── api/v1/serializers.py                    NEW   NotificationSerializer, MarkReadSerializer
├── api/v1/views.py                          NEW   List + MarkRead + MarkAllRead + SSE
└── urls.py                                  NEW

donna/core/cache/
├── __init__.py                              NEW
└── redis_cache.py                           NEW   redis_manager (sync + async)

donna/settings.py                            EXTEND + SIMPLE_JWT, WEB_REDIRECT_HOST,
                                                     GOOGLE_LOGIN_*, EMAIL_*

donna/urls.py                                EXTEND + /api/auth/ + /api/v1/notifications/

donna/status/urls.py                         NEW   tiny health-check stub (pre-existing
                                                   reference was broken)

pyproject.toml                               EXTEND + jsonschema>=4.20.0
```

## Endpoints live

```
POST /api/auth/signup
POST /api/auth/signin                    (simplejwt + CustomTokenObtainPairSerializer)
POST /api/auth/token/refresh
POST /api/auth/token/blacklist
POST /api/auth/logout
POST /api/auth/password/recover
GET  /api/auth/password/validate/<token>
POST /api/auth/password/confirm
POST /api/auth/email/verify/request      (authed)
GET  /api/auth/email/verify/confirm/<token>
GET  /api/auth/google/login              → {authorization_url}
GET  /api/auth/google/callback           → 302 frontend?refresh_token=…

GET  /api/v1/notifications/
POST /api/v1/notifications/mark-read     body: {ids: [...]}
POST /api/v1/notifications/mark-all-read
GET  /api/v1/notifications/stream        SSE, async, needs uvicorn
```

## Migrations needed (deferred)

- `users/0002_email_verified.py`
- `authentication/0004_reset_password_email_verification.py`
- `notifications/0001_initial.py`

Run `makemigrations users authentication notifications && migrate` when ready.

## Out of scope

- HubSpot / Google Calendar login handlers (narrio-specific)
- Sendgrid templates — Django `send_mail` plain text only
- Email channel for notifications (in-app + SSE only v1)
- Push / Slack channels for notifications
- Per-user notification preferences
- MFA / WebAuthn / passkeys
- Account linking (Google + password on same email — v1 just get-or-creates)
- Magic-link signin

## Open gaps (deferred)

1. **Account linking** — Google login finds existing email account and
   signs in; no explicit "link account" UX. Future: `LoginIdentity`
   row per (provider, user).
2. **Email verification on Google login** — Google attests; we set
   `email_verified=True` on first login.
3. **Rate limiting** — per-user limit on password reset
   (`api_settings.RESET_PASSWORD_TOKEN_LIMIT_PER_USER=3`). No IP-level
   throttling v1.
4. **SSE backpressure** — no max connections per user. Add Redis
   counter if abuse appears.
5. **Notification cleanup** — no TTL on rows. Add periodic Celery beat
   prune task at scale.
6. **Workspace-scoped notifications** — v1 stores `workspace` nullable
   but only emits to `user-{uid}-notifications` channel. Workspace
   fan-in covered by [10-realtime-layer.md](10-realtime-layer.md).
7. **i18n on email templates** — v1 hardcoded English.

## Verification

```bash
cd server
LOG_LEVEL=INFO LOG_FORMAT=console DEBUG=true \
  DJANGO_SETTINGS_MODULE=donna.settings .venv/bin/python -m django check
# expect: System check identified no issues (0 silenced).

# E2E manual
curl -X POST localhost:8000/api/auth/signup -H 'Content-Type: application/json' \
  -d '{"email":"alice@acme.test","password":"S3curePass!","full_name":"Alice A"}'

TOKEN=$(curl -sX POST localhost:8000/api/auth/signin \
  -d '{"email":"alice@acme.test","password":"S3curePass!"}' | jq -r .access)

curl -X POST localhost:8000/api/auth/email/verify/request -H "Authorization: Bearer $TOKEN"
# console-email backend prints verify link

curl localhost:8000/api/auth/google/login
# returns {authorization_url}
```
