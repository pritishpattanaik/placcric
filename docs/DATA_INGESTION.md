# Match ingestion: import first

## Operating decision

Keep SQLite as the dashboard's source of truth. Obtain a finalized record once after a match and import corrections explicitly. Dashboard page loads must never contact CricHeroes. This avoids dependence on website markup and repeated requests.

## Acquisition choices

| Route | Suitability | What must be confirmed |
| --- | --- | --- |
| Scorer/organiser sends structured JSON or agreed CSV | Preferred near-term route; no crawling | Format, accurate IDs and authority to share |
| Export offered to an organiser by their scoring system | Preferred if actually available | Supported format, access and redistribution terms |
| Authorised CricHeroes API/partner feed | Best future automation route if provided | Endpoint contract, coverage, credentials, limits and permissions |
| Final scorecard PDF/image supplied by scorer | Useful manual fallback | Human comparison against original before acceptance |
| PlacCric-native score entry | Independent alternative | Extra scorer workload, reconciliation and approval process |
| General cricket data API | Unconfirmed for this tournament | Exact tournament/match coverage before paying |
| Frequent website crawling | Excluded from default design | Not required for this project |

The reviewed public CricHeroes documentation does not establish a public developer API or guaranteed scorecard export. Ask their support or the organiser about approved access. Do not reverse-engineer private mobile endpoints or use session cookies as a substitute for provider permission.

## Today's workflow

Use data/scorecards.json as the import example. A knowledgeable operator transcribes or converts a scorer-supplied record, checks IDs and totals, then uploads through the authenticated data screen. Import currently validates and commits immediately. Only the current tournament's CricHeroes URLs and two-innings wins are supported. Retain original files privately outside git.

## Target workflow (not implemented yet)

1. Receive one final scorecard file per completed match; record provider, external ID, received time and source timestamp.
2. Calculate a file hash and store an immutable raw record outside publicly served directories.
3. Parse into provider-neutral staged tables. Distinguish missing values from zero; retain uncertain cells.
4. Show a preview: source, innings totals, identities, reconciliation failures and changes relative to existing data.
5. Require explicit approval before committing a reviewed match; rejection must leave analytics unchanged.
6. Publish atomically, track a revision and preserve the prior version for rollback.
7. Deduplicate on provider + external match ID and content hash. Same content is a no-op; corrections produce a new revision.

The current database has a basic import log, not immutable raw records, revision history or review staging. These are roadmap items.

## Proposed CSV support

Define and document a versioned contract before implementation: matches.csv, innings.csv, batting.csv and bowling.csv, joined by provider/match/innings/player IDs. Use UTF-8 and integer legal balls; include schema version, source and timestamps. Provide downloadable empty templates and fixtures. Reject duplicate keys and inconsistent totals with row-specific errors.

CSV fields must not be silently mapped to current scorecard facts. Names alone are insufficient to merge players. OCR should retain confidence and source page/cell information; it must never invent missing names or figures.

## Provider integration later

Request access for tournament 2194193 from CricHeroes. Ask specifically about finalized scorecards, corrections, player IDs, delivery method, historical coverage, retention and allowed use. If an approved webhook exists, accept signed events idempotently; otherwise follow an agreed bounded synchronization schedule. Neither capability is confirmed today. Keep the provider adapter separate from analytics so file imports continue to work offline.

Reference: https://cricheroes.com/faq
