# PlacCric coding instructions

Read README.md, docs/ARCHITECTURE.md, docs/DATA_INGESTION.md and docs/ROADMAP.md before changes. Inspect the actual checkout: the docs describe what is implemented, and the roadmap separates that from planned work. Do not assume a deployed product.

## Goal

Improve a cricket analytics app for tournament 2194193, with UCC club views. Prioritise reliable match imports, understandable statistics, mobile usability and persistent data. Pritish Pattanaik's CricHeroes player ID is 32722355; do not infer identity from a matching name.

## Current requirements (supersede the earlier SQLite/PIN-only constraints)

- Backend: Python 3.10+, FastAPI, SQLAlchemy 2, Alembic, **PostgreSQL** (tested with 16). SQLite is only a one-time migration source.
- Authentication target: **Google OpenID Connect** with invite/allowlist access and admin/captain/player roles (Milestone 2). The PIN login is interim, documented, and must be removed in M2; never add an undocumented PIN bypass.
- Local development stays on http://localhost:8000. Docker Compose (`compose.yaml`) is the standard way to run stage and production; running in a venv with `python3 server.py --port 8000` must keep working too.
- Environments: dev = Claude cloud on `claude/*` branches → PR into `main`; stage = owner's MacBook (OrbStack) on `main`; prod = Contabo VM on `production`. Never push to `main` or `production` directly. See docs/DEPLOYMENT.md.
- Keep the existing HTML/CSS/JavaScript UI and improve it incrementally; no frontend rewrite.
- No frequent CricHeroes crawling, scheduled scraping, background polling or network access triggered by viewing the dashboard.
- The owner has CricHeroes Pro. Do not assume it includes API or export rights. Do not invent provider endpoints, reverse-engineer private APIs, bypass access controls or ask for CricHeroes passwords. Prefer organiser/scorer-supplied files.
- No paid services, autonomous crawlers or unrelated rewrites without a concrete requirement. No automatic deployment: the owner runs `scripts/deploy.sh` on each machine.

## Constraints

- Configuration comes from environment variables, optionally a local `.env` (see `.env.example` and `deploy/env.production.example`, placeholders only). Pin image major versions in `compose.yaml`/`Dockerfile`.
- Schema changes only through new Alembic migrations, each with a working downgrade and test coverage. Never edit an applied migration.
- The server must never migrate, seed or reset the database on startup. Seeding is the explicit, idempotent `python3 -m app.cli seed`.
- Never fabricate statistics or source capabilities, or mark OCR/model output verified without human review. Distinguish snapshots, club lists and tournament squads.
- Store cricket overs as integer legal balls. Preserve source IDs, source URLs, source timestamps, warnings and small-sample caveats. IDs must not be reassigned because names changed.
- Preserve hashed secrets, session expiry, CSRF checks, login throttling, the Host allowlist and parameterised SQL. Default to loopback binding; containers publish ports on 127.0.0.1 only, with public traffic only through the Caddy HTTPS profile. Do not recommend public exposure while PIN login remains. Never hardcode a usable production secret or PIN.
- Keep Google client secrets and tokens out of browser code, git, logs and error messages. Never print database passwords (use `redact_url`).
- Never commit runtime databases, `.env`, secrets, auth sessions, dumps, backups or private uploaded scorecards. Public fixtures need a deliberate provenance/permission review.
- Coaching is deterministic. Do not describe it as an LLM. Optional AI work is a separate milestone and must declare provider, cost limits and which personal data is sent.

## Workflow

1. Inspect code and current tests. Work on one roadmap milestone per branch/PR.
2. Implement a complete vertical slice with clear validation and error messages.
3. Add meaningful tests. Integration tests use the isolated PostgreSQL database in `TEST_DATABASE_URL` (name must end in `_test`); never a user's database and never SQLite as a substitute. Mock external providers; never contact real Google or CricHeroes accounts in tests.
4. Run `python3 -m unittest discover -s tests -v` with `TEST_DATABASE_URL` set (use `PLACCRIC_REQUIRE_PG=1` so skips fail), or `docker compose --profile test run --rm --build tests`. Run `node --check web/app.js` when Node is available. CI must be green before merge.
5. For UI changes, test narrow/wide layouts, keyboard navigation, contrast, loading/error/empty states and permission-dependent controls. Report unavailable browser checks honestly.
6. Update README, CLAUDE.md, docs/ARCHITECTURE.md and docs/ROADMAP.md for implemented behaviour. Open a PR describing behaviour, validation and limitations, and any configuration the owner must supply. If credentials are unavailable, mark live-provider checks pending; never claim they passed. Do not merge or deploy automatically.

## Data integrity

Imports are staged and published only on admin approval (app/ingestion/staging.py). Every match belongs to a tournament whose overs limits are enforced; only completed two-innings matches with a winner are supported. Extend the schema deliberately for ties/no-results/super overs. CricHeroes scorecard PDFs carry names, not player IDs: identities come only from admin-confirmed, team-scoped aliases; suggestions never merge automatically. Never commit real scorecard PDFs; tests use tests/pdf_fixture.py. Reimports must not duplicate statistics. Validation runs before writes, and writes are atomic. Club roster listings stay separate from confirmed squads. Link Google accounts to players only through an explicit admin-approved mapping, never by name.

Current milestone status and the next task are in docs/ROADMAP.md.
