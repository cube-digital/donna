# 2026-06-09 15:45 — Website Scaffold and Pre-Public Hardening

## Summary & Overview

Built the public-facing Donna website from scratch as plain HTML in `docs/` (Odysseus-style, no SSG yet), iterated content with the user three times until the messaging matched the real product vision (chat workspace + Cowork-style agents grounded on Cortex). Did a full credential-exposure scan in preparation for flipping the repo public, the tree and git history came back clean. Started laying down the community / governance scaffolding (SECURITY.md, gitleaks workflow, .gitleaks.toml). README, CONTRIBUTING, LICENSE already existed and looked good. Session ended mid-scaffold, the remaining community files (CoC, SUPPORT, CHANGELOG, issue + PR templates) are still to write.

## Key Learnings

- **Donna's real positioning per user-provided source-of-truth brief**, a chat workspace (Slack/Discord shape) crossed with a collaborative AI workspace (Claude Cowork shape) where the agents are designed colleagues, not chatbots. Three target audiences: tech companies (engineering agents grounded via the MCP), service businesses (sales / ops / marketing using agents that know the company), solopreneurs (agents-as-team). Donna Cloud and self-hosted both run the same code. **Do not pitch it as a generic "context substrate", lead with the chat-with-colleagues framing.**
- **The roadmap is user-dictated, do not invent milestones.** The eight phases in order: M0 Foundations (shipped) → M1 Silver/Cortex (in progress) → M2 Retrieval chat agent → M3 Google Drive → M4 Draft/generation agent → M5 WhatsApp → M6 Linear+GitHub → M7 Private DMs with agents → M8 Learning personalities. Changelog and Docs pages are intentionally "coming soon" until a v1 ships.
- **Per the user, the website content must avoid technical jargon on the public-facing pages.** Technical depth lives only in `docs.html`. The Motivation page is a personal story (origin: Cube Digital agency pain), not a feature pitch.
- **Em dashes were a stylistic veto.** Replaced every ` — ` with `, ` across all 5 HTML files. User likely dislikes them globally, apply same rule to any future copy on this site.
- **Brand asset placement landed at, nav-brand only.** Hero character was rejected as "too big in the middle". Footer character was rejected as "too big". Only the small character right after "Donna" in the nav bar is acceptable. Promise-section + narrator-character variants were created then removed.
- **GitHub Pages serves anything from `branch/folder`**, Odysseus pattern is `Settings → Pages → Source: main branch, /docs folder, build type: legacy`. No Jekyll config needed if files are plain HTML, GitHub serves them as static.
- **`character.png` source dimensions are 168×355 (aspect 17:37, very portrait).** For accurate sizing without CLS: set HTML `width="170" height="370"` (intrinsic) + CSS `height: <px>; width: auto`. Or use `aspect-ratio: 17 / 37` in CSS.
- **Credential-scan findings, the tree is clean.** Zero `sk-…`, `ghp_…`, `AIza…`, `AKIA…`, `xox[bp]-…`, PEM, JWT, or service-account JSON in tracked files or git history. `.env`, `.env.docker`, `web/.env` all properly gitignored. `SECRET_KEY` in `settings.py` reads from env with a secure random fallback. Only dev-default to flag: `docker-compose.yml:34` uses `donna` as the fallback Postgres password, which is fine for local but must be documented.
- **`server/donna/integrations/migrations/0002_clientcredentials_oauthtoken_connection_and_more.py`** and `0003_remove_clientcredentials_authorize_url_and_more.py` matched the `credential` keyword in git history but are schema-only Django migrations, not data leaks.

## Solutions & Fixes

- **Character extraction from `fig_1_6_six_layer_stack.png`** → cropped to (50, 240, 320, 610), flood-filled cream background as transparent (RGB > 215/210/185, b < r heuristic), kept the largest connected opaque component to drop the dashed leader-line + caption-tail artifacts. Final transparent PNG at 168×355.
- **Website content felt generic / RAG-substrate-y on first pass** → user pushed back, "the information on the website is not accurate to the docs we have". Pulled real positioning from `server/plans/cortex/00 - vision.md`, `server/plans/01-architecture.md`, `server/plans/README.md`. Second pass still too tech-heavy → split into Home (audience-friendly) + Docs (technical depth). Third pass after user's full vision brief, rewrote everything top-down using the brief as source of truth.
- **`grep -rE` with too-complex regex** crashed ugrep → split secret-pattern scan into one prefix per call (`ghp_`, `sk-`, `AIza`, `AKIA`, `xox[bp]-`, `github_pat_`) instead of one mega-regex.
- **39 false-positive `sk-` matches in git history** (`Task->`, `ask-btn`, `microtask-`, `gx-task-check-`, etc.) → verified by extracting `sk-[a-zA-Z0-9_-]{20,}` (long-enough secret shape), zero matches.
- **Bash cwd jumping** → some bash calls landed in `assets/figures 2/png/` instead of repo root. Fixed by always prefixing with `cd /Users/ristoc/Workspaces/cube/donna && ...` or using absolute paths.

## Decisions Made

- **License = MIT.** Confirmed via existing `README.md:121` and `LICENSE` file. Permissive, max adoption. Alternatives rejected: Apache-2.0 (overkill on patent grant for this stage), AGPL-3.0 (would discourage adoption by SaaS-shaped users which is the wrong signal early).
- **Site stack = plain HTML in `/docs/`**, deferred VitePress. User explicitly said "later I would use vitepress after html". Reason: ship today, the content is small (5 pages), full design control matches the hand-drawn cartoon aesthetic of the existing figures.
- **Character placement = nav-brand only.** Removed from hero, promise section, motivation page narrator, footer. User: "this is too big, leave it only near the name".
- **Em dashes banned site-wide.** Replaced with `, ` via `sed -i '' 's/ — /, /g; s/—/, /g'` across all 5 HTML files.
- **Roadmap is user-authored, not me-authored.** I populated the eight phases verbatim from the user's brief. Do not invent or reorder.
- **Docs + Changelog pages stay as "coming soon" placeholders** until v1 ships. Per user direction.
- **Credential-scanning is gitleaks-based on push + PR + manual trigger.** Workflow `.github/workflows/gitleaks.yml` + config `.gitleaks.toml` (extends defaults, allowlists docs/, plans/, `.env.example`, known stopwords like `replace-me-in-production`).
- **Local repo destination chosen for this checkpoint** (vs Obsidian), the work is tightly coupled to the branch state.

## Pending Tasks

- [ ] Write `CODE_OF_CONDUCT.md` (Contributor Covenant v2.1, standard text, point `enforcement@cube-digital.com` or similar contact).
- [ ] Write `SUPPORT.md`. Channels: GitHub Discussions for Qs, GitHub Issues for bugs, SECURITY.md for vulns.
- [ ] Write `CHANGELOG.md` stub (Keep a Changelog format, `## [Unreleased]` section only since no v1 yet).
- [ ] Write `.github/PULL_REQUEST_TEMPLATE.md` (summary, motivation, testing, doc-sync trigger checkbox, breaking-change flag).
- [ ] Write `.github/ISSUE_TEMPLATE/bug_report.yml`, `.github/ISSUE_TEMPLATE/feature_request.yml`, `.github/ISSUE_TEMPLATE/config.yml` (config disables blank issues, points to Discussions for questions). README already references these by filename.
- [ ] Install `gitleaks` locally (`brew install gitleaks`) and run two final passes, `gitleaks detect --no-git -c .gitleaks.toml` (working tree) and `gitleaks detect -c .gitleaks.toml` (history). Both should return zero.
- [ ] Enable GitHub Pages, `Settings → Pages → Source: Deploy from a branch → main → /docs → save`. Site goes live at `https://cube-digital.github.io/donna/`.
- [ ] Branch protection on `main`, require PR review + passing gitleaks workflow before merge.
- [ ] Set the actual `enforcement@…` / `security@…` contact email in `SECURITY.md` (currently placeholder `security@cube-digital.com`).
- [ ] Resume P0.15a Cortex work (long-doc schema + builders + pipeline) per task #26 in TaskList, the website + governance side-quest was scope-creep into the original Cortex stream.
- [ ] Decide whether to commit the website (`docs/`), the governance files, and `.gitleaks.toml` as a single PR or split. Nothing is git-added yet.

## Errors & Workarounds

- **`cp: assets/figures 2/png/character.png: No such file or directory`** — Bash CWD landed somewhere unexpected (sandbox state). Workaround: always prefix `cd /Users/ristoc/Workspaces/cube/donna && ...` or use absolute paths. Proper fix: never rely on bash session CWD persistence in this tooling.
- **`ugrep: error at position 142, ... exceeds complexity limits`** — single mega-regex with 8+ alternation branches. Workaround: split into one `grep` call per prefix. Proper fix: keep regex alternation to 3-4 branches max in ugrep.
- **`File has not been read yet. Read it first before writing to it.`** on Write to `LICENSE` and `launch.json` — both existed already. Workaround: Read first, then Write or Edit. The harness enforces this for any file the assistant didn't author in the current context.
- **Preview screenshot kept showing mid-page content** (scrolled past the hero) — `location.href = '/index.html'` and `location.reload()` didn't reset scroll. Workaround: use `location.replace(...)` + `await new Promise(r => setTimeout(r, 400))` before scroll-to-top. Proper fix: pass `#top` anchor in URL or trigger `window.scrollTo({top:0, behavior:'instant'})` after a real navigation.

## Files Modified

### Website (all new in `docs/`)

- `docs/index.html` — landing page, audience-friendly tone, three audiences card grid, "How it works" three-step
- `docs/motivation.html` — personal origin story from Cube Digital agency pain, expanded vision in five movements
- `docs/roadmap.html` — git-graph layout with the user's exact 8 milestones (M0 shipped, M1 active, M2-M8 planned), click-to-expand cards
- `docs/changelog.html` — "coming with v1" placeholder
- `docs/docs.html` — "coming soon" placeholder, pointer to `server/plans/`
- `docs/assets/css/style.css` — full design system (palette lifted from `fig_*` figures: cream `#f6f1da`, navy `#2d2a40`, lavender / mint / sky / peach / yellow tinted cards, Fraunces display + Inter body, hard `var(--shadow)` Memphis-style shadows)
- `docs/assets/js/main.js` — nav active-link highlight + milestone-card expand toggle
- `docs/assets/character.png` — extracted character (168×355 transparent)
- `docs/assets/character_with_bg.png` — character with cream backdrop preserved
- `docs/assets/figures/fig_1_1..fig_1_6.png` — copied from `assets/figures 2/png/`
- `assets/figures 2/png/character.png` and `character_with_bg.png` — character extraction outputs

### Infrastructure

- `.claude/launch.json` — added `donna-site` config (python http.server on :4173 serving `docs/`)

### Governance (this session)

- `SECURITY.md` — full vuln-report policy, dev-default warnings, scope, allowlist
- `.github/workflows/gitleaks.yml` — gitleaks-action on push to main, PR, manual; full history scan (`fetch-depth: 0`)
- `.gitleaks.toml` — extends default ruleset, allowlists docs/plans/`.env.example`, stopwords for placeholders

### Pre-existing files referenced (not modified this session)

- `README.md` — already comprehensive, MIT badge, references templates by filename (`bug_report.yml`, `feature_request.yml`)
- `CONTRIBUTING.md` — already comprehensive, references CoC + templates
- `LICENSE` — already MIT 2026 Cube Digital

## Blockers & External Dependencies

- **GitHub Pages won't work on private repos on free plan.** Repo must flip public, OR org must upgrade to Pro/Team/Enterprise. Unblocks when: public-flip decision is made (license + secret scan are both green, no remaining technical blocker).
- **`security@cube-digital.com` in `SECURITY.md` is a placeholder.** User to confirm the real reporting address (could be a personal address, a team alias, or GitHub Advisories only). Unblocks when: user provides the address.
- **Local `gitleaks` not installed** (`brew install gitleaks` required for the local dry-run). The CI workflow will run regardless of local install, but a pre-public local pass is recommended belt-and-suspenders.
- **The eight-milestone roadmap dates ("Now / Next / Then / After 1.0")** are intentionally vague. If user wants real quarter targets, the cards need timestamps. Unblocks when: user supplies concrete dates per milestone, or confirms vague-on-purpose is fine for now.
