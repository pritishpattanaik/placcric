# Architecture

Status: describes the code as of Milestone 1. Planned components are marked as such.

## Overview

```
browser (web/index.html, app.js, styles.css)
   │  same-origin fetch, JSON, session cookie + X-CSRF-Token
   ▼
server.py ── uvicorn on 127.0.0.1:PORT
   ▼
app/main.py        FastAPI factory: Host allowlist, security headers, {"error": …} responses,
                   static files, /healthz, /readyz
app/api/routes.py  JSON API (/api/…)
app/api/security.py  JSON body guard (2 MB, application/json, Origin check), session, CSRF
app/auth/pin.py    interim PIN auth (removed in M2; Google OIDC planned in app/auth/)
app/analytics.py   aggregates, profiles, match views, deterministic coaching
app/matchup.py     Captain's room team-against-team report, dismissal parsing
app/ai/            optional OpenRouter analysis: evidence.py (server-built packs), openrouter.py (cache, cap, log)
app/ingestion/  records.py (provider-neutral records, rule checks, publish + revisions, diffs)
                 cricheroes_pdf.py (scorecard PDF reader) · staging.py (upload → preview → approve)
                 scorecards.py (JSON bundles, bundled tournament, seed)
   ▼
PostgreSQL  ◄── migrations/ (Alembic; the only way the schema is created or changed)
```

Supporting modules: `app/config.py` (environment and `.env`), `app/db.py` (engine, Alembic revision checks), `app/models.py` (SQLAlchemy models mirroring the migrations), `app/cli.py` (explicit admin commands), `app/sqlite_migration.py` (one-time legacy import).

## Design decisions

- **FastAPI + SQLAlchemy 2 Core queries.** Models define the schema for Alembic and documentation; analytics use parameterised SQL through SQLAlchemy `text()` so the proven SQLite-era calculations were ported unchanged. A parity check compared 173 API responses between the SQLite and PostgreSQL versions with no differences.
- **Byte-order collation.** Name ordering uses `COLLATE "C"` to match the SQLite behaviour exactly, independent of the server's locale.
- **Integer legal balls.** Overs are converted from cricket notation (`22.3` → 135) on import and formatted back only for display.
- **Provider IDs as primary keys.** Match and player IDs are the source provider's IDs (currently CricHeroes) and never change when names change. A `provider` column (default `cricheroes`) prepares for provider-neutral ingestion in M3.
- **No implicit writes at startup.** `server.py` checks the Alembic revision and refuses to start when out of date; it never seeds or migrates. The only startup write is the interactive first-PIN prompt, which disappears in M2.
- **Atomic imports.** Validation is pure and completes before any write; writes happen inside one transaction (`engine.begin()`).
- **Synchronous routes.** Route functions are plain `def`, so FastAPI runs them in its thread pool with the synchronous psycopg 3 driver.

## Schema (migration 0001)

| Table | Key | Notes |
| --- | --- | --- |
| `teams` | `id` | unique name |
| `roster_entries` | `(team_id, name)` | public club listings, not squads |
| `players` | `id` (provider ID) | `provider` |
| `matches` | `id` (provider ID) | teams, winner (must be a participant), result, toss, player of the match, `dls`, `warning`, `source_url`, `retrieved_at` as supplied |
| `innings` | `(match_id, number)` | runs, wickets (0–10), balls, extras; cascades from match |
| `batting` / `bowling` | `(match_id, innings_number, player_id)` | integer balls; non-negative checks; dots ≤ balls |
| `notes` | `team_id` | captain notes, `updated_at` timestamptz |
| `import_log` | `id` | time, match count, source, SHA-256 content hash |
| `pin_credentials`, `auth_sessions`, `login_attempts` | | interim auth; dropped in M2 |
| `tournaments` (0002) | `id` | provider + external ID, name, link slug, overs per innings, max overs per bowler |
| `matches.tournament_id`, `matches.stage` (0002) | | every match belongs to one tournament; stage as given by the source |
| `import_batches` (0002) | `id` | uploaded file metadata, private raw file name (SHA-256), parsed records (JSONB), status staged/approved/rejected, reviewer |
| `match_revisions` (0002) | `(match_id, number)` | every published version of a match as JSONB with a score hash; the scorecard tables hold the latest |
| `player_aliases` (0002) | `(team_id, alias_key)` | admin-confirmed scorecard names → player |
| `tournaments.kind` (0003) | | `tournament` or `friendly`; migration creates the "Friendly Match" category |
| `ai_requests` (0003) | `id` | AI request log and cache: time, kind, subject, model, cache key, status, token counts, answer, error (never the key) |

## Import flow

```
upload (PDF ≤10 MB / JSON ≤2 MB, admin + CSRF)
  → raw file stored privately as uploads/<sha256>.<ext> (0600)
  → parse: cricheroes_pdf.parse() or scorecards.bundle_to_records() → records (names, maybe no IDs)
  → import_batches row (status staged)
preview (computed on demand): check_record() against the tournament's rules, identities() per team,
  diff() against the published match, unchanged/new/correction
approve (one transaction, row lock): apply identity decisions (link / new player / CricHeroes ID),
  store aliases, re-check with IDs, publish() changed records + revision, import_log, status approved
restore: publish an old revision's content as a new revision
```

Player identity is never inferred from names: aliases exist only after an admin approves them, and they are scoped to a team.

## AI boundary

AI calls are made only from `POST /api/ai/analyze` (session + CSRF), after a user click. The server builds the evidence from the database; the browser sends only IDs of the teams/players to analyse and an optional question. The key stays server-side (environment only). See docs/AI.md.

## Security boundary

Loopback binding by default; exact Host allowlist (default `localhost:PORT`, `127.0.0.1:PORT`; set with `PLACCRIC_ALLOWED_HOSTS`); CSP without inline scripts; `Cache-Control: no-store`; frame denial; JSON-only POST bodies up to 2 MB with Origin checking; CSRF token on every authenticated POST; session cookies HttpOnly + SameSite=Strict (Secure by default when `PLACCRIC_ENV=production`, overridable with `PLACCRIC_COOKIE_SECURE`); `X-Forwarded-*` trusted only from `PLACCRIC_FORWARDED_ALLOW_IPS`. Database passwords are redacted in all CLI and server output.

## Containers and environments

`compose.yaml` defines `db` (postgres:16-bookworm, named volume `pgdata`, published on 127.0.0.1), `app` (built from `Dockerfile`: python:3.12-slim, non-root user, healthcheck on `/healthz`, published on 127.0.0.1), optional `caddy` (profile `https`, automatic Let's Encrypt, the only service on 0.0.0.0) and a `test` profile with an in-memory PostgreSQL. Settings come from `.env`: `PLACCRIC_HOST`, `PLACCRIC_PORT`, `PLACCRIC_ALLOWED_HOSTS`, `PLACCRIC_FORWARDED_ALLOW_IPS` (uvicorn proxy headers, so HTTPS Origin checks and per-client throttling work behind Caddy) and `PLACCRIC_COOKIE_SECURE`. `/healthz` reports the deployed commit (`PLACCRIC_VERSION`, baked in at build time) and is exempt from the Host check for probes. Migrations run as an explicit deploy step (`scripts/deploy.sh`), never from the server process. See docs/DEPLOYMENT.md.

## Planned

- `app/auth/oidc.py` and role/allowlist tables (M2).
- CSV templates, points table, storage of PDF extras (maidens, fall of wickets) (M3 remainder).
- Remaining M5 items: manual acceptance checklist, restore drills, monitoring.
