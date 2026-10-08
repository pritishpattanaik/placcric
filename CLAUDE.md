# PlacCric coding instructions

Read README.md, docs/DATA_INGESTION.md and docs/ROADMAP.md before changes. Inspect the actual checkout: documentation describes the supplied Python MVP, not an assumed deployed product.

## Goal

Improve a cricket analytics app for tournament 2194193, with UCC club views. Prioritise reliable match imports, understandable statistics, mobile usability and persistent data. Pritish Pattanaik's CricHeroes player ID is 32722355; do not infer identity from a matching name.

## Constraints

- Keep Python 3.10+, SQLite and the existing browser UI initially. Do not introduce Docker, a framework rewrite or paid services without a concrete requirement.
- Local launch must remain `python3 server.py --port 8000`.
- No scheduled CricHeroes scraping, background polling or network access triggered by viewing the dashboard.
- Do not invent provider endpoints, export features or access credentials. Prefer organiser/scorer-supplied files. Provider integration is blocked on confirmed access.
- Never fabricate statistics or mark OCR/model output verified without human review. Distinguish snapshots, club lists and tournament squads.
- Store cricket overs as legal balls internally. Preserve source IDs, source URLs, source timestamps, warnings and small-sample caveats.
- Preserve PIN hashing, session expiry, CSRF checks, login throttling, loopback binding and parameterised SQL. Never hardcode a usable production PIN.
- Never commit runtime SQLite files, secrets, auth sessions, backups or private uploaded scorecards. Public fixtures need a deliberate provenance/permission review.
- Coaching is currently deterministic. Do not describe it as an LLM. Optional AI work must declare provider, cost limits and which personal data is sent.

## Workflow

1. Inspect code and current tests. Pick one bounded roadmap milestone.
2. Implement a complete vertical slice with clear validation/error messages.
3. Add meaningful tests for changed behaviour. Use temporary databases, never a user's database.
4. Run `python3 -m unittest discover -s tests -v`. Run `node --check web/app.js` when Node is available.
5. For UI changes, test narrow/wide layouts, keyboard navigation, loading/error/empty states and authenticated interactions. Report unavailable browser checks honestly.
6. Update relevant documentation and open a PR with behaviour, validation and limitations. Do not merge or deploy automatically.

## Data integrity

The current import validator only supports completed two-innings matches with a winner from this tournament. Extend the schema deliberately for ties/no-results/super overs. Reimports should not duplicate statistics. Validation must run before writes, and writes must be atomic. IDs must not be reassigned because names changed. Add migration and rollback coverage before schema changes.

Immediate preferred task: M1 in docs/ROADMAP.md — import staging, preview, confirmation and durable provenance. Read docs/CLAUDE_CLOUD.md for the first task prompt.
