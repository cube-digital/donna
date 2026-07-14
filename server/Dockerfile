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
# NOTE: build context is the repo ROOT (see .github/workflows/cloud-deploy.yml
# + docker-compose.yml) so the SPA under web/ is reachable — hence server/ path
# prefixes below.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=server/pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=server/uv.lock,target=uv.lock \
    uv sync --frozen --no-install-project --no-dev


# ─── Stage 1b: web builder (Vite SPA) ─────────────────────────────────────────
# Builds the React/Vite bundle from web/ → /web/dist, baked into the runtime
# image and served same-origin by WhiteNoise (settings.WEB_DIST_ROOT).
FROM node:22-bookworm-slim AS web-builder

WORKDIR /web

# Deps layer keyed on the lockfile — rebuilds only when deps change.
COPY web/package.json web/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci

COPY web/ ./
RUN npm run build


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

# Server source last so dep-layer cache holds across most edits. Context is the
# repo root, so copy only server/ into the workdir (not the whole monorepo).
COPY --chown=donna:donna server/ /opt/donna

# Built SPA bundle — served at "/" by WhiteNoise (settings.WEB_DIST_ROOT).
COPY --from=web-builder --chown=donna:donna /web/dist /opt/donna/web_dist

# Storage + static directories used by the filesystem storage backend
# and Django's collectstatic.
RUN mkdir -p /opt/donna/var/storage /opt/donna/staticfiles \
    && chown -R donna:donna /opt/donna/var /opt/donna/staticfiles \
    && chmod +x /opt/donna/deploy/entrypoint.sh

USER donna

EXPOSE 8000

# Reset uv's own entrypoint so our entrypoint script is what gets called.
ENTRYPOINT ["/opt/donna/deploy/entrypoint.sh"]
