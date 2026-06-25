# Plan — Deployment pipelines (Cloud GitOps + Self-host releases)

> Source of decisions: 2026-06-24/25 chat with Rares.
> Source of current Donna shape: `server/Dockerfile`, `server/docker-compose.yml`,
> `server/donna/settings.py`, `.github/workflows/` (verified 2026-06-25).
> Out of scope: contents of the private `donna-cloud-infra` repo (Terraform,
> ArgoCD manifests, Helm values for Cloud). Only modifications to THIS repo
> (`donna`) are tracked here.

---

## Context

### Why this work

Donna ships two deployment modes from one public codebase:

| Mode | Where it runs | Tenancy | Update cadence | Audience |
|---|---|---|---|---|
| **Cloud** | Donna's AWS infra | Multi-tenant (workspace_id partition) | Continuous (every green main) | SMB + mid-market |
| **Self-host** | Customer's infra (compose or K8s) | Single-tenant | Versioned releases (`v1.2.3`) | Enterprise + privacy-sensitive |

Today: single `Dockerfile`, single `docker-compose.yml` mixing dev + self-host
concerns, flat `settings.py` (422 lines, env-driven), single workflow file
(`prod.yaml`, empty placeholder). Self-host is unshippable: no Helm chart, no
public release artifact, no signed image. Cloud has no CI/CD wiring at all.

### Goal

**One codebase + one build → two deploy paths,** with image identity preserved
(Cloud runs the same image bytes self-host runs, only env differs). Deploy
Flow A (GitOps + bot bumps tag) for Cloud; tagged GitHub release + public
GHCR image + Helm chart for self-host.

### What stays vs what changes

| | Stays | Changes |
|---|---|---|
| App code | All of `server/donna/` (cortex, chat, integrations, etc.) — zero edits required | — |
| Multi-tenancy | Header-tenanted, `X-Workspace-Id` middleware | — |
| Storage backend | `DONNA_STORAGE_BACKEND` env var | Cloud sets `s3`, self-host defaults `filesystem` |
| Database | Postgres + pgvector | Cloud: RDS; self-host: bundled compose or customer's |
| Celery | Same broker/backend | Cloud: ElastiCache Redis; self-host: bundled or customer's |
| Settings | Single `donna/settings.py` | Split into `donna/settings/{base,cloud,self_host,dev}.py` |
| Dockerfile | Two-stage build | Add `DONNA_DEPLOYMENT` env arg + cosign-friendly labels |
| `deploy/entrypoint.sh` | Migrate + collectstatic + uvicorn | Add `DONNA_DEPLOYMENT`-aware init + drop `--reload` in non-dev |
| `docker-compose.yml` | Local dev | Splits: `docker-compose.dev.yml` (dev, current shape) + `deploy/self_host/docker-compose.yml` (customer-facing) |
| `.github/workflows/` | `gitleaks.yml` | Add `ci.yml` (tests) + `release.yml` (tags → GHCR + Helm + GH release) + `cloud-deploy.yml` (main → ECR + GitOps bump) |
| Secrets | scattered env vars | New `donna.core.secrets.get_secret()` resolver |
| Telemetry | none | New `donna.telemetry` (opt-in, off by default self-host) |
| License | none | New `donna.billing.license` (defer; stub now) |

### Plan shape

Five phases, sequenced so each is independently shippable.

| Phase | Scope | Effort |
|---|---|---|
| 0 | Settings split + secrets resolver + telemetry stub. Pure refactor. Zero behaviour change. | ~1d |
| 1 | Dockerfile + entrypoint hardening (multi-deployment-aware). | ~0.5d |
| 2 | Split docker-compose — keep dev compose at repo root, add customer-facing compose under `deploy/self_host/`. | ~0.5d |
| 3 | Self-host CI: `ci.yml` (tests on PR) + `release.yml` (tag → multi-arch image to GHCR + cosign sign + Helm chart + GH release). | ~1.5d |
| 4 | Cloud CI: `cloud-deploy.yml` (main → ECR + cosign sign + bot bumps GitOps repo). Donna-cloud-infra repo skeleton (separate repo, NOT in this plan — documented as a sibling artifact). | ~1.5d |
| 5 | Helm chart skeleton under `deploy/self_host/helm/` + README + license validation stub. | ~1.5d |

Total ≈ 6.5d.

---

## Phase 0 — Settings split + secrets + telemetry stubs (~1d)

**Goal:** prepare app code so both deployment modes resolve config through
named seams. No behaviour change for dev today.

### 0.1 Split `donna/settings.py` into a package

**Action:** convert `donna/settings.py` (422 lines, flat) into
`donna/settings/` package with four files. All current behaviour preserved
under `dev.py` so local docker-compose keeps working unchanged.

```
server/donna/settings/
├── __init__.py            # dispatches by DONNA_DEPLOYMENT env var
├── base.py                # everything currently in settings.py that isn't dev-only
├── dev.py                 # imports base; sets DEBUG=True; current behaviour
├── self_host.py           # imports base; production-safe defaults; license-aware
└── cloud.py               # imports base; AWS-specific (S3, Secrets Manager, Sentry)
```

**New file:** `donna/settings/__init__.py`

```python
"""Settings dispatcher.

Picks the right settings module by ``DONNA_DEPLOYMENT``:

- ``dev``       — local docker-compose / runserver (default)
- ``self_host`` — customer-deployed (compose or K8s)
- ``cloud``     — Donna's own AWS infrastructure

Any code that needs to branch on deployment reads
``django.conf.settings.DEPLOYMENT`` (set on each leaf module).
"""
from __future__ import annotations

import os


_DEPLOYMENT = os.environ.get("DONNA_DEPLOYMENT", "dev").lower()

if _DEPLOYMENT == "cloud":
    from .cloud import *           # noqa: F401, F403
elif _DEPLOYMENT == "self_host":
    from .self_host import *       # noqa: F401, F403
elif _DEPLOYMENT == "dev":
    from .dev import *             # noqa: F401, F403
else:
    raise RuntimeError(
        f"unknown DONNA_DEPLOYMENT={_DEPLOYMENT!r}; "
        f"expected one of: dev, self_host, cloud"
    )
```

**New file:** `donna/settings/base.py`

Move *everything* from current `donna/settings.py` here EXCEPT:
- `DEBUG = ...` line → moves to dev.py
- The bottom-of-file `configure_logging()` call → stays at bottom of `__init__.py`
  so deployment-specific log format wins.

Add at the top:

```python
"""Shared base settings — common to dev / self_host / cloud."""
from __future__ import annotations
# ... existing imports unchanged ...

# Deployment identity — overridden in leaf modules
DEPLOYMENT = "base"   # never used directly; leaves override
```

**New file:** `donna/settings/dev.py`

```python
"""Development settings — local docker-compose + runserver."""
from .base import *  # noqa: F401, F403

DEPLOYMENT = "dev"

DEBUG = True
TELEMETRY_ENABLED = False
LICENSE_REQUIRED = False

# Storage: filesystem default (current docker-compose behaviour)
# (no override — base.py picks DONNA_STORAGE_BACKEND env; defaults to filesystem)

# Console logging
LOG_FORMAT = "console"

# configure_logging() runs from __init__.py
```

**New file:** `donna/settings/self_host.py`

```python
"""Self-host settings — customer-deployed (compose / K8s)."""
from .base import *  # noqa: F401, F403

DEPLOYMENT = "self_host"

DEBUG = False
TELEMETRY_ENABLED = env.bool("DONNA_TELEMETRY", default=False)

# License required for paid features beyond free tier
LICENSE_REQUIRED = True
LICENSE_KEY = env.str("DONNA_LICENSE_KEY", default="")

# JSON logs in production
LOG_FORMAT = env.str("LOG_FORMAT", default="json")

# ALLOWED_HOSTS must be set by operator
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")  # raises if missing — intentional

# CSRF / security hardening defaults
SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=True)
CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=True)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
```

**New file:** `donna/settings/cloud.py`

```python
"""Cloud settings — Donna's own AWS infrastructure."""
from .base import *  # noqa: F401, F403

DEPLOYMENT = "cloud"

DEBUG = False
TELEMETRY_ENABLED = True   # always on in Cloud
LICENSE_REQUIRED = False   # auto-licensed by subscription

# Storage: S3 with KMS
STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": env.str("DONNA_S3_BUCKET"),
            "region_name": env.str("AWS_REGION", default="us-east-1"),
            "object_parameters": {"ServerSideEncryption": "aws:kms"},
        },
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# Observability
SENTRY_DSN = env.str("SENTRY_DSN")
LOG_FORMAT = "json"

# CSRF / security hardening
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31_536_000
```

**Update:** `Dockerfile` env block (line 50):

```dockerfile
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=donna.settings \
    DONNA_DEPLOYMENT=self_host  \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"
```

Self-host = container default. Cloud + dev override at runtime via env.

**Update:** `server/docker-compose.yml` (the dev one — see Phase 2 for split)
— add `DONNA_DEPLOYMENT=dev` to every `env_file:`d service for explicitness.

**Verify:**
```bash
docker compose run --rm server python -c \
  "from django.conf import settings; print(settings.DEPLOYMENT)"
# expect: dev
DONNA_DEPLOYMENT=self_host docker compose run --rm server python -c \
  "from django.conf import settings; print(settings.DEPLOYMENT)"
# expect: self_host
```

### 0.2 Secrets resolver

**New file:** `donna/core/secrets.py`

```python
"""Unified secret resolver.

Cloud: AWS Secrets Manager (cached per process for 5 min).
Self-host + dev: env vars.

Same call site regardless of deployment. Code that needs a secret calls
``get_secret('DONNA_ANTHROPIC_API_KEY')``; the resolver picks the source.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from django.conf import settings


logger = logging.getLogger(__name__)

# Process-local cache; TTL in seconds.
_CACHE: dict[str, tuple[str, float]] = {}
_TTL_SECONDS = 300


def get_secret(key: str, default: str | None = None) -> str | None:
    """Resolve a secret by environment-variable-style key."""
    if settings.DEPLOYMENT != "cloud":
        return os.environ.get(key, default)

    cached = _CACHE.get(key)
    if cached and (time.time() - cached[1]) < _TTL_SECONDS:
        return cached[0]

    value = _aws_secrets_manager_lookup(key)
    if value is None:
        return default
    _CACHE[key] = (value, time.time())
    return value


def _aws_secrets_manager_lookup(key: str) -> str | None:
    """Look up a secret by key.

    Two storage strategies (set via ``DONNA_SECRETS_LAYOUT`` env):

    - ``per_key``  — one Secrets Manager entry per key (KEY=value)
    - ``bundled``  — one entry named ``donna/<env>/all`` containing JSON
                      ``{KEY: value, ...}``. Cheaper, fewer API calls.

    Default: ``bundled``.
    """
    try:
        import boto3
    except ImportError:
        logger.warning("boto3 not installed; cannot resolve cloud secrets")
        return None

    layout = os.environ.get("DONNA_SECRETS_LAYOUT", "bundled")
    sm = boto3.client("secretsmanager")
    try:
        if layout == "bundled":
            bundle_id = os.environ.get(
                "DONNA_SECRETS_BUNDLE_ID",
                f"donna/{os.environ.get('DONNA_ENV', 'prod')}/all",
            )
            resp = sm.get_secret_value(SecretId=bundle_id)
            data = json.loads(resp["SecretString"])
            return data.get(key)
        # per_key
        resp = sm.get_secret_value(SecretId=key)
        return resp.get("SecretString")
    except Exception:  # noqa: BLE001
        logger.exception("secrets_manager_lookup_failed", extra={"key": key})
        return None


def invalidate_cache(key: str | None = None) -> None:
    """Drop the in-process cache. ``None`` clears all."""
    if key is None:
        _CACHE.clear()
    else:
        _CACHE.pop(key, None)
```

**Edit:** every site in `donna/core/integrations/` that currently calls
`env.str("DONNA_<vendor>_*")` switches to `get_secret(...)`. Examples:

```python
# was (somewhere in connectors/google/.../oauth.py):
client_id = env.str("DONNA_OAUTH_GOOGLE_CLIENT_ID", default="")

# becomes:
from donna.core.secrets import get_secret
client_id = get_secret("DONNA_OAUTH_GOOGLE_CLIENT_ID", default="")
```

Scope this Phase 0 to OAuth + Anthropic key + Nango (per
[11-nango-integration.md](11-nango-integration.md)). Other env vars
(DB URL, Redis URL, log format) stay raw `env.str(...)` — they're
deployment topology, not secrets.

### 0.3 Telemetry stub

**New file:** `donna/telemetry/__init__.py`

```python
"""Opt-in usage telemetry.

Cloud: always on.
Self-host: opt-in via DONNA_TELEMETRY=true.
Dev: off.

Emit events with ``telemetry.emit('connector_connected', {...})``. Backend
implementation lives in ``backend.py``; for now everything is a no-op so
the call-site API is stable.
"""
from __future__ import annotations

from .api import emit, configure


__all__ = ["emit", "configure"]
```

**New file:** `donna/telemetry/api.py`

```python
from __future__ import annotations

import logging
from typing import Any

from django.conf import settings


logger = logging.getLogger(__name__)


def emit(event: str, properties: dict[str, Any] | None = None) -> None:
    """No-op when telemetry disabled."""
    if not getattr(settings, "TELEMETRY_ENABLED", False):
        return
    _backend().emit(event=event, properties=properties or {})


def configure() -> None:
    """Called from apps.ready() if telemetry enabled."""
    if getattr(settings, "TELEMETRY_ENABLED", False):
        _backend().configure()


def _backend():
    from .backend import NoopBackend, PostHogBackend
    if getattr(settings, "TELEMETRY_BACKEND", "noop") == "posthog":
        return PostHogBackend()
    return NoopBackend()
```

**New file:** `donna/telemetry/backend.py`

```python
from __future__ import annotations

import logging


logger = logging.getLogger(__name__)


class NoopBackend:
    def configure(self) -> None: pass
    def emit(self, *, event: str, properties: dict) -> None:
        logger.debug("telemetry_noop", extra={"event": event, "properties": properties})


class PostHogBackend:
    """Real backend — wired when settings.TELEMETRY_BACKEND='posthog'."""
    def configure(self) -> None:
        # ... posthog.api_key = ...; future work ...
        pass

    def emit(self, *, event: str, properties: dict) -> None:
        # ... posthog.capture(...); future work ...
        pass
```

Phase 0 ships only the no-op. PostHog wiring happens later when there's an
actual telemetry strategy. The seam is in place.

### 0.4 License key stub

**New file:** `donna/billing/__init__.py` (empty)

**New file:** `donna/billing/license.py`

```python
"""Self-host license validation.

Cloud: not used (LICENSE_REQUIRED=False).
Self-host free tier: not used.
Self-host paid tier: required at boot. Public key shipped in image;
private signing key lives on Donna's signing server (separate repo, OOB).

License format: base64url(payload) + '.' + base64url(rsa_pkcs1v15_sig).
Payload JSON: {customer, tier, features: [...], expires_at, issued_at}.

Phase 5 wires this into apps.ready(). Phase 0 only ships the validator
+ stub public key path so import sites are stable.
"""
from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timezone
from typing import Any

from django.conf import settings


logger = logging.getLogger(__name__)


# Replaced by real public key in Phase 5. Empty = anything validates as free tier.
_BUNDLED_PUBLIC_KEY_PEM = ""


class LicenseError(RuntimeError):
    pass


def validate_license() -> dict[str, Any]:
    """Returns license data dict, or raises LicenseError.

    No-op shortcut when ``LICENSE_REQUIRED`` is False.
    Empty key when required → free tier (capped features, no raise).
    Non-empty key → signature + expiry verified.
    """
    if not getattr(settings, "LICENSE_REQUIRED", False):
        return {"tier": "cloud", "features": "*", "expires_at": None}

    key = (getattr(settings, "LICENSE_KEY", "") or "").strip()
    if not key:
        return _free_tier()

    try:
        payload_b64, sig_b64 = key.rsplit(".", 1)
        payload_raw = base64.urlsafe_b64decode(payload_b64 + "==")
        sig = base64.urlsafe_b64decode(sig_b64 + "==")
        data = json.loads(payload_raw)
        _verify_signature(payload_raw, sig)
        _check_not_expired(data)
        return data
    except LicenseError:
        raise
    except Exception as exc:
        raise LicenseError(f"failed to parse license key: {exc}") from exc


def _free_tier() -> dict[str, Any]:
    return {
        "tier": "free",
        "customer": "self_host",
        "features": ["core"],  # everything paid is gated behind 'pro' / 'enterprise'
        "expires_at": None,
    }


def _verify_signature(payload: bytes, sig: bytes) -> None:
    pub_pem = getattr(settings, "LICENSE_PUBLIC_KEY", _BUNDLED_PUBLIC_KEY_PEM)
    if not pub_pem:
        # No public key bundled yet — Phase 5 ships it. For now, free tier.
        return
    from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15
    from cryptography.hazmat.primitives.hashes import SHA256
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    pub = load_pem_public_key(pub_pem.encode())
    try:
        pub.verify(sig, payload, PKCS1v15(), SHA256())
    except Exception as exc:
        raise LicenseError(f"license signature invalid: {exc}") from exc


def _check_not_expired(data: dict) -> None:
    expires = data.get("expires_at")
    if not expires:
        return
    when = datetime.fromisoformat(expires.replace("Z", "+00:00"))
    if when < datetime.now(timezone.utc):
        raise LicenseError(f"license expired at {expires}")
```

Phase 0 leaves Django booting fine in free tier when `LICENSE_REQUIRED=True`
and no key set. Phase 5 wires the actual feature gates.

### 0.5 Tests

```bash
docker compose run --rm server bash -lc \
  "DONNA_DEPLOYMENT=dev       uv run python -c 'from django.conf import settings; assert settings.DEPLOYMENT == \"dev\"'"
docker compose run --rm server bash -lc \
  "DONNA_DEPLOYMENT=self_host ALLOWED_HOSTS=donna.example.com \
   uv run python -c 'from django.conf import settings; assert settings.DEPLOYMENT == \"self_host\"'"
```

Plus new unit tests under `donna/core/tests/test_secrets.py` and
`donna/billing/tests/test_license.py` covering: dev resolver returns env,
cloud resolver hits boto3 (mocked), free-tier license, expired license,
bad signature.

---

## Phase 1 — Dockerfile + entrypoint hardening (~0.5d)

**Goal:** image is deployment-aware, signable, and runs production
defaults without `--reload`.

### 1.1 Dockerfile

**Edit:** `server/Dockerfile`

```dockerfile
# Add at the bottom of the runtime stage, before USER donna:
LABEL org.opencontainers.image.source="https://github.com/donna/donna" \
      org.opencontainers.image.title="Donna Server" \
      org.opencontainers.image.licenses="BSL-1.1" \
      org.opencontainers.image.description="Multi-tenant AI chat + connector framework"

# Build-time arg propagated to runtime label so customers can inspect commit.
ARG GIT_SHA="unknown"
ENV DONNA_GIT_SHA="${GIT_SHA}"
LABEL org.opencontainers.image.revision="${GIT_SHA}"
```

CI passes `--build-arg GIT_SHA=${{ github.sha }}` so image is traceable.

### 1.2 Entrypoint refactor

**Edit:** `server/deploy/entrypoint.sh` — split dev / non-dev paths.

```bash
#!/usr/bin/env bash
# Donna server entrypoint.
#
# Behaviour by DONNA_DEPLOYMENT:
#   dev       — migrate, collectstatic, uvicorn --reload (single worker)
#   self_host — migrate, collectstatic, uvicorn --workers N (no reload)
#   cloud     — collectstatic only; migrations run by Helm pre-install hook
#               (separate Job to support zero-downtime rolling deploys)
set -euo pipefail

DEPLOYMENT="${DONNA_DEPLOYMENT:-dev}"
WORKERS="${UVICORN_WORKERS:-4}"

if [[ "$DEPLOYMENT" == "cloud" ]]; then
    # Migrations are a separate Job — see deploy/self_host/helm/templates/migrate-job.yaml
    # (also used as ArgoCD pre-sync hook in donna-cloud-infra).
    python manage.py collectstatic --noinput || true
    exec uvicorn donna.asgi:application \
        --host 0.0.0.0 --port 8000 \
        --proxy-headers \
        --workers "$WORKERS"
fi

if [[ "$DEPLOYMENT" == "self_host" ]]; then
    python manage.py migrate --noinput
    python manage.py collectstatic --noinput || true
    exec uvicorn donna.asgi:application \
        --host 0.0.0.0 --port 8000 \
        --proxy-headers \
        --workers "$WORKERS"
fi

# dev (default)
python manage.py migrate --noinput
python manage.py collectstatic --noinput || true
exec uvicorn donna.asgi:application \
    --host 0.0.0.0 --port 8000 \
    --proxy-headers \
    --reload
```

### 1.3 Healthcheck endpoint

Already exists? If not, add — both compose + Helm need it.

**New file (if absent):** `donna/status/views.py:HealthView`

```python
"""Lightweight liveness probe. No DB hit; that's readiness."""
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]
    def get(self, request):
        return Response({"status": "ok"})


class ReadinessView(APIView):
    """Hits DB + Redis briefly so K8s knows when to send traffic."""
    authentication_classes: list = []
    permission_classes = [AllowAny]
    def get(self, request):
        from django.db import connection
        from django.core.cache import cache
        connection.ensure_connection()
        cache.set("readiness", "ok", timeout=5)
        return Response({"status": "ready"})
```

Wire in `donna/status/urls.py`:
```python
path("healthz/", HealthView.as_view()),
path("readyz/", ReadinessView.as_view()),
```

Add to `donna/settings/base.py` IGNORED_PATHS so workspace middleware lets them through:
```python
IGNORED_PATHS = [
    # ... existing ...
    "/healthz/",
    "/readyz/",
]
```

---

## Phase 2 — Split docker-compose (~0.5d)

**Goal:** dev compose stays at repo root; new compose lives under
`deploy/self_host/` for customers to consume.

### 2.1 Restructure

**Move:** `server/docker-compose.yml` → `server/docker-compose.dev.yml`.

Update its top comment to clarify dev-only intent. Keep all existing bind
mounts (`./donna:/opt/donna/donna`) so hot-reload works.

**New file:** `server/deploy/self_host/docker-compose.yml`

```yaml
# Donna self-host stack.
#
# Pulls the published image from GitHub Container Registry. Drop into a
# customer machine, set .env, `docker compose up -d`.
#
# All services share one bridge network. Postgres + Redis are bundled by
# default; customers with existing infra should comment them out and set
# DATABASE_URL / REDIS_URL to point externally.
#
# Documented in deploy/self_host/README.md.

services:
  database:
    image: pgvector/pgvector:pg17
    environment:
      POSTGRES_DB:       ${DATABASE_NAME:-donna}
      POSTGRES_USER:     ${DATABASE_USERNAME:-donna}
      POSTGRES_PASSWORD: ${DATABASE_PASSWORD:?Set DATABASE_PASSWORD in .env}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DATABASE_USERNAME:-donna} -d ${DATABASE_NAME:-donna}"]
      interval: 5s
      timeout: 3s
      retries: 10
    restart: unless-stopped

  cache:
    image: redis:7-alpine
    command: ["redis-server", "--appendonly", "yes"]
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10
    restart: unless-stopped

  server:
    image: ghcr.io/donna/donna-server:${DONNA_VERSION:-latest}
    environment:
      DONNA_DEPLOYMENT: self_host
    env_file:
      - .env
    depends_on:
      database: {condition: service_healthy}
      cache:    {condition: service_healthy}
    ports:
      - "${WEB_HOST_PORT:-8000}:8000"
    volumes:
      - donna_storage:/opt/donna/var/storage
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8000/healthz/"]
      interval: 10s
      timeout: 3s
      retries: 6
    restart: unless-stopped

  worker:
    image: ghcr.io/donna/donna-server:${DONNA_VERSION:-latest}
    environment:
      DONNA_DEPLOYMENT: self_host
    env_file:
      - .env
    entrypoint: []
    command: ["celery", "-A", "donna", "worker", "--loglevel=info", "--concurrency=4"]
    depends_on:
      database: {condition: service_healthy}
      cache:    {condition: service_healthy}
      server:   {condition: service_healthy}
    volumes:
      - donna_storage:/opt/donna/var/storage
    restart: unless-stopped

  beat:
    image: ghcr.io/donna/donna-server:${DONNA_VERSION:-latest}
    environment:
      DONNA_DEPLOYMENT: self_host
    env_file:
      - .env
    entrypoint: []
    command: ["celery", "-A", "donna", "beat", "--loglevel=info", "--schedule=/tmp/celerybeat-schedule"]
    depends_on:
      database: {condition: service_healthy}
      cache:    {condition: service_healthy}
      server:   {condition: service_healthy}
    restart: unless-stopped

volumes:
  postgres_data:
  redis_data:
  donna_storage:
```

**New file:** `server/deploy/self_host/.env.example`

```
# Required
DATABASE_PASSWORD=<set me to something strong>
SECRET_KEY=<run: python -c "import secrets; print(secrets.token_urlsafe(64))">
ALLOWED_HOSTS=donna.example.com

# Anthropic — bring your own
DONNA_ANTHROPIC_API_KEY=

# OAuth apps you register with Google, Notion, etc. Configure these via
# Django admin AFTER bootstrap; this env block is optional.

# Storage (default: filesystem)
DONNA_STORAGE_BACKEND=filesystem
# If using S3 / MinIO:
# DONNA_STORAGE_BACKEND=s3
# DONNA_S3_BUCKET=donna
# DONNA_S3_ENDPOINT_URL=https://minio.example.com
# DONNA_S3_ACCESS_KEY=
# DONNA_S3_SECRET_KEY=

# Optional: license unlocks paid features (free tier works without)
# DONNA_LICENSE_KEY=

# Optional: usage telemetry to Donna's support team
DONNA_TELEMETRY=false

# Version pin (omit for latest)
DONNA_VERSION=v0.1.0

# Local-host port for the web UI
WEB_HOST_PORT=8000
```

**New file:** `server/deploy/self_host/README.md`

```markdown
# Donna self-host

## Requirements

- Docker 24+ with Compose v2
- 4 GB RAM minimum
- 10 GB free disk (more for stored documents + cortex data)
- Reverse proxy with TLS termination (nginx / Caddy / Traefik) — optional but recommended

## Install

```bash
mkdir donna && cd donna
curl -O https://raw.githubusercontent.com/donna/donna/v0.1.0/server/deploy/self_host/docker-compose.yml
curl -O https://raw.githubusercontent.com/donna/donna/v0.1.0/server/deploy/self_host/.env.example
mv .env.example .env
# edit .env — set DATABASE_PASSWORD, SECRET_KEY, ALLOWED_HOSTS, DONNA_ANTHROPIC_API_KEY
docker compose up -d
docker compose exec server python manage.py createsuperuser
docker compose exec server python manage.py integrations_bootstrap
```

Donna admin lives at `http://<host>:8000/admin/`. App lives at `/`.

## Upgrades

Bump `DONNA_VERSION` in `.env`, then `docker compose pull && docker compose up -d`.
Each release notes any required manual steps (migrations are auto).

## Backup

- `postgres_data` volume — DB
- `donna_storage` volume — bronze/silver storage (or wherever `DONNA_STORAGE_BACKEND` points)

## Helm / K8s

See `deploy/self_host/helm/` for the K8s chart.
```

### 2.2 Dev compose stays as it was

`server/docker-compose.dev.yml` keeps current shape: bind-mounts source,
runs from local `Dockerfile` build, ports forwarded for direct host access.
The Makefile (if exists) + docs reference the new filename.

**Edit:** `server/Makefile` — point `docker compose` invocations at the dev file:

```makefile
COMPOSE_FILE ?= docker-compose.dev.yml
COMPOSE = docker compose -f $(COMPOSE_FILE)
```

---

## Phase 3 — Self-host CI (~1.5d)

**Goal:** push a tag → published Docker image (multi-arch, signed) + Helm
chart + GitHub release with copy-pasteable install snippet.

### 3.1 Shared test workflow

**New file:** `.github/workflows/ci.yml`

```yaml
name: ci
on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: pgvector/pgvector:pg17
        env:
          POSTGRES_DB:       donna_test
          POSTGRES_USER:     donna
          POSTGRES_PASSWORD: donna
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U donna -d donna_test"
          --health-interval 5s --health-timeout 3s --health-retries 10
      redis:
        image: redis:7-alpine
        ports: ["6379:6379"]
        options: >-
          --health-cmd "redis-cli ping" --health-interval 5s --health-retries 10

    env:
      DATABASE_URL: postgres://donna:donna@localhost:5432/donna_test
      REDIS_URL:    redis://localhost:6379/0
      SECRET_KEY:   ci-test-key
      DONNA_DEPLOYMENT: dev

    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          version: "latest"
      - run: uv sync --frozen
        working-directory: server
      - name: Django check
        run: uv run python manage.py check
        working-directory: server
      - name: Migrations
        run: uv run python manage.py migrate --noinput
        working-directory: server
      - name: Tests
        run: uv run python -m django test donna -v 2
        working-directory: server
```

### 3.2 Release workflow

**New file:** `.github/workflows/release.yml`

```yaml
name: release
on:
  push:
    tags: ["v*.*.*"]

permissions:
  contents: write          # GitHub release
  packages: write          # GHCR push
  id-token: write          # cosign OIDC signing

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      # ── Buildx + GHCR auth ─────────────────────────────────────────────────
      - uses: docker/setup-qemu-action@v3
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      # ── Multi-arch build + push ────────────────────────────────────────────
      - id: build
        uses: docker/build-push-action@v5
        with:
          context: server
          file:    server/Dockerfile
          platforms: linux/amd64,linux/arm64
          push: true
          build-args: |
            GIT_SHA=${{ github.sha }}
          tags: |
            ghcr.io/${{ github.repository_owner }}/donna-server:${{ github.ref_name }}
            ghcr.io/${{ github.repository_owner }}/donna-server:latest

      # ── Cosign sign ────────────────────────────────────────────────────────
      - uses: sigstore/cosign-installer@v3
      - name: Sign image (keyless OIDC)
        run: |
          cosign sign --yes \
            ghcr.io/${{ github.repository_owner }}/donna-server@${{ steps.build.outputs.digest }}

      # ── Package Helm chart ─────────────────────────────────────────────────
      - uses: azure/setup-helm@v4
      - name: Render chart version
        run: |
          # Strip leading "v" — Chart.yaml.version uses bare semver.
          VERSION="${GITHUB_REF_NAME#v}"
          sed -i "s/^version:.*/version: ${VERSION}/" server/deploy/self_host/helm/Chart.yaml
          sed -i "s/^appVersion:.*/appVersion: \"${GITHUB_REF_NAME}\"/" server/deploy/self_host/helm/Chart.yaml
      - run: helm package server/deploy/self_host/helm -d ./chart-out
      - name: Push chart to GHCR
        run: |
          helm push ./chart-out/donna-*.tgz \
            oci://ghcr.io/${{ github.repository_owner }}/charts

      # ── GitHub release with bundled compose + chart ───────────────────────
      - uses: softprops/action-gh-release@v2
        with:
          generate_release_notes: true
          files: |
            server/deploy/self_host/docker-compose.yml
            server/deploy/self_host/.env.example
            chart-out/donna-*.tgz
```

### 3.3 Delete `prod.yaml` placeholder

Current `.github/workflows/prod.yaml` is empty (1 line). Delete.

### 3.4 Tag the first release

After Phase 5 ships:
```bash
git tag v0.1.0 -m "First public release"
git push origin v0.1.0
```

Workflow fires → image + chart + GH release.

---

## Phase 4 — Cloud CI: GitOps bot bumps tag (~1.5d)

**Goal:** push to `main` → image to private ECR + commit to private
`donna-cloud-infra` repo bumping `image.tag`. ArgoCD in that repo pulls and
applies.

### 4.1 Cloud deploy workflow

**New file:** `.github/workflows/cloud-deploy.yml`

```yaml
name: cloud-deploy
on:
  push:
    branches: [main]

# Skip for docs-only commits (cheap; saves CI minutes).
concurrency:
  group: cloud-deploy
  cancel-in-progress: false

permissions:
  id-token: write       # cosign + AWS OIDC
  contents: read

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      # ── AWS auth via OIDC (no long-lived secrets) ──────────────────────────
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE_ARN }}
          aws-region:     us-east-1

      - uses: aws-actions/amazon-ecr-login@v2
        id: ecr

      # ── Multi-arch build + push to ECR ─────────────────────────────────────
      - uses: docker/setup-qemu-action@v3
      - uses: docker/setup-buildx-action@v3
      - id: build
        uses: docker/build-push-action@v5
        with:
          context: server
          file:    server/Dockerfile
          platforms: linux/amd64,linux/arm64
          push: true
          build-args: |
            GIT_SHA=${{ github.sha }}
          tags: |
            ${{ steps.ecr.outputs.registry }}/donna-server:${{ github.sha }}
            ${{ steps.ecr.outputs.registry }}/donna-server:main

      - uses: sigstore/cosign-installer@v3
      - run: |
          cosign sign --yes \
            ${{ steps.ecr.outputs.registry }}/donna-server@${{ steps.build.outputs.digest }}

      # ── Bump tag in private GitOps repo ────────────────────────────────────
      - uses: actions/checkout@v4
        with:
          repository: ${{ github.repository_owner }}/donna-cloud-infra
          token:      ${{ secrets.INFRA_REPO_PAT }}
          path:       infra
      - name: Bump image tag in argocd values
        run: |
          cd infra
          yq e '.image.tag = strenv(SHA)' -i argocd/apps/donna-server/values.yaml
          yq e '.image.tag = strenv(SHA)' -i argocd/apps/donna-worker/values.yaml
          yq e '.image.tag = strenv(SHA)' -i argocd/apps/donna-beat/values.yaml
          git config user.name  "donna-bot"
          git config user.email "bot@donna.ai"
          git commit -am "bump donna to ${SHA:0:7} (from ${{ github.repository }}@${{ github.sha }})"
          git push
        env:
          SHA: ${{ github.sha }}
```

### 4.2 Required secrets / OIDC trust

In GitHub repo settings (one-time setup, documented for handoff):

```
secrets:
  AWS_DEPLOY_ROLE_ARN  — IAM role with ECR push + GH OIDC trust policy
  INFRA_REPO_PAT       — fine-grained PAT scoped to donna-cloud-infra (Contents:RW)
```

AWS-side: IAM role with trust policy allowing
`token.actions.githubusercontent.com` for this repo + main branch only.
Permissions: `ecr:GetAuthorizationToken`, `ecr:BatchCheckLayerAvailability`,
`ecr:PutImage`, `ecr:InitiateLayerUpload`, `ecr:UploadLayerPart`,
`ecr:CompleteLayerUpload` scoped to the `donna-server` repository ARN.

### 4.3 donna-cloud-infra repo (sibling artifact — separate repo)

Not part of this plan, but the SHAPE this CI commits into:

```
donna-cloud-infra/                  ← PRIVATE
├── terraform/
│   ├── aws/{eks, rds, elasticache, secrets, iam}/
│   └── modules/
├── argocd/
│   ├── apps/
│   │   ├── donna-server/values.yaml  ← image.tag bumped here
│   │   ├── donna-worker/values.yaml
│   │   └── donna-beat/values.yaml
│   └── projects/
├── helm/                           ← pinned to chart version from THIS repo's release
│   └── donna/  (symlink or pinned dep)
├── secrets/                        ← SOPS-encrypted; refs AWS Secrets Manager
└── runbooks/
```

ArgoCD watches `argocd/apps/*` paths every 3min, applies on change.

---

## Phase 5 — Helm chart + license wiring (~1.5d)

**Goal:** customers can `helm install donna oci://ghcr.io/donna/charts/donna`
on any K8s cluster. License key is real (signed).

### 5.1 Chart layout

```
server/deploy/self_host/helm/
├── Chart.yaml
├── values.yaml
├── README.md
└── templates/
    ├── _helpers.tpl
    ├── configmap.yaml
    ├── secret.yaml                   # populated from values; supports external secrets
    ├── deployment-server.yaml
    ├── deployment-worker.yaml
    ├── deployment-beat.yaml
    ├── service.yaml
    ├── ingress.yaml                  # optional; user enables via values
    ├── pvc-storage.yaml              # used when storage.backend=filesystem
    ├── job-migrate.yaml              # pre-install + pre-upgrade hook
    └── tests/
        └── healthcheck-pod.yaml      # `helm test donna`
```

**New file:** `server/deploy/self_host/helm/Chart.yaml`

```yaml
apiVersion: v2
name: donna
description: Multi-tenant AI chat + connector framework
type: application
version: 0.1.0           # bumped by release.yml
appVersion: "v0.1.0"     # bumped by release.yml
home: https://github.com/donna/donna
sources:
  - https://github.com/donna/donna
```

**New file:** `server/deploy/self_host/helm/values.yaml`

```yaml
image:
  repository: ghcr.io/donna/donna-server
  tag: ""                    # defaults to .Chart.AppVersion when empty
  pullPolicy: IfNotPresent

deployment: self_host         # always self_host for chart-installed Donna

replicaCount:
  server: 2
  worker: 2
  beat: 1                     # MUST stay 1; concurrent beats double-fire schedules

resources:
  server:  { requests: { cpu: 500m, memory: 512Mi }, limits: { cpu: 2,    memory: 2Gi } }
  worker:  { requests: { cpu: 500m, memory: 512Mi }, limits: { cpu: 2,    memory: 2Gi } }
  beat:    { requests: { cpu: 100m, memory: 128Mi }, limits: { cpu: 500m, memory: 512Mi } }

# ── App config ──────────────────────────────────────────────────────────────
config:
  allowedHosts: []           # required
  storageBackend: filesystem # filesystem | s3 | gcs | azure
  telemetry: false
  logFormat: json

# ── Secrets (chart-managed OR external) ─────────────────────────────────────
secrets:
  create: true               # chart creates the Secret object
  externalSecretName: ""     # if set, chart skips creation and references this
  values:                    # only used when create=true
    secretKey: ""
    databasePassword: ""
    anthropicApiKey: ""
    licenseKey: ""

# ── Database ────────────────────────────────────────────────────────────────
postgres:
  embedded: true             # bundle a Postgres StatefulSet; turn off for external
  external:
    url: ""                  # postgres://user:pass@host:5432/db when embedded=false
  embeddedImage: pgvector/pgvector:pg17
  storage: 20Gi

# ── Cache / broker ──────────────────────────────────────────────────────────
redis:
  embedded: true
  external:
    url: ""
  embeddedImage: redis:7-alpine

# ── Ingress ─────────────────────────────────────────────────────────────────
ingress:
  enabled: false
  className: nginx
  hostname: donna.example.com
  tls:
    enabled: false
    secretName: ""

# ── Storage volume (when storageBackend=filesystem) ─────────────────────────
storage:
  size: 50Gi
  storageClass: ""

# ── Migration job ───────────────────────────────────────────────────────────
migrations:
  hookWeight: "-5"           # runs before deployments roll
  backoffLimit: 2
```

**New file:** `server/deploy/self_host/helm/templates/_helpers.tpl`

```yaml
{{- define "donna.fullname" -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "donna.image" -}}
{{- $tag := default .Chart.AppVersion .Values.image.tag -}}
{{- printf "%s:%s" .Values.image.repository $tag -}}
{{- end -}}

{{- define "donna.commonEnv" -}}
- name: DONNA_DEPLOYMENT
  value: {{ .Values.deployment | quote }}
- name: ALLOWED_HOSTS
  value: {{ join "," .Values.config.allowedHosts | quote }}
- name: DONNA_STORAGE_BACKEND
  value: {{ .Values.config.storageBackend | quote }}
- name: DONNA_TELEMETRY
  value: {{ .Values.config.telemetry | quote }}
- name: LOG_FORMAT
  value: {{ .Values.config.logFormat | quote }}
- name: DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "donna.secretName" . }}
      key: DATABASE_URL
- name: REDIS_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "donna.secretName" . }}
      key: REDIS_URL
- name: SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "donna.secretName" . }}
      key: SECRET_KEY
- name: DONNA_ANTHROPIC_API_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "donna.secretName" . }}
      key: DONNA_ANTHROPIC_API_KEY
{{- if .Values.secrets.values.licenseKey }}
- name: DONNA_LICENSE_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "donna.secretName" . }}
      key: DONNA_LICENSE_KEY
{{- end }}
{{- end -}}

{{- define "donna.secretName" -}}
{{- if .Values.secrets.externalSecretName -}}
{{- .Values.secrets.externalSecretName -}}
{{- else -}}
{{- include "donna.fullname" . -}}-secrets
{{- end -}}
{{- end -}}
```

**New file:** `server/deploy/self_host/helm/templates/deployment-server.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "donna.fullname" . }}-server
spec:
  replicas: {{ .Values.replicaCount.server }}
  selector:
    matchLabels:
      app.kubernetes.io/name:      {{ include "donna.fullname" . }}
      app.kubernetes.io/component: server
  template:
    metadata:
      labels:
        app.kubernetes.io/name:      {{ include "donna.fullname" . }}
        app.kubernetes.io/component: server
    spec:
      containers:
        - name: server
          image: {{ include "donna.image" . }}
          imagePullPolicy: {{ .Values.image.pullPolicy }}
          ports:
            - containerPort: 8000
          env:
            {{- include "donna.commonEnv" . | nindent 12 }}
          livenessProbe:
            httpGet:  { path: /healthz/, port: 8000 }
            initialDelaySeconds: 30
            periodSeconds: 10
          readinessProbe:
            httpGet:  { path: /readyz/, port: 8000 }
            initialDelaySeconds: 10
            periodSeconds: 5
          resources: {{- toYaml .Values.resources.server | nindent 12 }}
          {{- if eq .Values.config.storageBackend "filesystem" }}
          volumeMounts:
            - name: storage
              mountPath: /opt/donna/var/storage
          {{- end }}
      {{- if eq .Values.config.storageBackend "filesystem" }}
      volumes:
        - name: storage
          persistentVolumeClaim:
            claimName: {{ include "donna.fullname" . }}-storage
      {{- end }}
```

**New file:** `server/deploy/self_host/helm/templates/deployment-worker.yaml` — mirrors server, but:
```yaml
command: ["celery", "-A", "donna", "worker", "--loglevel=info", "--concurrency=4"]
```
(no probes — no HTTP port; replace with `livenessProbe.exec` running
`celery -A donna inspect ping`).

**New file:** `server/deploy/self_host/helm/templates/deployment-beat.yaml` — mirrors server, but:
```yaml
replicas: 1
command: ["celery", "-A", "donna", "beat", "--loglevel=info", "--schedule=/tmp/celerybeat-schedule"]
```
Pod has no probes; beat doesn't serve anything.

**New file:** `server/deploy/self_host/helm/templates/job-migrate.yaml`

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ include "donna.fullname" . }}-migrate-{{ .Release.Revision }}
  annotations:
    helm.sh/hook: pre-install,pre-upgrade
    helm.sh/hook-delete-policy: before-hook-creation,hook-succeeded
    helm.sh/hook-weight: {{ .Values.migrations.hookWeight | quote }}
spec:
  backoffLimit: {{ .Values.migrations.backoffLimit }}
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: migrate
          image: {{ include "donna.image" . }}
          command: ["python", "manage.py", "migrate", "--noinput"]
          env:
            {{- include "donna.commonEnv" . | nindent 12 }}
```

This Job runs once per `helm install` / `helm upgrade`, BEFORE the
Deployments roll. Matches the entrypoint refactor in Phase 1.2 (cloud
deployment skips migrate in the server pod).

**New file:** `server/deploy/self_host/helm/templates/secret.yaml`

```yaml
{{- if .Values.secrets.create }}
apiVersion: v1
kind: Secret
metadata:
  name: {{ include "donna.fullname" . }}-secrets
type: Opaque
stringData:
  SECRET_KEY:                {{ required "secrets.values.secretKey required" .Values.secrets.values.secretKey | quote }}
  DATABASE_URL:              {{ tpl (include "donna.databaseUrl" .) . | quote }}
  REDIS_URL:                 {{ tpl (include "donna.redisUrl"    .) . | quote }}
  DONNA_ANTHROPIC_API_KEY:   {{ .Values.secrets.values.anthropicApiKey | quote }}
  {{- if .Values.secrets.values.licenseKey }}
  DONNA_LICENSE_KEY:         {{ .Values.secrets.values.licenseKey | quote }}
  {{- end }}
{{- end }}

{{- define "donna.databaseUrl" -}}
{{- if .Values.postgres.embedded -}}
postgres://donna:{{ .Values.secrets.values.databasePassword }}@{{ include "donna.fullname" . }}-postgres:5432/donna
{{- else -}}
{{ .Values.postgres.external.url }}
{{- end -}}
{{- end -}}

{{- define "donna.redisUrl" -}}
{{- if .Values.redis.embedded -}}
redis://{{ include "donna.fullname" . }}-redis:6379/0
{{- else -}}
{{ .Values.redis.external.url }}
{{- end -}}
{{- end -}}
```

(Embedded Postgres/Redis manifests omitted from this plan for brevity —
standard StatefulSet + Service patterns; ship in Phase 5 work.)

### 5.2 Wire license check at boot

**Edit:** `donna/apps.py` (root app config — create if missing).

```python
# server/donna/apps.py
from __future__ import annotations

import logging

from django.apps import AppConfig
from django.conf import settings


logger = logging.getLogger(__name__)


class DonnaConfig(AppConfig):
    name = "donna"
    label = "donna"

    def ready(self):
        if getattr(settings, "LICENSE_REQUIRED", False):
            from donna.billing.license import LicenseError, validate_license
            try:
                settings.LICENSE_DATA = validate_license()
                logger.info(
                    "license_validated",
                    extra={
                        "tier":     settings.LICENSE_DATA.get("tier"),
                        "customer": settings.LICENSE_DATA.get("customer"),
                    },
                )
            except LicenseError as exc:
                logger.error("license_invalid", extra={"error": str(exc)})
                # Soft-fail in v0.1 — free tier kicks in. Phase 5 finalizes
                # whether bad license = boot-fail or free-tier fallback.
                settings.LICENSE_DATA = {"tier": "free", "features": ["core"]}
```

Wire into `INSTALLED_APPS` (if not already):
```python
INSTALLED_APPS = ["donna.apps.DonnaConfig", ...]
```

### 5.3 Feature gates

Phase 5 lays groundwork only. Actual paid-feature gates land per-feature.
Pattern:

```python
# anywhere a paid feature checks:
from django.conf import settings

def _has_feature(name: str) -> bool:
    data = getattr(settings, "LICENSE_DATA", {})
    features = data.get("features", [])
    return features == "*" or name in features

if not _has_feature("sso"):
    raise PermissionDenied("SSO requires a Donna Pro license")
```

---

## Critical files (summary)

### New

| File | Phase | Purpose |
|---|---|---|
| `server/donna/settings/__init__.py` | 0 | Dispatch by `DONNA_DEPLOYMENT` |
| `server/donna/settings/base.py` | 0 | Shared (everything currently in flat settings.py) |
| `server/donna/settings/dev.py` | 0 | DEBUG=True; console logs |
| `server/donna/settings/self_host.py` | 0 | Production-safe defaults; license-aware |
| `server/donna/settings/cloud.py` | 0 | S3 + Sentry + KMS + Datadog |
| `server/donna/core/secrets.py` | 0 | `get_secret()` resolver (env vs AWS Secrets Manager) |
| `server/donna/telemetry/{__init__,api,backend}.py` | 0 | Opt-in usage events; no-op default |
| `server/donna/billing/{__init__,license}.py` | 0 (stub) / 5 (real) | License key validation |
| `server/donna/apps.py` | 5 | Root AppConfig; wires license check |
| `server/donna/status/views.py:HealthView,ReadinessView` | 1 | K8s probes |
| `server/deploy/self_host/docker-compose.yml` | 2 | Customer-facing compose |
| `server/deploy/self_host/.env.example` | 2 | Required env vars documented |
| `server/deploy/self_host/README.md` | 2 | Install + upgrade + backup guide |
| `server/deploy/self_host/helm/Chart.yaml` | 5 | Helm chart metadata |
| `server/deploy/self_host/helm/values.yaml` | 5 | Operator-facing knobs |
| `server/deploy/self_host/helm/README.md` | 5 | Chart docs |
| `server/deploy/self_host/helm/templates/_helpers.tpl` | 5 | Shared template macros |
| `server/deploy/self_host/helm/templates/secret.yaml` | 5 | Chart-managed Secret (with external-secret override) |
| `server/deploy/self_host/helm/templates/configmap.yaml` | 5 | Non-secret config bundle |
| `server/deploy/self_host/helm/templates/deployment-server.yaml` | 5 | Web pod |
| `server/deploy/self_host/helm/templates/deployment-worker.yaml` | 5 | Celery worker pod |
| `server/deploy/self_host/helm/templates/deployment-beat.yaml` | 5 | Celery beat (single replica) |
| `server/deploy/self_host/helm/templates/service.yaml` | 5 | ClusterIP for server |
| `server/deploy/self_host/helm/templates/ingress.yaml` | 5 | Optional ingress |
| `server/deploy/self_host/helm/templates/pvc-storage.yaml` | 5 | When storageBackend=filesystem |
| `server/deploy/self_host/helm/templates/job-migrate.yaml` | 5 | Pre-install / pre-upgrade hook |
| `server/deploy/self_host/helm/templates/tests/healthcheck-pod.yaml` | 5 | `helm test donna` |
| `.github/workflows/ci.yml` | 3 | PR + main tests |
| `.github/workflows/release.yml` | 3 | Tag → GHCR + cosign + Helm + GH release |
| `.github/workflows/cloud-deploy.yml` | 4 | Main → ECR + cosign + GitOps bot |

### Edited

| File | Phase | Change |
|---|---|---|
| `server/donna/settings.py` (deleted; replaced by `settings/` package) | 0 | Convert to package |
| `server/donna/core/integrations/connectors/*/oauth.py` etc | 0 | Replace `env.str()` with `get_secret()` for secrets only |
| `server/donna/status/urls.py` | 1 | Add `/healthz/` + `/readyz/` routes |
| `server/donna/settings/base.py` | 1 | Add `IGNORED_PATHS` entries for healthz / readyz |
| `server/Dockerfile` | 1 | Add `DONNA_DEPLOYMENT=self_host` default; add OCI labels + `GIT_SHA` arg |
| `server/deploy/entrypoint.sh` | 1 | Branch by `DONNA_DEPLOYMENT`; drop `--reload` outside dev |
| `server/docker-compose.yml` → `server/docker-compose.dev.yml` | 2 | Rename; add `DONNA_DEPLOYMENT=dev` envs |
| `server/Makefile` | 2 | Point at `docker-compose.dev.yml` |
| `.github/workflows/prod.yaml` | 3 | DELETE (placeholder) |
| `server/donna/__init__.py` (or wherever current AppConfig lives) | 5 | Register `DonnaConfig` |

### Reused (no edit)

- All existing app code (`cortex/`, `chat/`, `integrations/`, etc.)
- Existing celery wiring (`donna/celery.py`)
- Existing migrations
- Existing connector framework

---

## Migration

No DB migrations.

One destructive file move:
- `server/donna/settings.py` → `server/donna/settings/__init__.py` (+ four
  sibling files). Git history preserved via `git mv`.

No data migration. Customers running the dev compose (today's
`docker-compose.yml`) follow Phase 2 rename — `docker-compose.dev.yml` is
the new local file.

---

## Verification

### Phase 0
```bash
# settings package boots in each mode
DONNA_DEPLOYMENT=dev       uv run python -c 'from django.conf import settings; print(settings.DEPLOYMENT)'
DONNA_DEPLOYMENT=self_host ALLOWED_HOSTS=donna.example.com uv run python -c '...'
DONNA_DEPLOYMENT=cloud     ALLOWED_HOSTS=donna.example.com DONNA_S3_BUCKET=x SENTRY_DSN=https://x@y/z uv run python -c '...'

# secrets resolver
docker exec donna-server bash -lc "cd /opt/donna && \
  uv run python -m django test donna.core.tests.test_secrets donna.billing.tests.test_license -v 2"
```

### Phase 1
```bash
# dev compose still works
docker compose -f docker-compose.dev.yml up --build -d
curl -fsS http://localhost:8190/healthz/  # → {"status": "ok"}
curl -fsS http://localhost:8190/readyz/   # → {"status": "ready"}
```

### Phase 2
```bash
# self-host compose pulls public image (run on a CLEAN machine)
cd /tmp && mkdir donna && cd donna
cp $REPO/server/deploy/self_host/docker-compose.yml .
cp $REPO/server/deploy/self_host/.env.example .env
# edit .env per instructions
docker compose up -d
docker compose exec server python manage.py createsuperuser
curl -fsS http://localhost:8000/healthz/
```

### Phase 3
```bash
# Tag a pre-release locally; verify workflow against a fork first
git tag v0.0.1-rc1 -m "rc1"
git push origin v0.0.1-rc1
gh run watch
# expect: GHCR image visible at ghcr.io/<owner>/donna-server:v0.0.1-rc1
# expect: chart visible via `helm pull oci://ghcr.io/<owner>/charts/donna --version 0.0.1-rc1`
# expect: GH release page with compose.yml + .env.example attached
```

### Phase 4
```bash
# Push a no-op commit; watch cloud-deploy.yml run
git commit --allow-empty -m "ci: smoke"
git push origin main
gh run watch
# expect: ECR image pushed
# expect: donna-cloud-infra repo has a new commit "bump donna to <sha>"
# expect: ArgoCD applies it (verify in ArgoCD UI of cloud cluster)
```

### Phase 5
```bash
# Lint chart
helm lint server/deploy/self_host/helm

# Install into kind cluster
kind create cluster --name donna-test
helm install donna server/deploy/self_host/helm \
  --set secrets.values.secretKey=$(openssl rand -base64 48) \
  --set secrets.values.databasePassword=donna \
  --set secrets.values.anthropicApiKey=sk-ant-... \
  --set config.allowedHosts={donna.test}
helm test donna
kubectl get pods,svc
kubectl port-forward svc/donna-donna-server 8000:80
curl -fsS http://localhost:8000/healthz/
```

---

## Cleanup discipline

Standard for this repo:
```bash
bash server/scripts/cleanup_test_residue.sh
```

After kind tests: `kind delete cluster --name donna-test`.

---

## Open questions

1. **Where does `donna-cloud-infra` live?** Separate private GitHub repo under
   the same org, or under a private GitHub org? Recommend separate private repo
   in same `donna` org (simpler PAT scoping, single org for billing).

2. **Image registry for Cloud — ECR vs GHCR (private)?** ECR if Cloud is on
   AWS (lower egress, IAM-native auth). GHCR private if multi-cloud later.
   Recommend ECR while Cloud is AWS-only.

3. **Cosign keyless vs key-based?** Keyless (OIDC) easier; key-based gives
   stronger long-term provenance. Recommend keyless for v0.1; revisit
   when first regulated customer asks.

4. **Free tier feature set.** When `LICENSE_KEY` empty + `LICENSE_REQUIRED=True`,
   what's gated? Recommend `core` only (Q&A + drafting); Nango integration,
   SSO, audit logs all require Pro. Document in `LICENSE.md`.

5. **Telemetry payload schema.** What events do we emit, what's PII-safe?
   Recommend draft 5-10 events for v0.1 (workspace_created, connector_connected,
   agent_turn_completed) with workspace_id hashed, no message content.

6. **Helm chart hosting alternatives.** OCI registries (GHCR) work but
   Helm tooling still treats them as second-class. Consider hosting a
   classic Helm repo via `gh-pages` branch as fallback? Defer — OCI is the
   2025 standard.

7. **Embedded Postgres in Helm chart — keep or drop?** Embedding makes
   `helm install` work on bare clusters, but production customers should
   use managed Postgres. Recommend keep with prominent warning in chart README.

8. **Versioning policy.** Semver, but what's the cadence + breaking-change
   policy? Recommend: minor every 4 weeks, patch as needed, major when
   migrations require downtime.

---
