#!/usr/bin/env bash
# Wipe any FS residue left behind by a Django test run that pre-dates
# the 2026-06-19 InMemoryStorage default. Keeps the cube-digital
# workspace (6bff774a-...) and any other dir matching a live workspace
# UUID in Postgres. Safe to run anytime; idempotent.
#
# Test DB itself is auto-dropped by Django after the run (no action
# needed there). This handles only `default_storage` leftovers.
#
# Usage:
#   bash server/scripts/cleanup_test_residue.sh

set -euo pipefail

cd "$(dirname "$0")/../var/storage"

# Workspace UUIDs to keep — pulled live from Postgres so the keep-list
# always reflects current state, not a hardcoded list.
KEEP_IDS=$(
  docker exec donna-database psql -U donna -d donna -tA \
    -c "SELECT id FROM workspaces;" 2>/dev/null || true
)

if [ -z "$KEEP_IDS" ]; then
  echo "WARN: could not query workspaces table — bailing out without deletes."
  exit 0
fi

KEEP_PATTERN=$(echo "$KEEP_IDS" | tr '\n' '|' | sed 's/|$//')

removed=0
for d in $(find . -maxdepth 1 -type d -name "????????-????-????-????-????????????" | grep -vE "$KEEP_PATTERN" || true); do
  rm -rf "$d"
  removed=$((removed + 1))
done
for d in $(find cortex vault -mindepth 1 -maxdepth 1 -type d 2>/dev/null | grep -vE "$KEEP_PATTERN" || true); do
  rm -rf "$d"
  removed=$((removed + 1))
done

echo "removed $removed orphan workspace dirs"
echo "kept dirs:"
find . -maxdepth 2 -type d -name "????????-????-????-????-????????????" | sort
