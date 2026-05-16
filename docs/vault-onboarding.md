# Vault onboarding — new team member setup

This guide gets you set up with the shared Cube-Digital knowledge vault on your machine. Takes about 15 minutes. You'll end up with Obsidian auto-syncing to the team's shared GitHub repository — no Obsidian Sync account needed.

## Prerequisites

You need:
- Obsidian installed (download at obsidian.md if not)
- Git installed (check with `git --version` in terminal; install via `xcode-select --install` on macOS if missing)
- Access to the GitHub repository (ask Rares or Andreea to add you)

## Step 1: Clone the repository

Open Terminal and run:

```bash
git clone https://github.com/cube-digital/cube-context.git ~/cube-context
```

This downloads the vault to `~/cube-context` on your machine. If you'd prefer a different location, change the path at the end.

## Step 2: Authenticate with GitHub

You need a Personal Access Token to push changes back to GitHub.

**Create the token:**
1. Go to github.com → click your profile picture → Settings
2. Scroll to the bottom → Developer settings
3. Personal access tokens → Tokens (classic) → Generate new token (classic)
4. Give it a name: `obsidian-vault-yourname`
5. Expiration: 90 days (you'll need to renew it then, or set No expiration)
6. Tick the `repo` scope only
7. Click Generate token
8. **Copy it immediately** — GitHub only shows it once

**Store it so git never asks again:**

```bash
git config --global credential.helper osxkeychain
cd ~/cube-context
git pull
```

If it asks for username and password:
- Username: your GitHub username
- Password: paste the token (not your actual GitHub password)

macOS Keychain stores it. You won't be asked again.

If it doesn't ask (says "Already up to date"), credentials were already stored and you're good.

## Step 3: Open the vault in Obsidian

1. Open Obsidian
2. Click the vault switcher (bottom left, looks like a vault icon)
3. Click "Open folder as vault"
4. Navigate to `~/cube-context` and select it
5. Click Open

Obsidian loads the vault. You should see the project folders and documentation.

If Obsidian asks "Trust author of this vault?" — click Trust. The vault was set up by the team.

If Obsidian offers to install community plugins — accept. It reads the shared plugin list and installs what the team uses.

## Step 4: Install and configure Obsidian Git

The Git plugin is what keeps your vault in sync with everyone else automatically.

**Install:**
1. Settings (gear icon, bottom left) → Community plugins
2. If you see "Turn on community plugins" — click it
3. Click Browse
4. Search for "Git"
5. Find "Obsidian Git" by Vinzent → Install → Enable

**Configure:**
1. Settings → Community plugins → Git → gear icon next to it
2. Set these values:

| Setting | Value |
|---|---|
| Auto commit-and-sync interval | 10 |
| Auto commit-and-sync after stopping file edits | ON |
| Auto pull interval | 5 |
| Pull on startup | ON |
| Commit message | `vault: {{date}} — {{numFiles}} files` |

Everything else can stay at defaults.

## Step 5: Test that sync works

Make a small test edit — add a line to any file, or create a throwaway note.

Then either wait ~10 minutes for auto-sync, or trigger it manually:

**Cmd-P** → type "Obsidian Git: Commit and sync" → Enter

Check that it runs without errors. If you see a success notification, you're done.

You can verify by checking the repository on GitHub — your commit should appear within a few seconds of the sync.

## How sync works day-to-day

You don't need to do anything manually. The plugin handles it:

- **On startup**: pulls latest changes from the team automatically
- **Every 5 minutes**: pulls any new changes from teammates
- **Every 10 minutes**: commits and pushes your local changes
- **After you stop editing**: commits and pushes shortly after you stop typing

The result: your vault stays in sync with the team automatically, like Dropbox but for markdown files.

## When you see a merge conflict

Occasionally (rarely) two people edit the same file at the same time and git can't automatically merge. Obsidian Git shows a notification.

When this happens:
1. Open the conflicted file — you'll see conflict markers like `<<<<<<`, `=======`, `>>>>>>>`
2. Manually pick which version you want (or combine both)
3. Delete the conflict markers
4. Save the file
5. Cmd-P → "Obsidian Git: Commit and sync"

If you're unsure, ping Rares — he can help resolve it in under a minute.

## Folder structure quick reference

```
cube-context/
├── README.md              # vault overview
├── CLAUDE.md              # conventions for Claude Code
├── _docs/                 # architecture and how-it-works docs
├── _registry.yaml         # list of active projects
├── _unrouted/             # things the ingestion pipeline couldn't match
└── projects/
    ├── acme/
    │   ├── _brief.md      # what this project is — read this first
    │   ├── _status.md     # current state
    │   ├── meetings/      # distilled meeting notes
    │   ├── emails/        # project-relevant emails
    │   ├── drive-index.md # links to Drive documents
    │   └── decisions.md   # decision log
    └── [other projects]/
```

When you pick up a new project, start with `projects/<name>/_brief.md`.

## Using Claude Code with the vault

If you use Claude Code for development work, run it from inside the project folder:

```bash
cd ~/cube-context
claude
```

Claude Code reads the `CLAUDE.md` at the vault root and understands the structure. You can ask it questions about any project and it'll read the relevant context automatically.

## Troubleshooting

**"Public key" error when syncing:**
Your token may have expired. Generate a new one (Step 2) and run `git pull` from terminal — it'll ask for credentials again and store the new token.

**Plugin not syncing, no error shown:**
Check Settings → Community plugins → Git is enabled (toggle is blue). If it is, try Cmd-P → "Obsidian Git: Pull" manually to see if an error appears.

**Files missing that teammates have:**
Run Cmd-P → "Obsidian Git: Pull" manually. If it still doesn't appear, check terminal: `cd ~/cube-context && git pull` to see if there's a git-level error.

**Obsidian asks about the `.obsidian` folder on first open:**
Accept it. The team shares base plugin and appearance settings via this folder; your personal workspace layout is kept local automatically.

**Token expired (after 90 days):**
Generate a new token on GitHub (same steps as Step 2). Run `git pull` from terminal, enter the new token when prompted. Keychain updates the stored credential.

## Questions

Ping Rares or Andreea on Slack. For git-specific issues, describing what you see in terminal after `git pull` is usually enough to diagnose the problem quickly.
