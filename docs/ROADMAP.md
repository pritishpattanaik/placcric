# Delivery milestones

One milestone per branch and pull request. Each PR reports changes, test results, remaining limitations and any configuration the owner must supply. Keep README status accurate. Nothing is merged or deployed automatically.

| Milestone | Status |
| --- | --- |
| M1 — PostgreSQL | **Implemented** (pending review) |
| M2 — Google login and access control | Planned; needs Google OAuth client credentials from the owner for the live check |
| M3 — Reliable match ingestion | **Core implemented** (pending review): tournaments, staged PDF/JSON imports, identity review, revisions/restore. CSV templates and points table remain |
| CricHeroes adapter | **PDF adapter implemented** for the per-match “Download Scorecard” file. No API/bulk export confirmed; automated fetching not built (robots.txt/terms unchecked) |
| M4 — UI and analytics | Planned |
| M5 — Release readiness | Partly delivered early: Docker Compose stack, dev/stage/prod workflow, deploy/backup/restore scripts, CI, HTTPS profile, health/readiness. Public exposure waits for M2 |
| Optional LLM coaching | Future, separate; explicit cost and privacy controls required |

## Baseline (before M1)

Working: a standard-library Python server with SQLite, single PIN login (PBKDF2 hash, hashed session tokens, CSRF, throttling, loopback binding), validated atomic JSON imports, dashboard/match centre/profiles/team filters/comparison/captain notes, deterministic coaching and six tests.

Gaps: no migrations; startup seeded the database implicitly; no multi-user identity or roles; imports wrote immediately with no staging, approval, revisions or raw-file provenance; no CSV contract; ties/no-results unsupported; UI not regression-tested on mobile or with keyboards.

## M1 — PostgreSQL (implemented)

Delivered:

- FastAPI + SQLAlchemy 2 + Alembic backend with PostgreSQL; routes, auth, models, ingestion, analytics and configuration in separate modules. API responses identical to the SQLite version for every endpoint.
- Migration `0001` creating teams, club listings, players (provider IDs), matches, innings, batting, bowling, notes, import history and interim auth tables, with check constraints. Overs stored as integer legal balls.
- Explicit idempotent `seed`; the server never migrates or seeds, and refuses to start if the schema is out of date.
- `migrate-sqlite` with dry run: read-only source, preserved IDs, no PIN/session/login-attempt data, count/aggregate/digest verification inside one transaction, documented recovery.
- `DATABASE_URL` configuration, `.env.example`, macOS PostgreSQL 16 setup, backup/restore, `/healthz` and `/readyz`.
- Tests against an isolated PostgreSQL test database: migrations up/down and model parity, constraints, seed idempotency, analytics, atomic imports, HTTP auth/CSRF/guards, and SQLite migration.

Acceptance criteria: all tests pass with `TEST_DATABASE_URL` set; `python3 server.py --port 8000` serves the existing UI from PostgreSQL; the migration of a legacy database reports matching counts and totals and leaves the SQLite file's hash unchanged.

Follow-up delivered on the same PR: Docker Compose deployment (PostgreSQL 16, app, optional Caddy HTTPS), environment-driven server settings, `scripts/deploy.sh|backup.sh|restore.sh`, GitHub Actions CI and docs/DEPLOYMENT.md.

Limitations: authentication is still the interim single PIN; import staging and revisions are M3; the coverage date shown in the UI is still the fixed snapshot date.

## M2 — Google login and access control

- Google OpenID Connect via a maintained library (Authlib planned), server-side authorization-code flow with state, nonce and PKCE.
- Validate issuer, audience, expiry and nonce; require `email_verified`; identify accounts by Google `sub`, not email.
- Opaque server-side sessions, rotated at login, with expiry, logout and revocation; CSRF retained. HttpOnly cookies, SameSite=Lax for the OAuth redirect, Secure under HTTPS; local HTTP only with an explicit development setting.
- Remove PIN login entirely (migration drops the PIN tables).
- Invite/allowlist access: signing in with an unlisted Google account grants nothing.
- Roles enforced on the backend with team scope: admin (manage access, approve imports and corrections), captain (authorised club data and club notes), player (permitted analytics).
- Google account ↔ cricket player links only via explicit admin-approved mapping; never by name.
- First admin bootstrapped from explicit configuration, never "first login wins".
- Docs: Google Cloud consent screen, client credentials and exact callback URLs (`http://localhost:8000/auth/callback` locally; the production HTTPS equivalent).
- Mocked-provider tests: success, invalid state, invalid nonce, denied consent, unverified email, unknown account, session expiry. No real Google accounts in automated tests.

Acceptance: no private data reachable without an allowlisted, verified Google identity; each role's permissions are tested; live Google sign-in marked pending until the owner supplies credentials and confirms it.

## M3 — Reliable match ingestion

### Delivered (migration 0002)

- `tournaments` with per-tournament overs per innings and per bowler; matches belong to a tournament and keep the source's stage name (e.g. "Semi Final"). Existing matches are assigned to tournament 2194193 by the migration. Analytics and the UI have a tournament filter.
- Staged imports (`import_batches`): upload a CricHeroes scorecard PDF or JSON bundle → private raw file (SHA-256 name, mode 0600, size limits 10 MB/2 MB) → preview with source, match IDs, innings totals, errors, warnings, field-level changes, and player identities → admin approve or reject. Nothing is published before approval; approval is one transaction.
- CricHeroes PDF reader: deterministic text-layer parsing (pypdf), every row reconciled; unreadable rows are errors. Squad cross-check warnings.
- Player identity: PDF names are resolved per team through admin-confirmed aliases (`player_aliases`). Similar names (same team, or an exact match at another club) are suggestions that require an explicit choice; nothing is merged automatically. New players get an internal ID (`pc-…`, provider `placcric`) or a CricHeroes ID typed by the admin.
- Revisions (`match_revisions`): every publish stores the full record; identical re-imports are no-ops (hash of scores, excluding names and retrieval time); corrections create revisions with a field diff; restore republishes an old revision as a new one. Data published before revisions gets a baseline revision on first correction.
- Ties, no-results and super overs are rejected explicitly.

### Remaining

- Documented CSV templates (deferred: PDFs are the chosen route).
- Points table, after the competition's rules for ties, abandoned matches, NRR and DLS are confirmed.
- Storing maidens, fall of wickets, minutes, squads and match officials (parsed from PDFs but not yet stored).
- Reviewer identity is "workspace PIN user" until Google accounts (M2).
- Merging two player records created by mistake (today: link correctly at review time).

### Original scope

- Reviewed JSON imports and documented, versioned CSV templates (matches, innings, batting, bowling) with row-level errors.
- Stage imports before committing; the preview shows source, match IDs, innings totals, validation errors, identity ambiguities and field-level changes to existing matches.
- Admin approval before publishing. Preserve source URLs, external IDs, timestamps, file hashes, reviewer identity and correction history.
- Identical imports are a no-op; corrections create revisions; accepted records apply atomically; previous revisions can be restored.
- Raw uploads stored privately (outside served directories and git), with size limits and safe generated filenames.
- Provider-neutral model; any CricHeroes adapter is separate from analytics.
- Explicit handling (schema and UI) or explicit rejection of ties, no-results and super overs, documented.
- Club listings stay separate from confirmed squads.

Acceptance: rejection changes nothing; identical imports don't change stats; approved corrections update atomically; restore works; no dashboard request contacts CricHeroes.

## CricHeroes adapter (blocked)

See docs/DATA_INGESTION.md for what is confirmed. Build only against a documented export format or an approved integration, with fixtures and reconciliation tests. Scorer-supplied files continue to work regardless.

## M4 — UI and analytics

Preserve and improve the dashboard, match centre, player profiles, team filters, comparison and captain notes. Test desktop/mobile layouts, keyboard navigation, contrast, loading/error/empty states and permission-dependent controls. Display imported-data coverage and source warnings clearly. Handle zero vs undefined statistics correctly. No ball-by-ball, phase, wagon-wheel or predictive metrics without the underlying data. Coaching stays deterministic.

## M5 — Release readiness

Reproducible setup, migrations and seed/import commands; PostgreSQL backup/restore; production guidance for HTTPS, OAuth callbacks, secrets, trusted hosts and persistent storage; health/readiness endpoints; tests for auth, permissions, analytics, migrations, imports and correction rollback; a manual acceptance checklist; updated README, CLAUDE.md and architecture docs. No public deployment without the owner's decision.
