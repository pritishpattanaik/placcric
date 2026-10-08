# Delivery milestones

Complete one milestone per pull request. Keep implemented status in README accurate.

## M0 — Verify the baseline

Run existing tests. Exercise PIN setup/login/logout/reset, team filters, match details, notes and imports on desktop and mobile. Add HTTP integration coverage for authentication, CSRF and private-file access. Fix concrete failures without a rewrite.

## M1 — Reviewed imports and provenance

Add a versioned migration mechanism, private raw import storage, file hashes, staged preview, approval and correction revisions. Display row-level failures and changed fields. Acceptance: rejection changes nothing; identical imports do not change stats; approved corrections update atomically; prior revisions can be restored; state-changing endpoints require authentication and CSRF.

## M2 — Scorer-friendly input

Add documented CSV templates and validation, with manual score entry if needed. Acceptance: scorer can supply a completed match without visiting CricHeroes; previews show missing/ambiguous identities; no silent merges; malformed uploads cannot corrupt existing data. Keep OCR optional and reviewed.

## M3 — UI and cricket correctness

Improve keyboard navigation, focus, mobile scorecard tables, contrast and loading/error states. Extend result modelling for ties/no-results only with documented competition rules. Acceptance: tested wide/narrow layouts, correct empty/zero/undefined values and visible coverage caveats. No invented ball-by-ball metrics.

## M4 — Confirmed provider adapter

Blocked until authorised access is confirmed. Implement only the documented provider contract with mock fixtures, retry limits, deduplication and correction handling. Acceptance: browsing dashboard causes no provider requests; ingestion remains optional and file imports still work offline.

## M5 — Optional multi-user hosting or AI

Choose separately, based on actual need. Hosting requires production HTTP/HTTPS, individual identities/roles, backups and restore tests. AI requires explicit data disclosure, provider secrets outside git, cost limits and evidence citations. Neither belongs in baseline implementation by default.
