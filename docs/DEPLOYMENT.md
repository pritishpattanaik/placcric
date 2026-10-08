# Deployment: dev → stage → prod

PlacCric runs as Docker Compose services: `db` (PostgreSQL 16) and `app` (FastAPI). There is also an optional `caddy` service for public HTTPS. Image versions are pinned in `compose.yaml` and `Dockerfile` (PostgreSQL 16, Python 3.12, Caddy 2), so neither machine needs its own Python or PostgreSQL installation. All settings live in a `.env` file on each machine, and `.env` is never committed.

| Environment | Where | Git branch | How it updates |
| --- | --- | --- | --- |
| **dev** | Claude Code cloud session | `claude/<topic>` | Claude commits and opens a pull request into `main` |
| **stage** | Your MacBook (OrbStack) | `main` | You review and merge the PR, then run `scripts/deploy.sh main` |
| **prod** | Contabo VM | `production` | You promote `main` → `production`, then run `scripts/deploy.sh production` on the VM |

CI (`.github/workflows/ci.yml`) runs on every pull request and on pushes to `main` and `production`. It runs the tests on Python 3.10 and 3.12 against PostgreSQL 16, checks the JavaScript syntax, validates the compose file and builds the image.

`scripts/deploy.sh <branch>` does the same steps on both machines:
1. Refuses to run if there are uncommitted changes, then fast-forwards the branch.
2. Builds the image and tags it with the commit SHA.
3. Starts the database and takes a backup.
4. Applies migrations.
5. Asks for a PIN if none is set.
6. Restarts the services and checks `/readyz` and `/healthz`, which reports the deployed version.
7. Records the deploy in `deploy-history.log`.

It never seeds or resets data.

> **Security note — read before prod.** Login is still the interim single PIN until Milestone 2 (Google sign-in). Run production in **private mode** (reachable only through an SSH tunnel) until M2 is merged. Public HTTPS mode is implemented and tested, but it puts a 6–12 digit PIN on the internet. The PIN is throttled per IP, but this is not appropriate protection for private club data.

---

## 1. One-time GitHub setup

1. Merge PR #1 into `main` once you've reviewed it and CI is green.
2. Create the `production` branch from `main`:
   ```bash
   git switch main && git pull
   git push origin main:production
   ```
3. Protect both branches. Go to GitHub → *Settings → Rules → Rulesets → New branch ruleset* and target `main` and `production`:
   - Require a pull request before merging.
   - Require status checks to pass: `tests (3.10)`, `tests (3.12)`, `docker`.
   - Block force pushes and deletions.

## 2. Stage — MacBook with OrbStack (OrbStack already running)

### First time

```bash
cd ~/Documents/Perosnal                  # or wherever you keep projects
git clone https://github.com/pritishpattanaik/placcric.git placcric-stage
cd placcric-stage
git switch main

cp .env.example .env
PW=$(openssl rand -hex 24)
sed -i '' "s/CHANGE_ME/$PW/g" .env       # sets the same password everywhere in .env
chmod 600 .env
```

**If you created a `placcric-postgres` container earlier**, it occupies port 5432. If it already contains data you want to keep, export it first, then stop it:

```bash
docker exec placcric-postgres pg_dump -U placcric -Fc placcric > ~/placcric-old.dump   # only if it has data to keep
docker stop placcric-postgres
```

Deploy:

```bash
scripts/deploy.sh main        # builds, migrates, asks you to create a PIN, starts
```

Load data. Do this once, and choose **one** of the three options:

```bash
# a) Fresh: bundled 5-match snapshot
docker compose run --rm app python -m app.cli seed

# b) From the old SQLite app (copy the files first; the original stays untouched)
mkdir -p ~/placcric-import && cp /path/to/old/data/placcric.sqlite3* ~/placcric-import/
docker compose run --rm -v ~/placcric-import:/import app python -m app.cli migrate-sqlite /import/placcric.sqlite3 --dry-run
docker compose run --rm -v ~/placcric-import:/import app python -m app.cli migrate-sqlite /import/placcric.sqlite3

# c) From the earlier placcric-postgres container
scripts/restore.sh ~/placcric-old.dump
```

Open http://localhost:8000 and sign in with your PIN.

### Every time a PR is merged into `main`

```bash
cd ~/Documents/Perosnal/placcric-stage
scripts/deploy.sh main
```

Check the change at http://localhost:8000. If it's good, promote it to prod (section 4).

Optional: run the test suite in containers against a throwaway database. Your stage data is not touched.

```bash
docker compose --profile test run --rm --build tests
docker compose --profile test rm -sf test-db
```

## 3. Prod — Contabo VM (first time)

These steps assume Ubuntu 24.04 and that you have the VM's IP address and root password from Contabo. Replace `SERVER_IP` below.

### 3.1 Harden SSH and add a deploy user

From your Mac (create a key once if you don't have one: `ssh-keygen -t ed25519`):

```bash
ssh root@SERVER_IP
adduser deploy                          # set a password (used for sudo)
usermod -aG sudo deploy
mkdir -p /home/deploy/.ssh && cp ~/.ssh/authorized_keys /home/deploy/.ssh/ 2>/dev/null || true
exit
ssh-copy-id deploy@SERVER_IP            # from the Mac
ssh deploy@SERVER_IP                    # confirm key login works before the next step
```

On the VM, as `deploy`, disable password and root logins, then turn on the firewall and automatic security updates:

```bash
sudo sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/; s/^#\?PermitRootLogin .*/PermitRootLogin no/' /etc/ssh/sshd_config
sudo systemctl restart ssh
sudo ufw allow OpenSSH
sudo ufw enable
sudo apt-get update && sudo apt-get -y upgrade && sudo apt-get install -y unattended-upgrades git
```

Note: ports that Docker publishes on `0.0.0.0` bypass ufw. PlacCric publishes the database and app on `127.0.0.1` only. Only Caddy publishes 80/443, and only in public mode.

### 3.2 Install Docker Engine and the Compose plugin

These are Docker's official Ubuntu instructions (check https://docs.docker.com/engine/install/ubuntu/ for changes):

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker deploy          # membership of the docker group is root-equivalent
exit                                    # log out and back in for the group to apply
ssh deploy@SERVER_IP
docker compose version
```

### 3.3 Get the code onto the VM

If the repository is **public**:

```bash
git clone https://github.com/pritishpattanaik/placcric.git ~/placcric
```

If it is **private**, use a read-only deploy key:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/placcric_deploy -N "" -C "contabo-placcric"
cat ~/.ssh/placcric_deploy.pub
# GitHub → repo Settings → Deploy keys → Add deploy key → paste, leave "Allow write access" OFF
cat >> ~/.ssh/config <<'EOF'
Host github.com
  IdentityFile ~/.ssh/placcric_deploy
  IdentitiesOnly yes
EOF
git clone git@github.com:pritishpattanaik/placcric.git ~/placcric
```

### 3.4 Configure and deploy

```bash
cd ~/placcric
git switch production
cp deploy/env.production.example .env
sed -i "s/CHANGE_ME/$(openssl rand -hex 24)/" .env
chmod 600 .env
nano .env                               # review; keep Mode A (private) for now
scripts/deploy.sh production            # asks you to create the production PIN
```

Use a different PIN and database password from stage.

### 3.5 Load data (once)

Choose one:

- **Copy your stage database** (recommended if you've been curating data on the Mac):
  ```bash
  # on the Mac
  cd ~/Documents/Perosnal/placcric-stage && scripts/backup.sh
  scp "$(ls -1t backups/*.dump | head -1)" deploy@SERVER_IP:placcric/backups/
  # on the VM
  cd ~/placcric && scripts/restore.sh backups/<that file>.dump
  ```
  Restoring a stage backup also copies the stage PIN. Afterwards, set a production PIN with `docker compose run --rm app python -m app.cli set-pin`.
- **Fresh:** `docker compose run --rm app python -m app.cli seed`

### 3.6 Use it (private mode)

From the Mac:

```bash
ssh -N -L 8000:127.0.0.1:8000 deploy@SERVER_IP
```

Then open http://localhost:8000. Stop the tunnel with `Ctrl+C`. If stage is running on your Mac at the same time, use another local port: `ssh -N -L 8001:127.0.0.1:8000 deploy@SERVER_IP` and open http://localhost:8001. Also add `localhost:8001` to `PLACCRIC_ALLOWED_HOSTS` in the VM's `.env`, then rerun `docker compose up -d app`.

### 3.7 Backups on the VM

Each deploy takes a backup automatically. Add a daily backup that keeps the newest 14:

```bash
crontab -e
# add:
15 2 * * * cd $HOME/placcric && scripts/backup.sh >> backups/backup.log 2>&1
```

Copy backups off the server regularly, because a VM failure would take local backups with it. From the Mac:

```bash
mkdir -p ~/placcric-backups/prod && scp 'deploy@SERVER_IP:placcric/backups/*.dump' ~/placcric-backups/prod/
```

## 4. Promote stage → prod (routine release)

1. On GitHub, open a pull request **from `main` into `production`** (title e.g. "Release 2026-10-09").
2. Wait for CI to pass, then merge it.
3. On the VM:
   ```bash
   ssh deploy@SERVER_IP
   cd ~/placcric && scripts/deploy.sh production
   ```
4. Open the app through the tunnel. The `healthz` line printed by the deploy shows the deployed commit.

**Hotfix:** branch from `production`, open a PR into `production`, deploy it, then open a PR from `production` into `main` so stage gets the fix too.

## 5. Rollback

Every deploy keeps the previous images (tagged by commit) and a pre-deploy backup.

```bash
cd ~/placcric
tail -5 deploy-history.log              # find the last good commit, e.g. 6000d44
docker image ls placcric-app            # confirm its image exists
docker tag placcric-app:6000d44 placcric-app:latest
docker compose up -d --wait app
```

If the bad release included a **database migration**, also restore the backup taken just before it (`ls -1t backups/`) with `scripts/restore.sh backups/<file>.dump`. Then fix forward: revert the change in a PR to `production`, so the branch matches what is running before the next deploy.

## 6. Public HTTPS (only after Milestone 2)

1. Point a DNS **A record** (e.g. `placcric.yourdomain.com`) at `SERVER_IP`.
2. On the VM: `sudo ufw allow 80,443/tcp && sudo ufw allow 443/udp`.
3. In `.env`, comment out the Mode A lines and enable Mode B (`COMPOSE_PROFILES=https`, `PLACCRIC_DOMAIN`, `PLACCRIC_ALLOWED_HOSTS=<domain>`, `PLACCRIC_FORWARDED_ALLOW_IPS=*`, `PLACCRIC_COOKIE_SECURE=true`).
4. Run `scripts/deploy.sh production`. Caddy obtains and renews a free Let's Encrypt certificate automatically.

Caddy sends HSTS, redirects HTTP to HTTPS and forwards only requests for your domain. The app trusts `X-Forwarded-*` headers only when `PLACCRIC_FORWARDED_ALLOW_IPS` is set, which keeps the HTTPS Origin/CSRF check and per-client login throttling correct.

## 7. Configuration reference (`.env`)

| Variable | Purpose | Stage (Mac) | Prod private | Prod public |
| --- | --- | --- | --- | --- |
| `POSTGRES_USER` / `POSTGRES_DB` | database role / name | `placcric` | `placcric` | `placcric` |
| `POSTGRES_PASSWORD` | database password (hex) | random | different random | different random |
| `POSTGRES_PUBLISH` | host port for PostgreSQL | `127.0.0.1:5432` | `127.0.0.1:5432` | `127.0.0.1:5432` |
| `PLACCRIC_ENV` | `development` or `production` | `development` | `production` | `production` |
| `PLACCRIC_PUBLISH` | host port for the app | `127.0.0.1:8000` | `127.0.0.1:8000` | `127.0.0.1:8000` |
| `PLACCRIC_ALLOWED_HOSTS` | accepted Host headers | `localhost:8000,127.0.0.1:8000` | same | your domain |
| `PLACCRIC_FORWARDED_ALLOW_IPS` | trusted proxy IPs | empty | empty | `*` |
| `PLACCRIC_COOKIE_SECURE` | Secure cookie flag | empty (off) | `false` | `true` |
| `COMPOSE_PROFILES` | extra services | unset | unset | `https` |
| `PLACCRIC_DOMAIN` | domain for Caddy | unset | unset | your domain |
| `DATABASE_URL`, `TEST_DATABASE_URL` | only for running without Docker (venv) | optional | unused | unused |
| `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` | optional AI analysis (docs/AI.md) | optional | optional | optional |
| `PLACCRIC_AI_DAILY_LIMIT`, `PLACCRIC_AI_MAX_OUTPUT_TOKENS` | AI cost caps | 25 / 2000 | 25 / 2000 | 25 / 2000 |

The app container builds its own `DATABASE_URL` from the `POSTGRES_*` values. If you change `POSTGRES_PASSWORD` after the database volume exists, the database keeps the old password. Change it inside PostgreSQL first (`ALTER ROLE placcric PASSWORD '…'`), then update `.env`.

## 8. Everyday commands

| Task | Command |
| --- | --- |
| Status | `docker compose ps` |
| App logs | `docker compose logs -f app` |
| Stop / start | `docker compose stop` / `docker compose up -d` |
| SQL shell | `docker compose exec db psql -U placcric placcric` |
| Backup / restore | `scripts/backup.sh` / `scripts/restore.sh <file>` |
| Change PIN | `docker compose run --rm app python -m app.cli set-pin` |
| Schema status | `docker compose run --rm app python -m app.cli db-status` |

**Never run `docker compose down -v` or `docker volume rm placcric_pgdata`.** They delete the database. `docker compose down` without `-v` is safe.

Uploaded scorecard files live in the `placcric_uploads` volume (not in the database dump). To copy them out for an off-server backup:

```bash
docker compose cp app:/app/uploads ~/placcric-backups/uploads-$(date +%Y%m%d)
```

## Troubleshooting

- **`Set POSTGRES_PASSWORD in .env`:** `.env` is missing or incomplete in the current directory.
- **Port 5432 or 8000 already in use:** another PostgreSQL or old server is running. Stop it, or change `POSTGRES_PUBLISH` / `PLACCRIC_PUBLISH` (and `PLACCRIC_ALLOWED_HOSTS` to match the new app port).
- **App restarts with "No PIN is configured":** run `docker compose run --rm app python -m app.cli set-pin`.
- **`Invalid host` (403):** add the exact host and port you are using to `PLACCRIC_ALLOWED_HOSTS`, then run `docker compose up -d app`.
- **Login works but nothing saves, or you are logged out immediately over plain HTTP:** set `PLACCRIC_COOKIE_SECURE=false` (private mode) or use HTTPS.
- **`migrate-sqlite` cannot open the file:** make the copied folder readable by the container (`chmod -R a+rwX ~/placcric-import`).
