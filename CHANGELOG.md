# Changelog

All notable changes to Donna are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
once it reaches `v1.0.0`. Until then, breaking changes can land at any time on `main`
and will be called out in the `Unreleased` section below.

## Types of changes

- **Added** — new features.
- **Changed** — changes to existing functionality.
- **Deprecated** — features still present but slated for removal.
- **Removed** — features removed in this release.
- **Fixed** — bug fixes.
- **Security** — vulnerability fixes (cross-reference an advisory when relevant).

---

## [Unreleased]

The project is pre-`v1.0.0`. Entries below describe work that has landed on `main`
since the public launch of the repository. They will be grouped under the first
tagged release when the v1 milestone ships.

### Added

- Public repository launch with full project documentation: `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `SUPPORT.md`, `CHANGELOG.md`.
- Public marketing website served from `docs/` on GitHub Pages: home, motivation, roadmap, changelog, docs.
- Automated secret scanning on every push and pull request via `gitleaks` (`.github/workflows/gitleaks.yml` + `.gitleaks.toml`).
- Multi-tenant chat workspace primitives: workspaces, channels, threads, direct messages, membership (`X-Workspace-Id` header-based tenancy).
- Connector framework in `donna/core/integrations/`: provider Protocol, HTTP client base, OAuth handler, webhook handler, adapter base, registry.
- Bronze ingestion layer with idempotent `DeliveryPackage` model.
- Fathom (meetings) connector — OAuth + webhook + adapter.
- Gmail (mail) connector — OAuth + polling + adapter, sharing the `google` OAuth provider with Drive.
- Real-time layer scaffolding: SSE channel per (user, workspace) for notifications, Django Channels WebSockets for chat / DM / presence / agent token streaming.
- Storage backend abstraction driven by `DONNA_STORAGE_BACKEND` (`filesystem | s3 | gcs | azure`); any S3-compatible service supported via `DONNA_S3_ENDPOINT_URL`.
- Standard app layout enforced project-wide (`models.py`, `services.py`, `api/v1/{views,serializers,filters}.py`, `urls.py`, `tests/`) — see `server/plans/03-conventions-and-api.md`.
- `donna.core` shared infrastructure: `BaseService`, `ModelViewSet`, `TimestampsMixin`, `UserAuditMixin`, `EncryptedTextField`, `StandardJSONRenderer`, `LoggingMiddleware`, structlog wiring.
- Bring-your-own-credentials model: `OAuthProvider` rows populated from `DONNA_OAUTH_<SLUG>_*` env vars (Cloud) or Django admin (on-premise).
- Authentication flows: email/password + Google OAuth login, password reset, email verification (`server/plans/09-auth-and-notifications.md`).
- Per-tenant integration configuration via `Connection` model with JSON config + state and JSON Schema validation (`server/plans/08-connection-pattern.md`).
- Issue templates (bug report, feature request) and pull request template under `.github/`.

### Changed

- Project positioning consolidated as "chat workspace where AI agents are real colleagues" — part Slack, part Claude Cowork. Website, README, and motivation page rewritten to match.
- Em-dash characters removed site-wide in favor of comma-space, matching house style.
- README expanded substantially with project layout, quick start, self-hosting, documentation map, and community standards sections.

### Security

- All credential patterns (`.env`, `*.pem`, `*.key`, service account JSON, OAuth secrets) added to `.gitignore`; baseline scan of working tree and full git history confirmed clean before public release.
- `SECURITY.md` published with vulnerability disclosure policy, scope, and supported-version statement.

---

## [0.0.0] — Pre-release

Donna existed as a private repository prior to the public launch. No tagged
releases were cut during that phase; the codebase evolved directly on `main`.
This `0.0.0` entry exists only to anchor the changelog's history.

The current public state of the repository is the starting point for all
future release notes. Subsequent releases will be added above this line in
reverse chronological order.

[Unreleased]: https://github.com/cube-digital/donna/commits/main
[0.0.0]: https://github.com/cube-digital/donna/commits/main
