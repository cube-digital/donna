# Security Policy

Donna is early-stage open-source software. We take security seriously even while the surface is changing fast. This document explains how to report a vulnerability and how we handle secrets in the repo.

## Reporting a vulnerability

**Do not open a public GitHub issue for security reports.**

Use one of these private channels instead:

- **Preferred:** [GitHub Security Advisories](https://github.com/cube-digital/donna/security/advisories/new) (private to maintainers).
- **Email:** `security@cube-digital.com`

When reporting, please include:

1. A description of the issue and the impact.
2. Steps to reproduce, ideally with a minimal example.
3. Affected version / commit SHA.
4. Any suggested remediation if you have one.

## What to expect

| Step | Target time |
|---|---|
| First acknowledgement | within 3 business days |
| Triage + severity assessment | within 7 business days |
| Patch or mitigation plan | within 30 days for high/critical |
| Public disclosure | coordinated with reporter, normally after a fix is released |

We will credit you in the advisory unless you ask us not to. We do not currently run a paid bug bounty program.

## Supported versions

Donna has not yet shipped a public v1. Security fixes land on `main`. Once we tag a v1.0.0, we will publish a support matrix here covering the active release line.

## Secrets in this repository

The repository is meant to be safe to fork, clone, and self-host. The following rules apply.

### Never commit real secrets

The following file patterns are gitignored and **must never** be committed:

- `.env`, `.env.local`, `.env.docker`, `.envrc`
- `*.pem`, `*.key`, `*.p12`, `*.pfx`, `id_rsa*`, `id_ed25519*`
- Google / AWS / GCP service account JSON files
- Any file containing OAuth client secrets, API keys, tokens, or session keys

Always use `.env.example` (placeholder values only) as the template. Real values live in `.env`, which is local-only.

### Known dev-only defaults

For local development convenience, a few defaults are hardcoded. **None of these should be used in production.**

| Location | Value | Purpose | Production action |
|---|---|---|---|
| `server/docker-compose.yml` | `POSTGRES_PASSWORD: ${DATABASE_PASSWORD:-donna}` | Default dev DB password | Set `DATABASE_PASSWORD` in your production environment |
| `server/.env.example` | `SECRET_KEY=replace-me-in-production` | Placeholder Django secret key | Generate a fresh secret key per deployment |
| `server/.env.example` | `DEBUG=True` | Local debug mode | Set `DEBUG=False` in production |
| `server/.env.example` | `ALLOWED_HOSTS=*` | Local catch-all | Set to your real hostnames in production |

### Bring-your-own credentials

Donna is designed so the operator owns all third-party credentials. OAuth client IDs and secrets for Gmail, Google Drive, Fathom, etc. are filled in either via environment variables (Cloud) or via the Django admin (on-premise). The framework reads them from the database at runtime. The repository does not ship any provider credentials.

## Automated scanning

Every push and pull request runs [`gitleaks`](https://github.com/gitleaks/gitleaks) over the diff and the git history. Builds fail if a credential pattern is detected. See `.github/workflows/gitleaks.yml`.

If `gitleaks` flags a false positive on a commit you authored, do **not** disable the workflow. Instead:

1. Add the path or pattern to `.gitleaksignore` (one entry per line).
2. Open a PR with a short justification in the commit message.

## Disclosure policy

We follow [coordinated disclosure](https://www.cisa.gov/coordinated-vulnerability-disclosure-process). After a fix is released:

- We publish an advisory on the GitHub Security Advisories page.
- The CHANGELOG entry includes the CVE (if assigned) and credits the reporter.
- We do not publicly link an issue to a vulnerability until a fix is available.

## Out of scope

These reports will be acknowledged but do not qualify as security issues under this policy:

- Vulnerabilities in third-party dependencies for which an official patch is already available (open an issue or PR upgrading the dep).
- Issues affecting only deprecated or unsupported branches.
- Findings that require physical access to the host, root-level access, or social engineering of a maintainer.
- Self-XSS, clickjacking on pages without sensitive actions, or missing security headers on docs / marketing pages.
- Output of automated scanners with no proof of impact.

Thanks for helping keep Donna safe.
