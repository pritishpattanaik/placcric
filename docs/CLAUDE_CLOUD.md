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
4. The app needs Python 3.10+, `pip install -r requirements.txt` and a PostgreSQL server. Cloud images may include PostgreSQL; create an isolated `placcric_test` database and set `TEST_DATABASE_URL` so integration tests run rather than skip. Start with default network access; do not add CricHeroes access for ordinary development.
5. Paste the task below. Review the diff and test report, then create a PR. Pull merged changes to your Mac before running them there.

Official cloud guide: https://code.claude.com/docs/en/claude-code-on-the-web

## Next task prompt

Milestone 1 (PostgreSQL) is implemented. After it is reviewed and merged, continue with Milestone 2:

```text
Read CLAUDE.md, README.md, docs/ARCHITECTURE.md, docs/DATA_INGESTION.md and docs/ROADMAP.md.
Inspect the repository and run the tests against an isolated PostgreSQL test database first.
Implement Milestone 2 (Google OpenID Connect, invite allowlist, admin/captain/player roles with
team scope, explicit first-admin bootstrap, removal of PIN login) as described in docs/ROADMAP.md.
Use mocked-provider tests only; mark the live Google check pending until credentials are supplied.
Update docs and open a PR with test results and required configuration.
```

## Use the credit deliberately

Finish one milestone per session, then review and merge it before the next. Ask Claude to inspect existing code rather than rebuild everything. Keep expensive AI experiments until ingestion and UI are reliable. The $100 is a budget, not a guarantee of how many tasks will complete; monitor the account balance and stop unnecessary sessions.

Cloud localhost is the cloud container, not your Mac. Continue running `python3 server.py --port 8000` on the Mac for your personal dashboard. Cloud sessions are development environments, not a permanent database host.
