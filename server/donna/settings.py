"""
Django settings for donna project.

Env-driven (via django-environ). Defaults are suitable for local development;
override via environment variables for any non-dev deployment.
"""

from pathlib import Path

import environ


BASE_DIR = Path(__file__).resolve().parent.parent

# ─── Environment ───────────────────────────────────────────────────────────────

env = environ.Env(
    DEBUG=(bool, True),
    ALLOWED_HOSTS=(list, ["*"]),
    LOG_LEVEL=(str, "INFO"),
    LOG_FORMAT=(str, "json"),
)

# Load .env file if present (looks for `.env` next to settings.py).
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env(
    "SECRET_KEY",
    default="django-insecure-dev-only-_^41*gm-7$4(ui2av_)kerd-w!1&t30ra*%h-d9g$zkr(82h^3",
)
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

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
]

AUTH_USER_MODEL = "users.User"

# ─── Middleware ────────────────────────────────────────────────────────────────

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
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
    "default": env.db_url(
        "DATABASE_URL",
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
    ),
}

# ─── DRF ───────────────────────────────────────────────────────────────────────

REST_FRAMEWORK = {
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
}

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

    raise ValueError(
        f"Unknown DONNA_STORAGE_BACKEND: {backend!r} "
        f"(expected one of: s3, filesystem, gcs, azure)"
    )


STORAGES = {
    "default":     _default_storage_config(),
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

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
}

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

# ─── Logging ───────────────────────────────────────────────────────────────────
# Configure structlog last so it picks up final settings.

from donna.core.logging import configure_logging  # noqa: E402

configure_logging(log_level=env("LOG_LEVEL"), log_format=env("LOG_FORMAT"))
