# Support

Thanks for using Donna. This document points you at the right channel for the kind of help you need.

Donna is pre-1.0 open-source software. We do not yet offer paid commercial support. Best-effort help is available through the channels below.

## Before you ask

A surprising amount of "how do I…" is already answered. Please skim the obvious places first:

1. [`README.md`](README.md) — what Donna is, repo layout, quick start.
2. [Website](https://cube-digital.github.io/donna/) — vision, motivation, roadmap.
3. [`server/plans/`](server/plans/) — the live architecture + design contract. Every non-trivial decision lives here.
4. [`CONTRIBUTING.md`](CONTRIBUTING.md) — development setup, conventions, PR process.
5. [`SECURITY.md`](SECURITY.md) — secrets handling, supported versions, vulnerability disclosure.

If the answer is not in any of those, pick the right channel below.

## Where to ask

| You want to… | Channel | Link |
|---|---|---|
| Ask a usage question, share an idea, get feedback on an approach | GitHub Discussions | [github.com/cube-digital/donna/discussions](https://github.com/cube-digital/donna/discussions) |
| Report a reproducible bug | GitHub Issues — bug report | [New bug](https://github.com/cube-digital/donna/issues/new?template=bug_report.yml) |
| Propose a feature or design change | GitHub Issues — feature request | [New feature](https://github.com/cube-digital/donna/issues/new?template=feature_request.yml) |
| Report a security vulnerability | **Private channel only** | See [`SECURITY.md`](SECURITY.md) |
| Discuss something that does not fit any of the above | Email | `hello@cube-digital.com` |

### Decision rules

- **Question, not a bug?** → Discussions. Issues are for tracked work; discussions are for conversation.
- **Reproducible bug?** → Issue with the bug template. Include version, environment, repro steps, expected vs actual behaviour.
- **Bug, but you have a patch ready?** → Open a PR directly and link the failing scenario in the description. No need to file an issue first for small fixes.
- **Security finding?** → Never file a public issue. Use the private channels in [`SECURITY.md`](SECURITY.md).
- **Commercial enquiry, partnership, press, hosting interest?** → `hello@cube-digital.com`.

## Response expectations

Donna is built in the open by a small team. We read every issue and discussion, but response times vary by channel:

| Channel | Typical first response |
|---|---|
| Security disclosures | Within 3 business days (see [`SECURITY.md`](SECURITY.md)) |
| Bug reports | Within 1 week |
| Feature requests | Within 2 weeks (may sit longer if waiting on roadmap input) |
| Discussions | Best effort, the community is encouraged to help too |
| Email | Within 1 week for non-security topics |

These are targets, not SLAs. We will be slower around weekends, holidays, and stretches of deep work on the roadmap.

## What makes a good bug report

The fastest path to a fix is a report that lets a maintainer reproduce the issue without guessing. Please include:

- **Donna version or commit SHA** (`git rev-parse HEAD`)
- **Environment** — OS, Python version, browser if it is a web issue
- **Deployment mode** — local Docker stack, host Python, Cloud, on-premise
- **Connectors involved** (Gmail, Fathom, Drive, etc.)
- **Steps to reproduce** — exact commands, requests, or UI actions
- **Expected behaviour** vs **actual behaviour**
- **Logs** — relevant lines from `docker compose logs web worker`, with secrets redacted
- **Screenshots** for UI issues

The [bug report template](.github/ISSUE_TEMPLATE/bug_report.yml) walks you through these fields.

## What makes a good feature request

- **Problem first, solution second.** Tell us what you are trying to accomplish and why the current product makes it hard. We can often suggest a smaller change than the one you would have proposed.
- **Real example.** A concrete scenario from your work is worth more than an abstract description.
- **Scope.** "Add a Slack-style sidebar" is actionable. "Make collaboration better" is not.
- **Alternatives considered.** Even a one-line "I tried X but Y blocks it" helps.

The [feature request template](.github/ISSUE_TEMPLATE/feature_request.yml) prompts for these.

## Commercial use, hosting, and consulting

Donna is MIT-licensed. You can self-host for any purpose, including commercial.

If you would prefer a managed deployment, hands-on integration help, or a custom connector built for you, reach out to `hello@cube-digital.com`. We will tell you honestly whether we are the right fit and what the realistic timeline looks like.

## Out of scope

We are not able to help with:

- General Django, Celery, Postgres, or Redis questions that are not specific to Donna — please use the upstream communities.
- One-on-one tutoring for unrelated AI / LLM topics.
- Custom forks for which you do not want to upstream changes.

We will close such requests politely with a pointer to a better resource.

## Saying thank you

The most useful thanks you can give: a clear issue, a small PR, a Discussion answer for another user, a star on the repo, or telling a colleague.
