# PlacCric

A local cricket analytics dashboard for the **Diwhyn Choice T25 Cricket Carnival — Season 2**, with UCC club views, player profiles, match scorecards, comparisons and captain notes.

Repository: https://github.com/pritishpattanaik/placcric

## Status

This package is a working local MVP, built with Python, SQLite and plain HTML/CSS/JavaScript. It is a starting point for further development in Claude Code. It has not been verified against the current contents of the GitHub repository or deployed as a public service.

| Available now | Planned work |
| --- | --- |
| Responsive dashboard, team filters and match details | Browser accessibility and mobile regression tests |
| Player batting/bowling statistics and comparisons | Scorer-friendly CSV entry and import preview |
| PIN login, server sessions and persistent captain notes | Multi-user accounts and roles if required |
| Validated JSON scorecard imports with atomic updates | Provider integration, subject to confirmed access |
| SQLite persistence and six backend tests | Migration/versioning and stronger ingestion audit trail |
| Evidence-based coaching rules | Optional LLM coaching with explicit consent and cost limits |

**Data coverage:** the bundled snapshot contains five completed matches and 15 club roster listings, collected on 7 October 2026. This is not a live feed or a complete season dataset. Club membership lists are not confirmed tournament squads. Player identities from scorecards use CricHeroes player IDs; names in club lists are not automatically merged with them.

The bundled source has recorded discrepancies, including a KL Stars innings total, a DLS match and an unusual batting list. Warnings remain visible. Imported validation establishes numerical consistency, not authenticity. Review the original sources before consequential selection decisions.

Tournament source: https://cricheroes.com/tournament/2194193/diwhyn-choice-t25-cricket-carnival-season-2/matches/past-matches

## Run on your Mac

Requires **Python 3.10 or newer**. No Docker, Node build or third-party Python dependencies are required for this MVP.

From the directory containing `server.py`:

```bash
python3 --version
python3 server.py --port 8000
```

On first launch, create and confirm your own **6–12 digit PIN** in Terminal. Open http://localhost:8000. Stop the server with `Ctrl+C`.

If using the downloaded package:

```bash
cd /Users/pritish/Documents/Perosnal/placcric-v2
python3 server.py --port 8000
```

Once the project is committed to GitHub, a fresh installation is:

```bash
git clone https://github.com/pritishpattanaik/placcric.git
cd placcric
python3 server.py --port 8000
```

The old `python3 -m http.server` command only serves static files. This version needs `server.py` for authentication, database access and imports. Stop any old server occupying port 8000 first.

Reset a forgotten PIN:

```bash
python3 server.py --reset-pin
```

This revokes existing sessions. Use the same `--db` argument when resetting a custom database.

## Architecture

- `server.py`: loopback HTTP server, authenticated API, static assets and startup.
- `app/database.py`: database initialization, scorecard validation and transactional import.
- `app/schema.sql`: normalized teams, players, matches, innings, batting, bowling, notes and authentication tables.
- `app/analytics.py`: aggregates, profiles, match views and deterministic coaching rules.
- `app/security.py`: PIN hashing, session creation and login throttling.
- `web/`: browser UI; no CDN or external font dependency.
- `data/scorecards.json`: initial scorecard snapshot and an example of the supported import format.
- `data/rosters.json`: club name listings, separate from scorecard player identities.
- `tests/test_app.py`: database, identity, statistics, authentication and import tests.
- `CLAUDE.md`: persistent instructions for coding agents.
- `docs/`: ingestion strategy, cloud handoff and development milestones.

The runtime database is `data/placcric.sqlite3`, created and seeded on first launch. SQLite uses foreign keys and WAL mode. To choose a different database:

```bash
python3 server.py --db /absolute/path/placcric.sqlite3 --port 8000
```

### Authentication and deployment boundary

PINs are salted and hashed with PBKDF2; session tokens are random and hashed at rest. Sessions expire after 12 hours. State-changing authenticated requests require a CSRF token. Login failures are throttled; the session cookie is HttpOnly and SameSite=Strict. The server binds only to `127.0.0.1`.

This is a **single-user local application**. Do not expose this HTTP server directly to the internet. Public hosting requires HTTPS, a production application server, user/role design, secret management, backups and deployment testing. A cloud coding session does not permanently host the app or connect to your Mac's localhost.

`PLACCRIC_PIN` exists for isolated automated tests. Do not commit a real PIN, session, environment file or runtime database. Prefer interactive PIN setup locally.

## Match data without frequent crawling

**Default: no scheduled crawler and no network calls to CricHeroes during normal dashboard use.** All analytics read local SQLite data.

1. Have the scorer or tournament organiser provide the finalized scorecard after each match. If an export is available to them, use it; otherwise use an agreed spreadsheet or manually entered record.
2. Convert that record into the current JSON format and retain its original source and match ID.
3. Open the dashboard's data/import screen and upload the JSON. Review warnings and totals first. The current importer writes validated records directly; a preview/approval screen is planned.
4. Correct a match by importing the same match ID again. Scores are replaced transactionally and aggregates are recomputed from stored data.
5. Ask CricHeroes about authorised tournament data access or a partner feed. Do not assume an undocumented API, webhook or export exists. Build an adapter only after capabilities and permissions are confirmed.

Read [the data strategy](docs/DATA_INGESTION.md) for alternatives and the intended import workflow. Screenshots/PDFs can be transcription inputs in a future workflow, but extracted numbers must be reviewed before becoming verified data. General cricket APIs should not be assumed to cover this local tournament.

### Current JSON import contract

Use `data/scorecards.json` as the executable example. A bundle contains a `matches` array of 1–100 matches and optional `retrieved_at`. Each match contains a numeric string `id`, `source_url`, ISO date, venue, two ordered teams, winner, result and two innings. Batting rows use player ID/name, runs, balls, fours, sixes, dismissal and not-out flag. Bowling rows use player ID/name, overs, runs, wickets, dots, wides and no-balls.

Current restrictions: CricHeroes scorecard URLs for this tournament; two innings; a winner matching one team; up to 25 overs per innings and five per bowler. Ties, no-results, super overs, other providers and other competition rules are **not yet supported**. Do not force these into misleading winner records.

Overs use cricket notation: `22.3` means 135 balls, not 22.3 decimal overs. Internally, balls are integers. Batting runs plus extras and bowling legal-ball totals must reconcile. Failed validation leaves stored scores unchanged. Repeated imports do not duplicate match statistics, although each import is logged.

### Statistical scope

All displayed aggregates are for imported matches and active team filters. Batting average is runs divided by dismissals; zero dismissals yields an undefined average, displayed as a dash. Strike rate is runs per 100 balls. Bowling economy is conceded runs per six legal balls. Zero-ball, zero-run not-out listings do not count as batting innings. No ball-by-ball data is bundled; phase splits, wagon wheels, pace/spin analysis and predictive win probabilities are not available. DLS results must not be used to infer a standard NRR table without competition rules.

## Tests and backup

```bash
python3 -m unittest discover -s tests -v
```

If Node is installed, also check browser JavaScript syntax:

```bash
node --check web/app.js
```

Before updating code or reimporting corrections, stop the server and back up `data/placcric.sqlite3` together with any adjacent `-wal` and `-shm` files. Alternatively use SQLite's backup API for a consistent live snapshot. Backups contain PIN hashes, sessions and notes; keep them private and outside git.

## Develop with Claude Code in the cloud

Start with [the cloud handoff guide](docs/CLAUDE_CLOUD.md) and [the milestone backlog](docs/ROADMAP.md). Connect the Claude GitHub App to this repository, push these files, then choose the repository in https://claude.ai/code. Cloud sessions work from repository content, not files left only on your Mac.

Official instructions: https://code.claude.com/docs/en/claude-code-on-the-web

## Attribution and licensing

PlacCric is independent of CricHeroes and is not an official CricHeroes product. Source links and provenance should accompany imported data. No licence to redistribute third-party match data is implied. The repository owner should select a code licence and review data-sharing permissions before public redistribution.
