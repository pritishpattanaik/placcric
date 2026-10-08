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
app/ingestion/scorecards.py  validation, atomic import, idempotent seed
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

## Security boundary

Loopback binding; exact Host allowlist (`localhost:PORT`, `127.0.0.1:PORT`); CSP without inline scripts; `Cache-Control: no-store`; frame denial; JSON-only POST bodies up to 2 MB with Origin checking; CSRF token on every authenticated POST; session cookies HttpOnly + SameSite=Strict (Secure when `PLACCRIC_ENV=production`). Database passwords are redacted in all CLI and server output.

## Planned

- `app/auth/oidc.py` and role/allowlist tables (M2).
- Staging, revisions and private raw-upload storage under `app/ingestion/` (M3).
- Production settings: trusted hosts, HTTPS, proxy headers (M5).
