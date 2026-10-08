#!/usr/bin/env bash
# Restore a dump made by scripts/backup.sh into the docker compose `db` service.
# Usage: scripts/restore.sh backups/placcric-YYYYMMDDTHHMMSSZ.dump
# Replaces the current contents of the database. The app is stopped during the restore.
set -euo pipefail
cd "$(dirname "$0")/.."
FILE="${1:?Usage: scripts/restore.sh <dump-file>}"
[ -f "$FILE" ] || { echo "No such file: $FILE" >&2; exit 1; }
read -r -p "This REPLACES the current PlacCric database with $FILE. Type 'restore' to continue: " answer
[ "$answer" = "restore" ] || { echo "Cancelled."; exit 1; }
docker compose up -d --wait db
echo "Taking a safety backup of the current database first..."
scripts/backup.sh
docker compose stop app
docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' < "$FILE"
docker compose run --rm --no-deps app python -m app.cli db-status || true
docker compose up -d --wait app
echo "Restore complete."
