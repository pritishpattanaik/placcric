# Claude Code cloud handoff

## Get this project into your GitHub repository

The project files prepared in ChatGPT are not automatically on your Mac or GitHub. Your earlier Mac directory contained the static dist prototype. Download and extract this package first.

Clone your existing repo into a new directory so you preserve the static prototype:

```bash
cd /Users/pritish/Documents/Perosnal
git clone https://github.com/pritishpattanaik/placcric.git placcric-repo
cd placcric-repo
git switch -c setup/local-mvp
```

Copy the CONTENTS of the extracted placcric-v2 folder into placcric-repo (server.py, app/, web/, tests/, seed JSON, README.md, CLAUDE.md, docs/ and .gitignore). Put server.py at the repo root, not inside another placcric-v2 directory. If the repository already has application code, compare before replacing files; preserve unrelated work. Do not copy runtime databases or backups.

Then:

```bash
python3 -m unittest discover -s tests -v
git status --short
git diff --stat
git add README.md CLAUDE.md docs .gitignore server.py app web tests data/scorecards.json data/rosters.json
git diff --cached --stat
git commit -m "Add PlacCric local MVP and development handoff"
git push -u origin setup/local-mvp
```

Review the staged files, especially third-party seed data, before committing. If the repo is public, first confirm that sharing the seed data is appropriate. Open a pull request in GitHub and merge after review, or select this branch for a cloud session. Do not force-push or overwrite the default branch.

## Start the cloud session

1. Open https://claude.ai/code and install/authorise the Claude GitHub App for pritishpattanaik/placcric.
2. Select the repository and the branch containing these files.
3. Use a normal cloud session for the credit shown in your screenshot. That offer says Projects and Routines are excluded and expires 5 November at 3:59 PM GMT+8; verify the offer details in your account. Do not assume API usage or local coding sessions use this credit.
4. The app needs Python 3.10+ and no dependency installation. Start with default network access; do not add CricHeroes access for ordinary development.
5. Paste the task below. Review the diff and test report, then create a PR. Pull merged changes to your Mac before running them there.

Official cloud guide: https://code.claude.com/docs/en/claude-code-on-the-web

## First task prompt

```text
Read CLAUDE.md, README.md, docs/DATA_INGESTION.md and docs/ROADMAP.md.
Inspect the actual repository and run the existing tests first.
Implement milestone M1: staged JSON imports with a preview and explicit
confirmation before committing, preserving the existing local port-8000 app.
Show source, match IDs, innings totals, validation errors, and corrections
relative to existing matches. Reject invalid files without changing analytics.
Retain provenance and content hashes; use a versioned SQLite migration and
make identical imports a no-op. Keep raw uploads private and outside git.
No CricHeroes crawling, paid provider, LLM calls or framework rewrite.
Add meaningful tests for validation, duplicate imports, correction approval,
rollback and auth/CSRF on import actions. Update docs for implemented behaviour.
Open a PR with test results and clearly state any unperformed UI checks.
```

## Use the credit deliberately

Finish one milestone per session, then review and merge it before the next. Ask Claude to inspect existing code rather than rebuild everything. Keep expensive AI experiments until ingestion and UI are reliable. The $100 is a budget, not a guarantee of how many tasks will complete; monitor the account balance and stop unnecessary sessions.

Cloud localhost is the cloud container, not your Mac. Continue running `python3 server.py --port 8000` on the Mac for your personal dashboard. Cloud sessions are development environments, not a permanent SQLite host.
