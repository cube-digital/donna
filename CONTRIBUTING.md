# Contributing to Donna

Thanks for considering a contribution. Donna is built in the open and we welcome help, bug reports, design feedback, docs fixes, and code, no contribution is too small.

This document covers:

1. [Code of Conduct](#code-of-conduct)
2. [Ways to contribute](#ways-to-contribute)
3. [Development setup](#development-setup)
4. [Project layout](#project-layout)
5. [Conventions](#conventions)
6. [Pull request process](#pull-request-process)
7. [Branching and commits](#branching-and-commits)
8. [Tests](#tests)
9. [Security disclosures](#security-disclosures)
10. [License](#license)

---

## Code of Conduct

By participating in this project you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md). Be kind, be patient, assume good faith.

## Ways to contribute

You do not need to write code to help.

- **Report a bug**, open an issue using the [bug report template](.github/ISSUE_TEMPLATE/bug_report.yml).
- **Propose a feature** or design change with the [feature request template](.github/ISSUE_TEMPLATE/feature_request.yml).
- **Improve documentation**, typo fixes, clearer explanations, missing examples, all welcome.
- **Triage issues**, comment with reproductions, suggest labels, link related issues.
- **Build a connector**, the connector framework is designed to make adding integrations small.
- **Submit a code change**, see the pull request process below.

For open-ended ideas or design questions, start a [Discussion](https://github.com/cube-digital/donna/discussions) before opening a PR. It keeps the work coordinated and avoids wasted effort.

## Development setup

### Prerequisites

- **Python 3.13+** (managed via [uv](https://github.com/astral-sh/uv))
- **Node.js 20+** with [pnpm](https://pnpm.io/)
- **Docker** + Docker Compose (for the full local stack)

### Full stack via Docker (recommended)

```bash
git clone https://github.com/cube-digital/donna.git
cd donna/server
docker compose up --build              # Postgres + Redis + web + worker + beat
docker compose run --rm web bootstrap  # seed OAuthProvider rows from env
docker compose run --rm web shell      # Django shell
docker compose logs -f worker          # tail Celery worker
```

### Server only (host Python)

```bash
cd server
uv sync
cp .env.example .env                   # fill in DATABASE_URL, REDIS_URL, DONNA_OAUTH_*
uv run python manage.py migrate
uv run python manage.py runserver
uv run celery -A donna worker -l info  # separate terminal
uv run celery -A donna beat -l info    # separate terminal
```

### Web client

```bash
cd web
pnpm install
pnpm dev                               # http://localhost:5173
```

### Desktop client

```bash
cd desktop
pnpm install
pnpm dev
```

### Smoke test

1. API up, `curl http://localhost:8000/api/health/` returns 200.
2. Bootstrap ran, `OAuthProvider.objects.count() >= 1`.
3. Web chat opens at `http://localhost:5173`, you can sign in.

## Project layout

| Path | Purpose |
|---|---|
| `server/` | Django backend, all backend code lives here |
| `server/donna/<app>/` | App layout per `server/plans/03-conventions-and-api.md` |
| `server/donna/core/` | Shared infrastructure, do not import from apps into core |
| `server/donna/integrations/connectors/<name>/` | One folder per connector |
| `server/plans/` | Authoritative architecture + build plan (read first) |
| `server/plans/cortex/` | The Cortex substrate, vision + contracts + flows |
| `web/` | Vite + TypeScript web client |
| `desktop/` | Electron + TypeScript desktop client |
| `docs/` | Public website (GitHub Pages) |
| `assets/` | Brand assets, diagrams, figures |

Read [`server/plans/README.md`](server/plans/README.md) before making non-trivial backend changes, the design decisions live there.

## Conventions

### Python (server)

- **Package manager**, `uv` (never `pip` directly).
- **App layout**, see `server/plans/03-conventions-and-api.md`. Mandatory structure: `models.py`, `services.py`, `api/v1/{views,serializers,filters}.py`, `urls.py`, `tests/`.
- **Business logic lives in `services.py`**, not in views or serializers.
- **Services extend `donna.core.services.BaseService`**.
- **Logging**, `get_logger(__name__)` from `donna.core.logging`, never `print()` or stdlib `logging`.
- **Exceptions**, `NotFoundException` / `BadRequestException` from `donna.core.exceptions`.
- **Sensitive fields**, `EncryptedCharField` / `EncryptedTextField` (Fernet).
- **Model PKs**, UUID.
- **API responses**, auto-wrapped by `StandardJSONRenderer`, do not hand-roll envelopes.
- **PATCH only, no PUT** (`UpdateModelMixin.partial_update`).
- **LLM access**, via `LLMFactory` only, never a raw provider SDK.

### TypeScript (web / desktop)

- **Package manager**, `pnpm`.
- **Style**, follow the existing files in each folder.
- **No direct backend calls from components**, route through a thin API client.

### Documentation

- Update `server/plans/<doc>.md` when you change architectural shape (new model, new endpoint, new convention).
- The plans are the live design contract, not historical artifacts.

## Pull request process

1. **Fork** the repo and create a feature branch from `main` (see [Branching](#branching-and-commits)).
2. **Make changes**, keep PRs small and focused. One concern per PR.
3. **Run tests** locally (see [Tests](#tests)). Add tests for new behaviour.
4. **Update docs**, if you changed architectural shape or public API, update the relevant `server/plans/<doc>.md` in the same PR.
5. **Open the PR** with a clear title and description. Fill in the PR template.
6. **CI must pass**, lint + tests on every push.
7. **At least one maintainer review** is required before merge.
8. **Squash and merge** is the default. Keep the commit history clean.

### What gets merged faster

- One concern per PR.
- Tests included.
- Docs updated when shape changes.
- Clear motivation in the description (link the issue if there is one).
- Small diff, big diffs need extra justification.

## Branching and commits

- **Branch names**, `feature/<slug>`, `fix/<slug>`, `docs/<slug>`, `chore/<slug>`.
- **Commit messages**, conventional commits style:
  ```
  feat(cortex): add long-document section builder
  fix(integrations): handle Gmail token refresh edge case
  docs(plans): clarify the bronze idempotency contract
  ```
- **Doc-sync trigger**, if your change touches a path tracked by the doc-sync matrix in `CLAUDE.md`, include `[doc-sync: <category>]` in the commit message.

## Tests

```bash
# Server
cd server
uv run pytest                          # all tests
uv run pytest donna/cortex/tests/      # one module
uv run pytest -k test_name             # one test

# Inside docker
docker compose run --rm web pytest

# Web
cd web && pnpm test
```

Write tests for new code. Bug fixes should land with a regression test. Use `factory_boy` for fixtures (Python) or the existing test utilities (web).

## Security disclosures

**Do not file public issues for security findings.** See [`SECURITY.md`](SECURITY.md) for the responsible-disclosure process.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE) that covers the project. You retain copyright on your contributions, you grant a license to the project under MIT terms.

---

Thanks for reading. If anything in this doc is unclear, open an issue and tell us, that itself is a contribution.
