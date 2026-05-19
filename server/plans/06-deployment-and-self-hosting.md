# Deployment and self-hosting

How Donna ships. Two deployment modes from one codebase: **Donna Cloud** (we run it) and **Donna On-Premise** (customer runs it). Designed so the only difference is data ownership and OAuth app ownership — no code branches.

## Why this matters now

[05-integration-architecture.md](05-integration-architecture.md) commits to the n8n deployment model (ship-all, opt-out, BYO OAuth). That decision has implications well beyond integrations: storage backend choice, worker model, queue choice, license, container topology. This doc captures those upstream decisions so they don't accumulate as AWS-coupling debt or commercial-license regrets later.

## Two deployment targets, one artifact

| | Donna Cloud | Donna On-Premise |
|---|---|---|
| **Operator** | Donna team | Customer's sysadmin |
| **Hosting** | AWS (or whichever cloud) | Customer's infrastructure (VPS, k8s, bare metal) |
| **Image** | Same Docker image | Same Docker image |
| **Database** | Managed Postgres (RDS, Cloud SQL) | Postgres container or managed |
| **Cache/queue** | Managed Redis (ElastiCache) | Redis container |
| **Object storage** | AWS S3 (or GCS, R2) | S3-compatible (SeaweedFS / Garage / R2 / Ceph) |
| **Worker fleet** | ECS / Cloud Run / k8s | Docker compose or k8s |
| **OAuth apps** | Donna-owned (one per provider) | Customer-owned (one per provider, per deployment) |
| **TLS / domain** | `*.donna.cloud` | Customer's domain (`donna.acme.internal`) |
| **Updates** | Continuous deploy | Customer-driven (versioned releases) |

The architectural rule: **nothing in the code branches on deployment mode.** All variation is data (which OAuth apps exist, which S3 endpoint, which queue host) and configuration (env vars).

## The "no AWS-only" rule

Every dependency must work on a customer's VPS, on bare metal, on Hetzner, on a homelab. This rules out:

- AWS Lambda (runs only on AWS)
- AWS SQS (Redis or Postgres-backed queues work everywhere)
- AWS DynamoDB (Postgres works everywhere)
- AWS-specific managed services with no OSS equivalent (DocumentDB, ECS-only patterns)

If we want a fancy AWS feature in Cloud (e.g., S3 Intelligent-Tiering), we use it *through* the same interface — the on-prem path just doesn't get the optimization. **Never use an AWS-only service in the data path.**

## Storage: pluggable, env-var-driven, code-agnostic

Provider Celery tasks call Django's `default_storage` directly (configured via `STORAGES["default"]`). Customers pick the actual backend via env vars at deploy time. No `BronzeStorage` facade in v1 — the storage write is two lines of Django (`default_storage.save(key, ContentFile(...))`).

### Usage in a provider task

```python
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
import json

# Inside providers/fathom/tasks.py::ingest_fathom_meeting
storage_key = f"{workspace_id}/fathom/meetings/{meeting_id}.json"
default_storage.save(
    storage_key,
    ContentFile(json.dumps(adapter.to_json()).encode()),
)
# storage_key is then persisted on the DeliveryPackage row
```

Key convention: `{workspace_id}/{provider}/{kind}/{item_id}.json` — workspace-prefixed for compliance + lifecycle policies.

**When to introduce a `BronzeStorage` facade**: when (a) 2+ providers duplicate the `default_storage.save(...)` boilerplate above, or (b) bronze-specific features are needed (presigned URLs, lifecycle policies, replay across providers). For Fathom-only v1, direct `default_storage` is enough.

**When to introduce a dedicated `STORAGES["integrations"]` named backend**: when integration data and Django uploads (avatars, attachments) need to live in separate buckets / paths / lifecycle policies. Defer until integration #2.

### Settings — one env var picks the backend

Using Django 4.2+ `STORAGES` dict (multiple named backends, properly supported):

```python
# donna/settings.py

def _default_storage_config():
    backend = env("DONNA_STORAGE_BACKEND", default="s3")

    if backend == "s3":
        return {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "bucket_name":      env("DONNA_S3_BUCKET"),
                "endpoint_url":     env("DONNA_S3_ENDPOINT_URL", default=None),
                "access_key":       env("DONNA_S3_ACCESS_KEY"),
                "secret_key":       env("DONNA_S3_SECRET_KEY"),
                "region_name":      env("DONNA_S3_REGION", default="us-east-1"),
                "addressing_style": env("DONNA_S3_ADDRESSING_STYLE", default="virtual"),
                "use_ssl":          env.bool("DONNA_S3_USE_SSL", default=True),
                "verify":           env.bool("DONNA_S3_VERIFY_SSL", default=True),
            },
        }

    if backend == "filesystem":
        return {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {
                "location": env("DONNA_FILESYSTEM_ROOT", default="/var/lib/donna/storage"),
                "base_url": env("DONNA_FILESYSTEM_BASE_URL", default=None),
            },
        }

    if backend == "gcs":
        return {
            "BACKEND": "storages.backends.gcloud.GoogleCloudStorage",
            "OPTIONS": {
                "bucket_name": env("DONNA_GCS_BUCKET"),
                "credentials": env("DONNA_GCS_CREDENTIALS_PATH"),
            },
        }

    if backend == "azure":
        return {
            "BACKEND": "storages.backends.azure_storage.AzureStorage",
            "OPTIONS": {
                "account_name":    env("DONNA_AZURE_ACCOUNT"),
                "account_key":     env("DONNA_AZURE_KEY"),
                "azure_container": env("DONNA_AZURE_CONTAINER"),
            },
        }

    raise ImproperlyConfigured(f"Unknown DONNA_STORAGE_BACKEND: {backend}")


STORAGES = {
    "default":     _default_storage_config(),
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
```

### Supported backends (env-var matrix)

| Target | `DONNA_STORAGE_BACKEND` | Required env vars |
|---|---|---|
| **AWS S3** | `s3` | `DONNA_S3_BUCKET`, `DONNA_S3_REGION`, `DONNA_S3_ACCESS_KEY`, `DONNA_S3_SECRET_KEY` |
| **MinIO / SeaweedFS / Ceph (self-host)** | `s3` | + `DONNA_S3_ENDPOINT_URL`, `DONNA_S3_ADDRESSING_STYLE=path` |
| **Cloudflare R2** | `s3` | + `DONNA_S3_ENDPOINT_URL=https://<acct>.r2.cloudflarestorage.com`, `DONNA_S3_REGION=auto` |
| **Backblaze B2** | `s3` | + `DONNA_S3_ENDPOINT_URL=https://s3.<region>.backblazeb2.com` |
| **Wasabi** | `s3` | + `DONNA_S3_ENDPOINT_URL=https://s3.<region>.wasabisys.com` |
| **Hetzner Object Storage** | `s3` | + `DONNA_S3_ENDPOINT_URL=https://<region>.your-objectstorage.com` |
| **Garage (small self-host)** | `s3` | + `DONNA_S3_ENDPOINT_URL=https://garage.acme.internal:3900` |
| **Local filesystem** | `filesystem` | `DONNA_FILESYSTEM_ROOT` |
| **Google Cloud Storage (native)** | `gcs` | `DONNA_GCS_BUCKET`, `DONNA_GCS_CREDENTIALS_PATH` (service account JSON path) |
| **Azure Blob Storage** | `azure` | `DONNA_AZURE_ACCOUNT`, `DONNA_AZURE_KEY`, `DONNA_AZURE_CONTAINER` |

Any S3-compatible service that isn't in the table works the same way — `DONNA_STORAGE_BACKEND=s3` + an `DONNA_S3_ENDPOINT_URL` pointing at it. The customer doesn't need Donna code changes to bring up a new provider.

### Recommended backends by deployment shape

| Deployment | Recommendation |
|---|---|
| Donna Cloud (AWS-hosted) | Real AWS S3 (no endpoint override) |
| Donna Cloud (other clouds, future) | Native GCS / Azure Blob / R2 |
| On-prem production (large) | **SeaweedFS** (mature, fast, billions of files) or Ceph RGW (if already running Ceph) |
| On-prem production (small) | **Garage** (lightweight, S3-compatible, Rust) |
| Homelab / single-server | **`filesystem`** backend pointed at a local directory |
| Dev environment | SeaweedFS in docker-compose |

### Why not MinIO?

MinIO went fully commercial in 2025 (pulled features into paid tier, restrictive license trajectory). It still works for existing deployments but is no longer the default OSS recommendation. **For new deployments, recommend SeaweedFS** (mature, fast, strong default) with Garage as a lightweight alternative for small installs. Ceph only if the customer already runs Ceph.

### Bronze path conventions

```
{workspace_id}/{provider}/{yyyy}/{mm}/{dd}/{provider_item_id}.json
```

Workspace-prefixed so:
- Lifecycle policies can be applied per-workspace (e.g., compliance-driven retention)
- A workspace can be deleted by purging a single prefix
- Multi-tenant isolation is visible in the storage layout, not just at the application layer

### Verifying configuration: `storage_test` command

A management command sanity-checks the backend before real ingestion runs:

```bash
python manage.py storage_test
```

Writes + reads a small JSON file via `default_storage`. Reports the backend class, the key written, and the read-back payload. If misconfigured, the customer sees it before any connector touches storage.

### Per-workspace storage override (deferred to v2+)

For enterprise customers with data residency requirements ("our EU workspace's data must live in EU"), a per-workspace override allows pointing one workspace at its own bucket/credentials:

```
WorkspaceStorageConfig (one-to-one Workspace)
├── backend           (s3 | filesystem | gcs | azure)
├── bucket_name, endpoint_url, region_name, access_key, secret_key  (S3-compat)
├── filesystem_root                                                  (FS)
└── metadata                                                         (backend-specific)
```

Provider tasks check for an override per workspace before falling back to the global `default_storage`. Triggered when a real enterprise customer asks — see [02-data-model.md](02-data-model.md) open list.

## Compute: plain workers, never serverless

Workers are **long-running processes** in containers. No Lambda, no Cloud Run-per-request, no serverless. Reasoning:

- Self-host story dies the moment AWS Lambda is in the path
- 15-minute Lambda limit doesn't fit long backfills
- Cold starts make webhook latency unpredictable
- Local dev requires LocalStack/sst — extra friction

Concrete shape:

```yaml
# docker-compose.yml (excerpt)
services:
  web:
    image: donna/api:v1.0
    command: gunicorn donna.wsgi
    ports: ["8000:8000"]

  worker:
    image: donna/api:v1.0           # SAME image
    command: celery -A donna worker --concurrency=4
    deploy:
      replicas: 2

  scheduler:
    image: donna/api:v1.0           # SAME image
    command: celery -A donna beat

  redis: { image: redis:7 }
  postgres: { image: postgres:16 }
  seaweedfs: { image: chrislusf/seaweedfs }
```

One image, different start commands. Scale workers by replicas.

### Workflow engine choice — Celery for v1

Three candidates were considered for the integration pipeline workflow engine:

| | Celery | Django-Q | Inngest |
|---|---|---|---|
| Maturity | Highest | Medium | Newer |
| Self-host story | Excellent | Excellent (Postgres-backed) | Cloud-first; self-host exists but heavier |
| Required infra | Redis + worker process | Postgres only | Inngest server + worker (or cloud) |
| Observability | Manual (Flower) | Built-in admin | Best-in-class |
| Donna fit | ✅ universal | ✅ simpler ops | ❌ adds infra |

**Choice: Celery + Redis.** Universal Django shop default, self-host friendly, swap to Inngest later if observability becomes the bottleneck (~integration #10). Django-Q was tempting for the "Postgres-only" story but has weaker fanout patterns at scale.

`tasks.py` is abstracted so the swap is a `tasks.py` rewrite, not a provider rewrite.

## Database: Postgres always

One choice, universal:

- Donna Cloud: managed Postgres (RDS / Cloud SQL).
- On-prem: Postgres container or managed.
- Dev: Postgres container (or SQLite for the absolute smallest dev setup, but most ops should use Postgres for parity).

No special database features that won't migrate (avoid CockroachDB-only SQL, avoid pgvector-only features unless we commit to it explicitly).

## Cache and queue: Redis

Used for:
- Celery broker (job queue)
- Per-provider rate limit token buckets (long-term; v1 may use Postgres)
- Session cache if we go session-auth (TBD per [04-roadmap.md](04-roadmap.md))

Self-host equivalent: Redis container or Valkey (OSS fork after the Redis license change).

## OAuth apps: BYO for on-prem

Per [05-integration-architecture.md#deployment-model](05-integration-architecture.md#deployment-model), the on-prem sysadmin must register their own OAuth app with each provider they enable. This is unavoidable — every integration platform (n8n, Activepieces, Nango, Airbyte) requires it because the redirect URI must point at the customer's deployment, not at Donna Cloud.

### The on-prem onboarding flow (per Tier 1 vendor)

**One setup guide per vendor, not per product**, because OAuth apps are registered at vendor level (Google Console issues one OAuth app that covers Gmail + Drive + Calendar with combined scopes; same for Microsoft, Atlassian).

- Single-product vendor → one guide per integration: `docs/self-hosting/integrations/fathom.md`, `docs/self-hosting/integrations/slack.md`, `docs/self-hosting/integrations/linear.md`.
- Multi-product vendor → one guide per vendor: `docs/self-hosting/integrations/google.md` (covers Gmail + Drive + future Calendar), `docs/self-hosting/integrations/microsoft.md` (Outlook + Teams + OneDrive), `docs/self-hosting/integrations/atlassian.md` (Jira + Confluence).

This matches the upstream reality: sysadmin clicks "Create OAuth App" once per vendor in their developer console, not once per service.

Template:

```markdown
# Setting up {Provider} for your Donna deployment

## 1. Register an OAuth app

1. Sign in to {Provider}'s developer console at {URL}.
2. Create a new OAuth application.
3. Set:
   - **Application name**: "Donna ({your-company})"
   - **Redirect URI**: `https://{your-donna-host}/oauth/callback/{slug}`
   - **Scopes required**: {list}
4. Save and copy the **Client ID** and **Client Secret**.

## 2. Configure in Donna

1. Sign in to Donna admin at `https://{your-donna-host}/admin/`.
2. Navigate to **Authentication → OAuth Providers → {Provider}**.
3. Fill in:
   - Client ID
   - Client Secret
   - Redirect URI (same as step 1)
4. Check **Is enabled**.
5. Save.

## 3. (Webhooks only) Configure the webhook

1. In {Provider}'s console, navigate to webhooks.
2. Add a webhook with URL: `https://{your-donna-host}/api/v1/integrations/{slug}/webhook/callback`
3. Copy the **signing secret** {Provider} generates.
4. Back in Donna admin, paste it into the **Webhook secret** field on the same provider row.

## 4. Users connect

Workspace members can now navigate to **Settings → Integrations** in Donna and click **Connect** on any of the products covered by this OAuth app (e.g., Gmail and Drive for Google). One OAuth dance unlocks all of them.
```

~10 minutes of admin work per Tier 1 *vendor* (covers all that vendor's products). Industry-standard.

**Example — Google guide concretely:** the setup doc registers one OAuth app in Google Cloud Console with the union of Gmail + Drive scopes. Sysadmin configures the single `OAuthProvider("google")` row in Donna admin. Users see both "Gmail" and "Drive" cards in their integrations list; either "Connect" button triggers the same OAuth flow, which authorizes both products at once.

### What Donna Cloud customers see

For Cloud customers, the OAuth apps are pre-configured by the Donna team. Customers go directly to **Settings → Integrations → {Provider} → Connect**. No setup step.

### Cloud OAuth provisioning — env-var bootstrap pattern

Both Cloud and on-prem use the **same code path**: at request time, the OAuth flow reads `client_id`/`client_secret` from the `OAuthProvider` DB row (with `EncryptedCharField` for the secret). The only difference is *how the row gets populated*:

| | Donna Cloud | Donna On-Premise |
|---|---|---|
| Source of credentials | AWS Secrets Manager / Vault → env vars | Customer enters via Django admin |
| When populated | At container start (bootstrap reads env, writes row) | Manually after deploy |
| `is_enabled` initial state | `True` (filled by bootstrap) | `False` (customer flips after entering credentials) |
| Encryption key | Backed by KMS, supplied as env var | Local env var on customer's VPS |

The `integrations_bootstrap` management command checks for env vars per provider and seeds the row when they're present:

```python
client_id     = env(f"DONNA_OAUTH_{slug.upper()}_CLIENT_ID",     default=None)
client_secret = env(f"DONNA_OAUTH_{slug.upper()}_CLIENT_SECRET", default=None)
redirect_uri  = env(f"DONNA_OAUTH_{slug.upper()}_REDIRECT_URI",  default=None)

if client_id and client_secret and redirect_uri:
    # Cloud path — credentials present, enable immediately
    OAuthProvider.objects.update_or_create(slug=slug, defaults={
        "client_id":     client_id,
        "client_secret": client_secret,        # EncryptedCharField encrypts at write
        "redirect_uri":  redirect_uri,
        "is_enabled":    True,
        "default_scopes": ...,
        "authorize_url": ...,
        "token_url":     ...,
    })
else:
    # On-prem path — leave row stub with is_enabled=False, admin fills it
    OAuthProvider.objects.update_or_create(slug=slug, defaults={
        "is_enabled":    False,
        "default_scopes": ...,
        "authorize_url": ...,
        "token_url":     ...,
    })
```

The **DB row is always the source of truth at request time** — runtime code never reads OAuth secrets from env vars directly. Env vars are only consumed once, at bootstrap, to seed the row.

This keeps:
- One code path (no `if cloud else on_prem` branches in OAuth flow code)
- Operational sovereignty (Cloud uses secrets-manager-backed env vars; on-prem uses admin UI)
- `is_enabled` toggle works in both modes (you can disable a provider in prod without removing env vars)

## Image, distribution, and updates

### One Docker image

Built and tagged per release:

```
donna/donna:v1.2.0
donna/donna:latest
donna/donna:v1
donna/donna:v1.2
```

Contains: API server, worker, scheduler — selected at runtime via the start command.

### Deployment artifacts

| Artifact | Use case |
|---|---|
| `docker-compose.yml` | Dev environments, small self-hosters |
| Helm chart (`charts/donna/`) | Production self-host on Kubernetes |
| Terraform module (optional, future) | Cloud-hosted self-host (AWS/GCP) |

**Helm chart from day one** even if it's minimal — building it later means refactoring config defaults. Treat self-host as a first-class deployment target.

### Updates

- Donna Cloud: continuous deploy from `main` after CI.
- Donna On-Prem: customer pulls a versioned image. Migration runs automatically via Helm hook / docker-compose entrypoint.

### Migrations and integration bootstrap

On container start (web service), an entrypoint runs:

```bash
python manage.py migrate --noinput
python manage.py integrations_bootstrap   # see 05
python manage.py runserver / gunicorn ...
```

Worker containers skip migrate (only web runs it to avoid races). `integrations_bootstrap` is idempotent.

## License

**Decision: Elastic License v2 (recommended).** Rationale:

- Allows self-host (the on-prem story we're committed to).
- Blocks competing managed services ("Donna-as-a-Service" by a third party).
- Industry-standard for OSS-with-commercial — Airbyte, Nango, Elastic itself use it.
- BSL (Business Source License — Sentry, HashiCorp) is an alternative with similar properties; differs in that BSL converts to OSS after N years, while ELv2 doesn't.

**Rejected:**
- **MIT / Apache 2.0** — too permissive. Any cloud provider could launch "Donna Cloud" tomorrow as a managed service and undercut us.
- **n8n's Sustainable Use License** — non-OSI-approved fair-code. More restrictive than ELv2 and confuses contributors.
- **SSPL (MongoDB-style)** — heavier license, has scared off some users/contributors.
- **Closed-source / source-available without modification** — kills the OSS community story.

**Decision deferred to first public release.** No license commitment until the repo goes public. Until then, the codebase is private. Reconfirm with legal before tagging v1.0.

## Open questions

- **Helm chart maturity at v1.** Minimal chart (deployment + statefulset for Postgres + Redis + storage) is enough for the first on-prem customer; production-hardening (HPA, ingress, secrets management via Vault, network policies) is a phase of its own.
- **OAuth client_secret storage for Donna Cloud.** Even though *we* configure them, they're still sensitive. `EncryptedCharField` on the `OAuthProvider` row protects against DB dump leakage. Per-environment KMS key (AWS KMS in Cloud, local key on on-prem) is the natural next step.
- **Multi-tenancy of Donna Cloud.** Is "Donna Cloud" one Postgres database with many workspaces, or one database per customer? The header-based tenancy already supports the single-db model; per-customer DB is a v3+ concern for enterprise.
- **Domain / subdomain model for Cloud.** `app.donna.cloud` for everyone vs `{slug}.donna.cloud` per workspace. Affects cookies, CORS, OAuth redirect URIs.
- **Per-environment encryption keys.** `EncryptedCharField` reads from a settings-derived key today; for Cloud we want KMS-backed, for on-prem we need a customer-managed key (env var or Vault).
- **Backups for on-prem.** Currently none of our concern; document recommended pg_dump + S3 sync cadence in the operator guide once a real customer asks.
- **Observability stack for on-prem.** Sentry-on-prem? Self-hosted Grafana + Loki + Prometheus? Customers will want metrics + logs + traces; we provide hooks (structlog already emits JSON) and recommend a stack, but don't bundle it.
- **Air-gapped on-prem.** Some enterprise customers can't reach `pypi.org` or Docker Hub. Document a fully-air-gapped install path (private registry + offline pip mirror) when that customer arrives.
