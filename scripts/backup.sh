#!/usr/bin/env bash
# Back up the PlacCric PostgreSQL database from the docker compose `db` service.
# Usage: scripts/backup.sh [backup-directory]      (default: ./backups, ignored by git)
# Keeps the newest $KEEP_BACKUPS dumps (default 14). Backups contain private notes: keep them private.
set -euo pipefail
cd "$(dirname "$0")/.."
DIR="${1:-backups}"
KEEP="${KEEP_BACKUPS:-14}"
mkdir -p "$DIR"
chmod 700 "$DIR"
FILE="$DIR/placcric-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > "$FILE.partial"
mv "$FILE.partial" "$FILE"
chmod 600 "$FILE"
echo "Backup written: $FILE ($(du -h "$FILE" | cut -f1))"
ls -1t "$DIR"/placcric-*.dump 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r old; do rm -- "$old"; done
