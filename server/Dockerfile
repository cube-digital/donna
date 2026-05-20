# syntax=docker/dockerfile:1.7
#
# Multi-stage Dockerfile for the Donna server.
# Single image, multiple commands: web (gunicorn), worker (celery), shell, etc.

# ─── Stage 1: builder — install Python deps with uv ────────────────────────────
FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# uv from official image (small, fast).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install deps first (cache layer) using only the lock-like files.
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-install-project 2>/dev/null || uv sync --no-install-project

# ─── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=donna.settings

# Runtime deps only — no build tooling.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash app

WORKDIR /app

# Copy the prepared venv from builder.
COPY --from=builder /opt/venv /opt/venv

# Project source.
COPY --chown=app:app . /app

# Storage + static dirs (default_storage filesystem backend writes here).
RUN mkdir -p /app/var/storage /app/staticfiles && chown -R app:app /app/var /app/staticfiles

USER app

EXPOSE 8000

# Entrypoint runs migrate + collectstatic for the web role; bypassed for worker.
COPY --chown=app:app deploy/entrypoint.sh /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["web"]
