# PlacCric

A cricket analytics dashboard for the **Diwhyn Choice T25 Cricket Carnival — Season 2** (CricHeroes tournament 2194193), with UCC club views, player profiles, match scorecards, comparisons and captain notes.

Repository: https://github.com/pritishpattanaik/placcric

## Status

PlacCric is a Python backend (FastAPI, SQLAlchemy 2, Alembic) using **PostgreSQL**, plus the existing plain HTML/CSS/JavaScript UI. It runs in Docker Compose (recommended) or a Python virtual environment. It is not deployed publicly. Milestones are tracked in [docs/ROADMAP.md](docs/ROADMAP.md).

| Implemented now | Planned (not yet implemented) |
| --- | --- |
| PostgreSQL persistence with versioned Alembic migrations (M1) | Google OpenID Connect sign-in, invite allowlist and roles (M2) |
| Explicit, idempotent seed command; startup never seeds or resets data (M1) | Documented CSV templates for scorer-supplied records |
| One-time, verified SQLite → PostgreSQL migration with dry run (M1) | Points table (needs your competition rules for ties, NRR and DLS) |
| **Several tournaments** with their own overs limits (e.g. T25 and T20), and a tournament filter | Admin/captain/player roles (M2); today the PIN user is the admin |
| **Staged imports**: upload → preview (totals, checks, changes, player identities) → approve or reject | Storing maidens, fall of wickets and minutes from PDFs (read but not stored yet) |
| **CricHeroes scorecard PDF reader** (the “Download Scorecard” file) and scorecard JSON | UI accessibility/mobile regression testing beyond the checks listed in the PR (M4) |
| Match revisions with restore; identical re-imports change nothing | |
| Dashboard, match centre, player profiles, team filters, comparison, captain notes | Production configuration, HTTPS, trusted hosts and backup tooling (M5) |
| Deterministic, evidence-based coaching rules | CricHeroes adapter — blocked until an authorised export or integration is confirmed |
| **Friendly Match** category for one-off matches between any teams | |
| **Captain's room team-against-team report**: records, run rates, head to head, threats, how wickets fall, who dismissed whom | |
| **Optional AI analysis via OpenRouter** (match plan, scouting report, player comparison, coach answers) with daily cap, cache and request log — see [docs/AI.md](docs/AI.md) | |
| **Interim** single-user PIN login (hashed PIN, server sessions, CSRF, throttling) | PIN login is removed when Google sign-in lands in M2 |
| Health (`/healthz`) and readiness (`/readyz`) endpoints | |
| Docker Compose stack (PostgreSQL 16, app, optional Caddy HTTPS), deploy/backup/restore scripts, GitHub Actions CI | Public internet exposure — only after M2 replaces the PIN |

**Data coverage:** the bundled snapshot contains five completed matches and 15 public club listings, collected on 7 October 2026. It is not a live feed or a complete season. Club listings are not confirmed tournament squads. Scorecard identities use CricHeroes player IDs; names in club listings are never merged with them automatically.

The bundled source has recorded discrepancies, including a KL Stars innings total, a DLS match and an unusual batting list. Their warnings stay visible in the UI. Import validation checks numerical consistency, not authenticity. Review the original sources before consequential selection decisions.

Tournament source: https://cricheroes.com/tournament/2194193/diwhyn-choice-t25-cricket-carnival-season-2/matches/past-matches

## Run with Docker Compose (recommended)

Needs Docker with Compose v2 (OrbStack or Docker Desktop on a Mac; Docker Engine on Linux). All configuration is in `.env`.

```bash
git clone https://github.com/pritishpattanaik/placcric.git && cd placcric
cp .env.example .env
sed -i '' "s/CHANGE_ME/$(openssl rand -hex 24)/g" .env   # on Linux: sed -i "s/…/…/g" .env
scripts/deploy.sh main                                   # build, migrate, set PIN, start
docker compose run --rm app python -m app.cli seed       # first time only: bundled snapshot
```

Open http://localhost:8000. The dev → stage (MacBook) → prod (Contabo) workflow, branch model, server setup, HTTPS, backups and rollback are in **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**.

## Alternative: run on a Mac without Docker (venv)

Requirements:

- **Python 3.10 or newer** (`python3 --version`).
- **PostgreSQL 16** (tested with 16.x). Other supported PostgreSQL major versions are expected to work but are not tested.

### 1. Install and start PostgreSQL with Homebrew

```bash
brew install postgresql@16
brew services start postgresql@16
# Homebrew does not link versioned formulae; add its tools to PATH (Apple silicon path shown):
echo 'export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"' >> ~/.zprofile
source ~/.zprofile
psql --version
```

On Intel Macs the prefix is `/usr/local/opt/postgresql@16/bin`. [Postgres.app](https://postgresapp.com/) also works; use its PostgreSQL 16 server and add its `bin` directory to `PATH`.

### 2. Create a role, the application database and a separate test database

Choose your own password; do not reuse it elsewhere.

```bash
createuser --pwprompt placcric          # enter a new password when prompted
createdb --owner placcric placcric
createdb --owner placcric placcric_test # disposable; tests drop and recreate its schema
```

### 3. Install the Python dependencies

```bash
git clone https://github.com/pritishpattanaik/placcric.git
cd placcric
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run `source .venv/bin/activate` in each new Terminal window before the commands below.

### 4. Configure the database URL

```bash
cp .env.example .env
```

Edit `.env` and replace `CHANGE_ME` with your password. `.env` is ignored by git; never commit it. Real environment variables take precedence over `.env`. If your password contains `@`, `:`, `/` or `%`, URL-encode it (for example `@` becomes `%40`).

### 5. Create the schema and load the bundled data (explicit, one time)

```bash
python3 -m app.cli db-upgrade   # apply migrations
python3 -m app.cli seed         # load bundled club listings and the five-match snapshot
```

`seed` is idempotent: running it again adds nothing and never overwrites a match that already exists (so later corrections survive). The server never runs migrations or seeding on startup.

If you are upgrading from the SQLite version, **skip `seed`** and follow [Migrating from SQLite](#migrating-from-the-sqlite-version) instead.

### 6. Run on port 8000

```bash
python3 server.py --port 8000
```

On first launch you will be asked to create a **6–12 digit PIN** in Terminal (interim login; see below). Open http://localhost:8000. Stop with `Ctrl+C`. The server binds only to `127.0.0.1`.

Reset the interim PIN (revokes existing sessions): `python3 server.py --reset-pin` or `python3 -m app.cli set-pin`.

If the server reports that the schema needs migrating, run `python3 -m app.cli db-upgrade`. If it cannot connect, check that PostgreSQL is running (`brew services list`) and that `DATABASE_URL` is correct. Passwords are never printed.

## Commands

| Command | Purpose |
| --- | --- |
| `python3 server.py --port 8000` | Run the local app on http://localhost:8000 |
| `python3 -m app.cli db-upgrade` | Apply Alembic migrations (same as `alembic upgrade head`) |
| `python3 -m app.cli db-status` | Show current and latest schema revision; exit code 1 if a migration is needed |
| `python3 -m app.cli db-downgrade REVISION --yes` | Roll the schema back (e.g. `base`). **Drops tables and their data** — back up first |
| `python3 -m app.cli seed` | Idempotently load bundled data |
| `python3 -m app.cli migrate-sqlite PATH [--dry-run]` | One-time SQLite → PostgreSQL copy |
| `python3 -m app.cli set-pin` | Set the interim PIN |

## Migrating from the SQLite version

Earlier versions stored data in `data/placcric.sqlite3`. The migration command copies it into PostgreSQL once.

What it does:

- Opens the SQLite file **read-only** and checks its SHA-256 before and after; the original file is not modified.
- Copies teams, club listings, players (with CricHeroes IDs), matches, innings, batting, bowling, captain notes and import history, **preserving every ID**.
- Does **not** copy the PIN hash, sessions, login attempts or internal `meta` rows. You set a new PIN afterwards.
- Requires a freshly upgraded, **unseeded** PostgreSQL database, and refuses to run if any cricket data is already present (so it cannot be run twice).
- Runs in a single transaction. Before committing it compares row counts, aggregate totals (runs, balls, wickets, extras, boundaries, dots, wides, no-balls, not-outs) and a content digest of every table. Any mismatch rolls everything back.

Steps:

```bash
# 1. Stop the old server (Ctrl+C) so the SQLite file is not changing.
# 2. Keep a copy of the old database and its -wal/-shm files somewhere private, outside git.
mkdir -p ~/placcric-backups
cp data/placcric.sqlite3* ~/placcric-backups/
# 3. Create the schema, but do NOT run seed.
python3 -m app.cli db-upgrade
# 4. Verify without writing anything.
python3 -m app.cli migrate-sqlite data/placcric.sqlite3 --dry-run
# 5. Migrate for real; the report lists counts and totals per table.
python3 -m app.cli migrate-sqlite data/placcric.sqlite3
# 6. Set a new PIN and start the server.
python3 server.py --port 8000
```

**Recovery.** The SQLite file is left as it was, so you can always start again:

- If the dry run or migration reports an error, nothing was written. Fix the reported problem and re-run.
- If you want to redo a committed migration, recreate the PostgreSQL database and repeat steps 3–5:
  ```bash
  dropdb placcric && createdb --owner placcric placcric
  python3 -m app.cli db-upgrade
  python3 -m app.cli migrate-sqlite data/placcric.sqlite3
  ```
- To return to the old SQLite app temporarily, check out the last SQLite commit (`511a876`) in a separate directory and run it against your untouched `data/placcric.sqlite3`.

## Backup and restore (PostgreSQL)

Backups contain captain notes and, until M2, the PIN hash and session digests. Keep them private and outside the repository. Uploaded scorecard files are not in the database: back up the `uploads/` folder too (with Docker, see docs/DEPLOYMENT.md).

```bash
mkdir -p ~/placcric-backups
pg_dump --format=custom --file ~/placcric-backups/placcric-$(date +%Y%m%d-%H%M).dump placcric
```

Restore into an empty database (stop the server first):

```bash
dropdb placcric && createdb --owner placcric placcric
pg_restore --no-owner --role=placcric --dbname placcric ~/placcric-backups/placcric-YYYYMMDD-HHMM.dump
python3 -m app.cli db-status
```

Test a restore into a scratch database (`createdb placcric_restore_check`) occasionally to confirm your backups work.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full description.

- `server.py` — local launcher (uvicorn on 127.0.0.1); checks the schema revision and refuses to start if a migration is needed.
- `app/main.py` — FastAPI app factory, host allowlist, security headers, error format, static files, health/readiness.
- `app/api/` — JSON API routes and request guards (JSON size limit, origin check, session and CSRF).
- `app/auth/pin.py` — interim PIN authentication (removed in M2).
- `app/models.py` — SQLAlchemy models; `migrations/` — Alembic migrations (the only way the schema is created).
- `app/ingestion/records.py` — provider-neutral match records: checks against tournament rules, publishing with revisions, diffs.
- `app/ingestion/cricheroes_pdf.py` — reader for CricHeroes “Download Scorecard” PDFs (pypdf, no OCR).
- `app/ingestion/staging.py` — upload → preview → approve/reject, player identity decisions, restore.
- `app/ingestion/scorecards.py` — JSON bundle format, bundled tournament and idempotent seed.
- `app/analytics.py` — aggregates, profiles, match views and deterministic coaching rules.
- `app/matchup.py` — Captain's room team-against-team report and dismissal parsing.
- `app/ai/` — optional OpenRouter analysis: server-built evidence packs, cache, daily cap, request log.
- `app/sqlite_migration.py` — one-time SQLite import with verification.
- `app/config.py` — environment configuration (`DATABASE_URL`, `PLACCRIC_ENV`), optional `.env` loading, password redaction.
- `app/cli.py` — explicit administration commands.
- `web/` — browser UI; no CDN or external fonts.
- `data/scorecards.json` — bundled snapshot and an example of the import format; `data/rosters.json` — public club listings.
- `tests/` — validation, PostgreSQL integration, HTTP and migration tests.
- `Dockerfile`, `compose.yaml`, `deploy/` (Caddyfile, production env template), `scripts/` (deploy, backup, restore), `.github/workflows/ci.yml`.

### Authentication (interim) and deployment boundary

Until Milestone 2, sign-in uses a single workspace PIN: salted PBKDF2-SHA256 hash, random session tokens stored only as SHA-256 digests, 12-hour expiry, CSRF token on every state-changing request, login throttling (8 attempts per 15 minutes per client), and an HttpOnly, SameSite=Strict cookie. Requests with a Host header other than `localhost:PORT` or `127.0.0.1:PORT` are rejected.

By default the server binds to `127.0.0.1`; in containers it binds inside the container and is published on `127.0.0.1` only. Bind address, allowed hosts, proxy trust and cookie security come from environment variables (see `.env.example`). **Do not expose the PIN-protected app to the internet**: run production privately (SSH tunnel) until Google sign-in with roles (M2) is merged. A cloud coding session does not host the app or connect to your Mac's localhost.

`PLACCRIC_PIN` exists for isolated automated runs. Do not commit a real PIN, `.env`, session, database dump or backup.

## Match data without frequent crawling

**No scheduled crawler, no polling and no CricHeroes requests during dashboard use.** All analytics read the local PostgreSQL database.

### Importing a match from a CricHeroes PDF

1. When a match is **completed**, open its scorecard on CricHeroes and use **Download Scorecard**. You get `Scorecard_<matchid>.pdf`.
2. In PlacCric open **Data & imports**. If the tournament is new, use **Add a tournament** (name, CricHeroes tournament ID, overs per innings, max overs per bowler).
3. Under **Upload a scorecard**, choose the PDF and the tournament. The match ID is filled in from the file name; optionally paste the scorecard link. Click **Upload & review**.
4. The **review** page shows the match, both innings, every check and any warnings (for example a batter missing from the listed squad). Nothing is published yet.
5. **Players**: the PDF has names but no CricHeroes IDs. Names you confirmed before are recognised automatically (per team). New names default to *New player*. When a similar existing player is found (for example the same name at another club), you must choose: *Same as …* or *New player*. You can also type a player's CricHeroes ID.
6. Click **Approve & publish** (or **Reject**). Approval publishes in one transaction and records a revision.
7. To correct a match, upload the corrected file: the review lists each changed field. Uploading the same scores again changes nothing. Each match page has a **Revision history** with **Restore**.

The original files are kept privately on the server (in `uploads/`, or the `uploads` Docker volume) under their SHA-256 name with owner-only permissions. They are never served or committed.

JSON bundles in the format below go through the same review and approval.

You have CricHeroes Pro. No official documentation reviewed shows an API or bulk export; the per-match PDF is the confirmed export. See [docs/DATA_INGESTION.md](docs/DATA_INGESTION.md#cricheroes-pro-what-is-confirmed).

### Current JSON import contract

Use `data/scorecards.json` as the executable example. A bundle contains a `matches` array of 1–100 matches and an optional `retrieved_at`. Each match contains a numeric string `id`, `source_url`, ISO date, venue, two ordered teams, winner, result and two innings. Batting rows use player ID/name, runs, balls, fours, sixes, dismissal and a not-out flag. Bowling rows use player ID/name, overs, runs, wickets, dots, wides and no-balls.

Current restrictions: if a source link is given it must be this match's CricHeroes scorecard (and the tournament's link name, when set); exactly two innings; a winner matching one team; the tournament's overs per innings and per bowler. **Ties, no-results, super overs, other providers and other competition rules are not supported** and are rejected rather than forced into a misleading winner record.

Overs use cricket notation: `22.3` means 135 balls, not 22.3 decimal overs. Internally overs are stored as integer legal balls. Batting runs plus extras, and bowling legal balls, must reconcile with innings totals (errors block approval). Extras breakdowns, bowler runs versus byes/leg byes, and dismissals versus wickets are checked as warnings. Failed validation leaves stored scores unchanged.

### Friendly matches

One-off matches between any teams go in the built-in **Friendly Match** category (created by migration 0003 and by `seed`). Upload their scorecard PDFs exactly like tournament matches, choosing "Friendly Match (friendlies)". Overs limits are the widest allowed (50/50) because friendlies vary; the totals must still reconcile. Use the Tournament filter to see friendlies on their own; "All tournaments" includes them.

### Captain's room and AI

Choose your team and the opposition. PlacCric compares them from the imported scorecards in the current Tournament filter: matches, wins batting first and chasing, average and highest scores, run rates, economy, recent form, head-to-head results, top batters and bowlers on both sides, how each side's batters get out and how their bowlers take wickets, and who dismissed whom in their meetings (read from the dismissal text). Sample-size warnings and data limits are always shown.

Optionally add an OpenRouter key to get an **AI match plan** here, an **AI scouting report** on player profiles, an **AI comparison** on Compare players and AI answers in the coach. Setup, cost controls and exactly what is sent are in [docs/AI.md](docs/AI.md).

### Statistical scope

All aggregates cover imported matches and the active tournament and team filters. Batting average is runs divided by dismissals; with zero dismissals it is undefined and shown as a dash. Strike rate is runs per 100 balls. Bowling economy is runs conceded per six legal balls. Zero-ball, zero-run not-out listings do not count as batting innings. No ball-by-ball data exists, so phase splits, wagon wheels, pace/spin analysis and predictive win probabilities are not shown. DLS results are not used to infer a standard NRR table.

## Tests

The integration tests need a **separate PostgreSQL test database** whose name ends in `_test`; they drop and recreate its schema. SQLite is not used as a substitute. Set `TEST_DATABASE_URL` in `.env` (see `.env.example`), then:

```bash
python3 -m unittest discover -s tests -v
node --check web/app.js   # if Node is installed
```

Or, with Docker only (uses a throwaway in-memory PostgreSQL, never your data):

```bash
docker compose --profile test run --rm --build tests
```

Without `TEST_DATABASE_URL` the PostgreSQL tests are reported as skipped; set `PLACCRIC_REQUIRE_PG=1` to make that an error. The tests refuse to run against a database whose name does not end in `_test` or that matches `DATABASE_URL`.

PDF tests use a synthetic scorecard with invented players (`tests/pdf_fixture.py`). Real downloads contain third-party personal data, so they are not committed; to check one locally run `PLACCRIC_REAL_SCORECARD_PDF=/path/Scorecard_123.pdf python3 -m unittest tests.test_pdf`.

## Develop with Claude Code in the cloud

See [docs/CLAUDE_CLOUD.md](docs/CLAUDE_CLOUD.md) and [docs/ROADMAP.md](docs/ROADMAP.md). Cloud sessions work from repository content, not from files only on your Mac. Official guide: https://code.claude.com/docs/en/claude-code-on-the-web

## Attribution and licensing

PlacCric is independent of CricHeroes and is not an official CricHeroes product. Imported data keeps its source links. No licence to redistribute third-party match data is implied. The repository owner should choose a code licence and review data-sharing permissions before public redistribution.
