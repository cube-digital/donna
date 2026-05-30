---
name: donna-local
description: Bring up the entire Donna local development stack — Postgres + Redis containers, Django runserver, Celery worker, and the Vite web dev server — and verify every layer is healthy. Use whenever the user asks to "start Donna", "boot the stack", "run Donna locally", "fire up the dev environment", or similar. Idempotent: if a service is already up, leave it alone and just verify.
tools: Bash, Read, Write, Edit
model: sonnet
---

# donna-local — start the Donna development stack

Bring up the full local dev environment for Donna and verify every layer is
healthy. The repo lives at `/Users/andreeamiclaus/Desktop/Workspace/Cube/Donna/donna/`.

## What you're starting

| Layer | Where | URL / port |
|---|---|---|
| Postgres | docker compose service `database` | host `5551` → container `5432` |
| Redis | docker compose service `cache` | host `6667` → container `6379` |
| Django runserver | `server/`, venv | http://127.0.0.1:8000 |
| Celery worker | `server/`, venv | (no port) |
| Vite dev server | `web/` | http://localhost:5173 |
| Optional: Electron | `desktop/` | wraps the Vite server |

## Bring-up sequence

### 1. Pre-flight

```bash
cd /Users/andreeamiclaus/Desktop/Workspace/Cube/Donna/donna/server
[ -f .env ] || cp .env.example .env
mkdir -p env && [ -f env/.env.docker ] || cp .env.example env/.env.docker
[ -d .venv ] || uv sync
```

### 2. Postgres + Redis

```bash
# Shell-side overrides are CRITICAL: .env has DATABASE_PORT=5551 / REDIS_PORT=6667
# (host-side, what Django connects to). Compose also reads .env and would map
# the host port to itself on the container side. The inline override forces
# the container side to 5432 / 6379 (the real Postgres / Redis ports).
DATABASE_PORT=5432 REDIS_PORT=6379 docker compose up -d database cache
```

Poll `docker compose ps` until both `donna-database` and `donna-cache` are
`(healthy)`. Cap at 30s.

### 3. Migrate + runserver

```bash
DJANGO_SETTINGS_MODULE=donna.settings .venv/bin/python -m django migrate
```

Start the dev server in the background only if nothing is on :8000:

```bash
if ! lsof -ti :8000 > /dev/null; then
  DJANGO_SETTINGS_MODULE=donna.settings nohup .venv/bin/python -m django runserver \
    > /tmp/donna-runserver.log 2>&1 &
  disown
fi
```

Verify with a public auth endpoint (avoids the X-Workspace-Id wall):

```bash
sleep 3
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/auth/google/login
# expect 200
```

### 4. Celery worker

```bash
if ! pgrep -f 'celery.*donna.*worker' > /dev/null; then
  nohup .venv/bin/celery -A donna worker --loglevel=info \
    > /tmp/donna-celery.log 2>&1 &
  disown
fi
```

### 5. Vite dev server

```bash
cd ../web
[ -d node_modules ] || npm install

if ! lsof -ti :5173 > /dev/null; then
  nohup npm run dev > /tmp/donna-web.log 2>&1 &
  disown
fi
```

Wait until `curl -s -o /dev/null -w "%{http_code}" http://localhost:5173/`
returns `200`. Cap at 30s.

### 6. (Optional) Electron

Only do this if the user asked for "with Electron" or "the desktop app":

```bash
cd ../desktop
[ -d node_modules ] || npm install
nohup npm run start:dev > /tmp/donna-electron.log 2>&1 &
disown
```

## Report back

A compact status table is enough:

```
✓ Postgres   127.0.0.1:5551  (donna / donna / donna)
✓ Redis      127.0.0.1:6667
✓ Django     http://127.0.0.1:8000
✓ Celery     pid <N>
✓ Web        http://localhost:5173
ℹ Test login andreea.miclaus@cube-digital.io / thisisatest
ℹ Logs       /tmp/donna-{runserver,celery,web}.log
```

If any step fails, surface the error inline + tail ~10 lines of the
relevant log.

## Rules

- **Idempotency** — if a port is bound or a process matches, leave it alone
  and just verify it answers. Don't kill and restart unless asked.
- **Never `docker compose down -v`** unless explicitly asked — `-v` nukes
  the Postgres volume and you lose every workspace, user, and message.
- **Never run `npx tsc` without `--noEmit`** — it emits `.js` files
  alongside `.ts` sources and pollutes the tree.
- **Don't touch `.env` files** unless they're missing entirely. The host
  / container port split is hand-tuned; rewriting it breaks the mapping.
- **Don't run `pkill` broadly** — use `pgrep` to find the exact PID and
  send SIGTERM to that PID only. The user might have unrelated `node` or
  `python` processes.
