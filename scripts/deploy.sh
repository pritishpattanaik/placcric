#!/usr/bin/env bash
# Build and (re)deploy PlacCric with docker compose from a git branch.
#   Stage (MacBook):     scripts/deploy.sh main
#   Production (server): scripts/deploy.sh production
# Steps: fast-forward the branch, build the image, back up, apply migrations, restart, check readiness.
# It never seeds data; run `docker compose run --rm app python -m app.cli seed` once yourself if needed.
set -euo pipefail
cd "$(dirname "$0")/.."
BRANCH="${1:?Usage: scripts/deploy.sh <branch>   e.g. main (stage) or production}"

[ -f .env ] || { echo ".env is missing. Copy .env.example (or deploy/env.production.example) and fill it in." >&2; exit 1; }
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Uncommitted changes in $(pwd); commit or stash them before deploying." >&2; exit 1
fi

echo "==> Updating $BRANCH"
git fetch origin "$BRANCH"
git checkout -q "$BRANCH"
git merge --ff-only "origin/$BRANCH"
VERSION="$(git rev-parse --short HEAD)"

echo "==> Building image $VERSION"
PLACCRIC_VERSION="$VERSION" docker compose build app
docker tag placcric-app:latest "placcric-app:$VERSION"

echo "==> Starting database"
docker compose up -d --wait db

echo "==> Backing up before migrating"
scripts/backup.sh

echo "==> Applying migrations"
docker compose run --rm --no-deps app python -m app.cli db-upgrade

PIN_ROWS="$(docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT count(*) FROM pin_credentials"')"
if [ "$PIN_ROWS" = "0" ]; then
  echo "==> No PIN configured yet; set one now (6-12 digits)"
  docker compose run --rm --no-deps app python -m app.cli set-pin
fi

echo "==> Starting services"
docker compose up -d --wait --remove-orphans

echo "==> Checking readiness"
docker compose exec -T app python -c "import json,urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=5)))"
docker compose exec -T app python -c "import json,urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=5)))"

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $BRANCH $VERSION" >> deploy-history.log
echo "==> Deployed $VERSION from $BRANCH. Previous deploys: deploy-history.log"
