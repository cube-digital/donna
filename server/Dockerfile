# syntax=docker/dockerfile:1.7
#
# Multi-stage Dockerfile for the Donna server.
#
# Base: Astral's official uv image (Python 3.13, Debian Bookworm slim).
# - Maintained by the uv authors → secure, small, fast.
# - Ships uv preinstalled → no third-party COPY trick needed.
#
# Two stages:
#   builder — installs project deps via `uv sync --frozen --no-install-project`.
#             Caches uv's wheel cache + bind-mounts pyproject/uv.lock so the
#             dep-only layer rebuilds only when those files change.
#   runtime — copies the prepared .venv, adds project source, runs as
#             non-root. Entrypoint script runs migrate + collectstatic +
#             uvicorn. Worker / beat services bypass the entrypoint and
#             exec `celery` directly (see docker-compose.yml).

# ─── Stage 1: builder ─────────────────────────────────────────────────────────
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

# Build-only OS deps (psycopg2 needs libpq + headers, plus a C compiler).
RUN apt-get update -y \
    && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        libpq-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/donna

# Install dependencies in their own layer using a cached uv wheel store.
# pyproject.toml + uv.lock are bind-mounted (no COPY) so this layer's
# cache key tracks them; project source is added later.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --frozen --no-install-project --no-dev


# ─── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=donna.settings \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# Runtime OS deps only — no compiler toolchain.
# libpq5 for psycopg2 runtime; postgresql-client for the entrypoint's
# pg_isready-equivalent + `docker compose run --rm server psql ...`.
RUN apt-get update -y \
    && apt-get install -y --no-install-recommends \
        libpq5 \
        postgresql-client \
        curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash donna

WORKDIR /opt/donna

# Bring the venv across from the builder.
COPY --from=builder --chown=donna:donna /opt/venv /opt/venv

# Project source last so dep-layer cache holds across most edits.
COPY --chown=donna:donna . /opt/donna

# Storage + static directories used by the filesystem storage backend
# and Django's collectstatic.
RUN mkdir -p /opt/donna/var/storage /opt/donna/staticfiles \
    && chown -R donna:donna /opt/donna/var /opt/donna/staticfiles \
    && chmod +x /opt/donna/deploy/entrypoint.sh

USER donna

EXPOSE 8000

# Reset uv's own entrypoint so our entrypoint script is what gets called.
ENTRYPOINT ["/opt/donna/deploy/entrypoint.sh"]
