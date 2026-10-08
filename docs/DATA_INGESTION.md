# Match ingestion: import first

## Operating decision

PostgreSQL is the dashboard's source of truth. Obtain a finalized record once after a match and import corrections explicitly. Dashboard page loads never contact CricHeroes, and there is no crawler or polling. This avoids depending on website markup and repeated requests.

## Acquisition choices

| Route | Suitability | What must be confirmed |
| --- | --- | --- |
| Scorer/organiser sends structured JSON or agreed CSV | Preferred near-term route; no crawling | Format, accurate IDs and authority to share |
| Export offered to an organiser or Pro subscriber by their scoring system | Preferred if actually available | Supported format, access and redistribution terms |
| Authorised CricHeroes API/partner feed | Best future automation route if provided | Endpoint contract, coverage, credentials, limits and permissions |
| Final scorecard PDF/image supplied by scorer | Useful manual fallback | Human comparison against original before acceptance |
| PlacCric-native score entry | Independent alternative | Extra scorer workload, reconciliation and approval process |
| General cricket data API | Unconfirmed for this tournament | Exact tournament/match coverage before paying |
| Frequent website crawling | Excluded | Not required for this project |

## CricHeroes Pro: what is confirmed

Research on 8 October 2026 used only official CricHeroes pages, as they appear in web search results. Direct page fetches from the development environment failed, so this summary has not been checked against the live pages.

Confirmed, according to the search summaries of official pages:

- CricHeroes' own blog describes PRO as a membership with features such as performance analytics (CricInsights), live streams, highlights, custom themes, PRO Club access and an ad-free experience. Its feature comparison does not list a data export, API or integration. That post was over a year old when reviewed.
- Public match scorecard pages show a "Download Scorecard" control.

Unknown (to confirm with CricHeroes support or in the app):

- Whether "Download Scorecard" needs Pro, which file format it produces (for example PDF or image) and whether it is machine-readable.
- Whether tournament organisers can export match, player or points-table data in bulk.
- Whether any official API, partner feed or webhook exists, on what terms, and with what redistribution rights.

No official developer API documentation was found. Do not reverse-engineer private endpoints, reuse logged-in session cookies, or ask for the account password. If you supply an export file, inspect its format, add it as a fixture (after a provenance/permission review) and build a separate adapter with reconciliation tests. Until then, scorer-supplied files and manual input remain the route, and this does not block other work.

Questions to send CricHeroes support: Does Pro or organiser access include a data export for tournament 2194193? In what format (CSV/JSON/PDF)? Does it include player IDs, corrections and ball-by-ball data? Is there an approved API or partner programme, and what use and redistribution terms apply?

## Today's workflow (implemented)

Use `data/scorecards.json` as the import example. An operator transcribes or converts a scorer-supplied record, checks IDs and totals, then uploads through the authenticated **Data & imports** screen. The importer validates the whole file before writing anything, then commits all matches in one transaction. Re-importing a match ID replaces its scores without duplicating statistics. Each import is logged with its source label and a SHA-256 hash of the canonical JSON. Only this tournament's CricHeroes URLs and two-innings matches with a winner are supported. Keep original files privately, outside git.

## Target workflow (Milestone 3, not implemented yet)

1. Receive one final scorecard file per completed match; record provider, external ID, received time and source timestamp.
2. Store the raw file privately (outside served directories and git) under a generated filename, with its hash and a size limit.
3. Parse into provider-neutral staged tables. Distinguish missing values from zero; retain uncertain cells.
4. Preview: source, match IDs, innings totals, identity ambiguities, validation failures and field-level changes relative to existing data.
5. Admin approval before publishing; rejection leaves analytics unchanged. Record the reviewer's identity.
6. Publish atomically as a new revision, keep the prior revision and allow restoring it.
7. Deduplicate on provider + external match ID + content hash: identical content is a no-op; corrections create revisions.

## Proposed CSV support (Milestone 3)

Define and document a versioned contract before implementation: `matches.csv`, `innings.csv`, `batting.csv` and `bowling.csv`, joined by provider/match/innings/player IDs. UTF-8, integer legal balls or cricket-notation overs, schema version, source and timestamps. Provide empty templates and fixtures. Reject duplicate keys and inconsistent totals with row-specific errors.

CSV fields must not be silently mapped to scorecard facts. Names alone are insufficient to merge players. OCR, if ever added, must retain confidence and source page/cell, never invent missing names or figures, and require human review before data counts as verified.

## Provider integration later

If CricHeroes confirms an approved webhook, accept signed events idempotently; otherwise use an agreed, bounded, manually triggered synchronisation. Neither is confirmed. Keep the adapter separate from analytics so file imports keep working offline.

Reference: https://cricheroes.com/faq
