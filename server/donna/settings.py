"""
Django settings for donna project.

Env-driven (via django-environ). Defaults are suitable for local development;
override via environment variables for any non-dev deployment.
"""

import os
import secrets
from datetime import timedelta
from pathlib import Path

import environ


BASE_DIR = Path(__file__).resolve().parent.parent

# ─── Environment ───────────────────────────────────────────────────────────────

environ.Env.read_env(env_file=str(BASE_DIR.joinpath(".env")))
env = environ.Env()

SECRET_KEY = env.str("SECRET_KEY", default=secrets.token_urlsafe())

DEBUG = env.str("DEBUG", default="false").lower() == "true"
TESTING = env.str("TESTING", default="false").lower() == "true"
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["*"])

# ─── Apps ──────────────────────────────────────────────────────────────────────

INSTALLED_APPS = [
    # Contrib
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Third-party
    "rest_framework",
    "channels",                          # Django Channels — WS transport (see plans/10-realtime-layer.md)
    "drf_spectacular",                   # OpenAPI schema + Swagger UI

    # Donna apps
    "donna.core",
    "donna.users",
    "donna.workspaces",
    "donna.authentication",
    "donna.authorization",
    "donna.chat",
    "donna.integrations",
    "donna.notifications",
    "donna.status",
    "donna.cortex",
]

AUTH_USER_MODEL = "users.User"

# ─── Middleware ────────────────────────────────────────────────────────────────

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Whitenoise serves static files directly from uvicorn (no nginx needed).
    # MUST sit right after SecurityMiddleware per Whitenoise docs.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",

    # Logging middleware attaches a request_id to structlog's contextvars early.
    "donna.core.middleware.LoggingMiddleware",

    # Django auth → user context → workspace context (header-tenanted).
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "donna.workspaces.middlewares.UserContextMiddleware",
    "donna.workspaces.middlewares.WorkspaceMiddleware",

    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "donna.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "donna.wsgi.application"
ASGI_APPLICATION = "donna.asgi.application"

# ─── Database ──────────────────────────────────────────────────────────────────

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql_psycopg2",
        "NAME": env.str("DATABASE_NAME", default="donna"),
        "USER": env.str("DATABASE_USERNAME", default="donna"),
        "PASSWORD": env.str("DATABASE_PASSWORD", default="donna"),
        "HOST": env.str("DATABASE_HOST", default="database"),
        "PORT": env.str("DATABASE_PORT", default=5432),
        "CONN_MAX_AGE": env.int("DATABASE_CONN_MAX_AGE", default=25),
        "TEST": {
            "NAME": env.str("TEST_DATABASE_NAME", default="donna_test"),
        },
    }
}

# ─── Graph database (FalkorDB / Graphiti) ─────────────────────────────────────
#
# Connection params for graphiti_core.driver.FalkorDriver. FalkorDB speaks the
# Redis protocol; the `graph` service in docker-compose listens on 6379 inside
# the network. Host-side runs should override GRAPH_HOST=localhost.

GRAPH_DB = {
    "host":     env.str("GRAPH_HOST",     default="graph"),
    "port":     env.int("GRAPH_PORT",     default=6379),
    "database": env.str("GRAPH_DATABASE", default="donna"),
    "username": env.str("GRAPH_USERNAME", default=None) or None,
    "password": env.str("GRAPH_PASSWORD", default=None) or None,
}

# ─── DRF ───────────────────────────────────────────────────────────────────────

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_RENDERER_CLASSES": [
        "donna.core.renderers.StandardJSONRenderer",
    ],
    "EXCEPTION_HANDLER": "donna.core.exception_handler.custom_exception_handler",
    "DEFAULT_PAGINATION_CLASS": "donna.core.pagination.StandardLimitOffsetPagination",
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    # AUTHENTICATION_CLASSES intentionally omitted until the JWT-vs-session
    # decision lands (see plans/04-roadmap.md Phase 0).
    "PAGE_SIZE": 10,
    "NON_FIELD_ERRORS_KEY": "error",
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.JSONParser",
    ],
    "SEARCH_PARAM": "q",
    "ORDERING_PARAM": "sort",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

# ─── drf-spectacular ──────────────────────────────────────────────────────────
SPECTACULAR_SETTINGS = {
    "TITLE": "Donna API",
    "DESCRIPTION": "Multi-tenant chat + integrations + agent platform.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# ─── simplejwt ─────────────────────────────────────────────────────────────────
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME":  timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "AUTH_HEADER_TYPES":      ("Bearer",),
}

# ─── Auth + frontend ──────────────────────────────────────────────────────────
WEB_REDIRECT_HOST = env.str("WEB_REDIRECT_HOST", default="http://localhost:5173")

# Public backend URL used to build absolute webhook destination URLs handed to
# upstream vendors during `IntegrationProvider.on_connect`. WEB_REDIRECT_HOST
# targets the frontend; this targets the backend. In dev set to an ngrok /
# cloudflared tunnel — vendors cannot reach `localhost`.
DONNA_PUBLIC_BASE_URL = env.str("DONNA_PUBLIC_BASE_URL", default="http://localhost:8000")

# Google login OAuth — INTENTIONALLY SEPARATE from the integration-OAuth
# rows in donna.authentication.OAuthProvider (those drive Gmail/Drive
# ingestion). Login only needs identity; we don't persist Google refresh
# tokens at login.
GOOGLE_LOGIN_CLIENT_ID     = env.str("GOOGLE_LOGIN_CLIENT_ID",     default="")
GOOGLE_LOGIN_CLIENT_SECRET = env.str("GOOGLE_LOGIN_CLIENT_SECRET", default="")
GOOGLE_LOGIN_REDIRECT_URI  = env.str("GOOGLE_LOGIN_REDIRECT_URI",  default="")

# ─── Email backend ────────────────────────────────────────────────────────────
EMAIL_BACKEND       = env.str("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
EMAIL_HOST          = env.str("EMAIL_HOST",     default="")
EMAIL_PORT          = env.int("EMAIL_PORT",     default=587)
EMAIL_HOST_USER     = env.str("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env.str("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS       = env.bool("EMAIL_USE_TLS", default=True)
DEFAULT_FROM_EMAIL  = env.str("DEFAULT_FROM_EMAIL", default="noreply@donna.local")

# Where workspace-invitation accept links point (frontend route
# ``/invitations/<token>/accept``).
FRONTEND_BASE_URL = env.str("FRONTEND_BASE_URL", default="http://localhost:5173")

# ─── Storage (pluggable, env-var-driven) ──────────────────────────────────────
#
# One storage backend serves all of Donna's file storage (avatars, ingested
# blobs, etc.). Provider Celery tasks use `default_storage`.
# Pick the backend with `DONNA_STORAGE_BACKEND`; provide credentials via the
# matching env vars (see plans/06-deployment-and-self-hosting.md).

DONNA_STORAGE_BACKEND = env("DONNA_STORAGE_BACKEND", default="filesystem")


def _default_storage_config():
    backend = DONNA_STORAGE_BACKEND

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
                "location": env(
                    "DONNA_FILESYSTEM_ROOT",
                    default=str(BASE_DIR / "var" / "storage"),
                ),
                "base_url": env("DONNA_FILESYSTEM_BASE_URL", default=None),
            },
        }

    raise ValueError(
        f"Unknown DONNA_STORAGE_BACKEND: {backend!r} "
        f"(expected one of: s3, filesystem, gcs, azure)"
    )


STORAGES = {
    "default":     _default_storage_config(),
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# Auto-detect Django test mode so we can swap in throw-away storage and
# skip vault writes. `manage.py test` or `python -m django test` both
# put "test" in sys.argv. Honour the explicit env var too.
import sys as _sys  # noqa: E402

if "test" in _sys.argv or TESTING:
    STORAGES["default"] = {
        "BACKEND": "django.core.files.storage.InMemoryStorage",
    }
    # Vault writes would otherwise hit InMemoryStorage in tests too,
    # adding test noise (extra writes per CortexEntity save). Tests that
    # exercise the vault renderer explicitly opt in via
    # ``override_settings(CORTEX_VAULT_ENABLED=True)``.
    _VAULT_TEST_DEFAULT_OFF = True
else:
    _VAULT_TEST_DEFAULT_OFF = False

# ─── Integrations ──────────────────────────────────────────────────────────────
#
# Opt-out list. Connector slugs in this list are imported but not registered.
DISABLED_INTEGRATIONS = env.list("DONNA_DISABLED_INTEGRATIONS", default=[])

# ─── Celery ────────────────────────────────────────────────────────────────────
#
# Provider tasks register via @shared_task; the integrations app's apps.py
# auto-imports each connector's tasks.py at startup.

CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=None)
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"

# Beat schedule — per-connector poll fanouts. Each entry MUST point at a
# top-level fanout task that itself enqueues per-workspace work. Interval
# units are seconds.
CELERY_BEAT_SCHEDULE = {
    "gmail-fanout-sync": {
        "task":     "integrations.google.mail.fanout_sync",
        "schedule": env.int("DONNA_GMAIL_SYNC_INTERVAL", default=300),  # 5 min
    },
    "drive-fanout-sync": {
        "task":     "integrations.google.drive.fanout_sync",
        "schedule": env.int("DONNA_DRIVE_SYNC_INTERVAL", default=300),  # 5 min
    },
    "cortex-recluster-fanout": {
        "task":     "cortex.recluster_fanout",
        # 24h default — clusters drift slowly; pick longer for big
        # workspaces.
        "schedule": env.int("DONNA_CORTEX_RECLUSTER_INTERVAL", default=86400),
    },
    "cortex-reap-orphan-bodies": {
        # Nightly reaper for SilverStorage body files whose
        # CortexEntity row no longer exists (rare; only when PG
        # commit fails after storage write succeeded). Idempotent.
        "task":     "cortex.reap_orphan_bodies",
        "schedule": env.int("DONNA_CORTEX_REAP_INTERVAL", default=86400),
    },
    "cortex-flush-vault-indexes": {
        # Phase 5 (2026-06-19): per-entity render is synchronous in the
        # manager, but folder `_index.md` regen is debounced via a Redis
        # dirty-set + this beat job. SPOP per dirty folder → render.
        "task":     "cortex.flush_vault_indexes",
        "schedule": env.int("CORTEX_VAULT_FLUSH_SECONDS", default=300),  # 5 min
    },
    "cortex-reclassify-orgs": {
        # 00m org-relationship classifier (Tier A rules + Tier B Haiku)
        # — fires nightly to catch newly-collected email signal that
        # would shift an org's bucket (vendor→client when invoices stop
        # and SoW emails arrive, etc.). All workspaces, every workspace's
        # locked orgs are skipped.
        "task":     "cortex.reclassify_orgs",
        "schedule": env.int("CORTEX_RECLASSIFY_ORGS_INTERVAL", default=86400),  # 24h
    },
}

# ─── Cortex vault (Phase 5) ───────────────────────────────────────────────────
# Global kill switch for hierarchical vault rendering. When True (default),
# every CortexEntity write also lands at vault/<ws>/<parent_path>/<slug>.md
# and flags the folder dirty for the next `flush_vault_indexes` beat run.
# Disable to skip all vault I/O (agent + API surfaces are unaffected — they
# read straight from Postgres / the flat cortex/ tree).
CORTEX_VAULT_ENABLED = env.bool(
    "CORTEX_VAULT_ENABLED",
    default=not _VAULT_TEST_DEFAULT_OFF,
)

# ─── Channels (WebSocket transport) ───────────────────────────────────────────
#
# RedisChannelLayer reuses the Celery broker URL. Override via
# CHANNELS_REDIS_URL when you want WS pubsub on a separate Redis.
# See plans/10-realtime-layer.md.

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [env.str("CHANNELS_REDIS_URL", default=CELERY_BROKER_URL)],
        },
    },
}

# Presence TTL — WS clients heartbeat at half this interval.
DONNA_PRESENCE_TTL_SECONDS = env.int("DONNA_PRESENCE_TTL_SECONDS", default=30)

# ─── Password validation ───────────────────────────────────────────────────────

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ─── i18n / static ─────────────────────────────────────────────────────────────

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# DRF Spectacular — Donna API schema settings live earlier in this file
# (single canonical SPECTACULAR_SETTINGS block above).

# CORS
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True

CORS_ALLOW_HEADERS = ["*"]

CORS_ALLOW_METHODS = [
    "DELETE",
    "GET",
    "OPTIONS",
    "PATCH",
    "POST",
    "PUT",
]

# CSRF Trusted Origins
CSRF_TRUSTED_ORIGINS = env.list(
    "CSRF_TRUSTED_ORIGINS",
    default=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
)

# SIMPLE_JWT — single canonical block lives earlier in this file.

# ─── Logging ───────────────────────────────────────────────────────────────────
# Configure structlog last so it picks up final settings.

from donna.core.logging import configure_logging  # noqa: E402

configure_logging(
    log_level=env.str("LOG_LEVEL", default="INFO"),
    log_format=env.str("LOG_FORMAT", default="console"),
)
