# job-finder — Deployment & Operations Runbook

Single-VPS deployment with Docker Compose behind Caddy (automatic HTTPS).

## 1. Prerequisites
- A VPS with Docker + Docker Compose v2.
- A domain (e.g. `jobs.example.com`) with an A/AAAA record pointing at the VPS.
- Ports **80** and **443** open to the internet (Caddy needs them for HTTPS/ACME).

## 2. Configure
```bash
git clone <repo> job-finder && cd job-finder
cp .env.example .env
```
Edit `.env` and set at minimum:
- `POSTGRES_PASSWORD` — strong random value
- `JWT_SECRET` — long random string (e.g. `openssl rand -hex 32`)
- `DOMAIN` — your real domain (e.g. `jobs.example.com`)
- `PUBLIC_API_URL=/api`
- `FIRST_USER_EMAIL` / `FIRST_USER_NAME` / `FIRST_USER_PASSWORD` — the seeded admin
- Optional: `OPENAI_API_KEY` **or** `ANTHROPIC_API_KEY` (tailoring/parsing; app works without)
- Optional: `TELEGRAM_BOT_TOKEN` (per-user chat ids are set in-app under Settings)
- Optional: `IMAP_*` (the email_alerts connector)

> The committed `docker-compose.yml` runs Caddy on 80/443 for production. The
> local-dev `docker-compose.override.yml` (gitignored) remaps Caddy to high ports;
> **do not copy it to the server.**

## 3. Launch
```bash
docker compose up -d --build
docker compose ps          # all services should become healthy
```
First boot: Postgres initialises the schema, the API prestart runs Alembic
migrations (`alembic upgrade head`), and the seeded admin is created. The worker
downloads the embedding model once (cached in the `model_cache` volume).

Visit `https://$DOMAIN`, log in as the seeded admin, and create the other users
under **/admin/users** (capped at `MAX_USERS`).

## 4. First-run checklist (per user)
1. **Profile** — add field(s) + answer-bank data (and a default CV under **CVs**).
2. **Searches** — add sources (Greenhouse/Lever/Ashby tokens, LinkedIn/Bayt
   keywords, or a company careers URL). LinkedIn/Bayt are **discovery-only**.
3. **Settings** — paste your Telegram chat id to receive notifications.
4. **Jobs → Run discovery now** (admin) to populate the ranked feed.

## 5. Operations
- **Discovery** runs automatically via Celery Beat every `DISCOVERY_INTERVAL_MINUTES`
  (default 360). Trigger on demand from **Jobs → Run discovery now**.
- **Logs:** `docker compose logs -f api worker browser-worker`
- **Update:** `git pull && docker compose up -d --build`
- **DB backup:**
  ```bash
  docker compose exec -T db pg_dump -U $POSTGRES_USER $POSTGRES_DB > backup_$(date +%F).sql
  ```
- **DB restore:** `cat backup.sql | docker compose exec -T db psql -U $POSTGRES_USER $POSTGRES_DB`
- **Volumes:** `pgdata` (database), `files` (CVs + generated PDFs + screenshots),
  `model_cache` (embedding model), `caddy_data/config`. Back up `pgdata` + `files`.

## 6. Hardening notes
- Secrets live only in `.env` (gitignored). Rotate `JWT_SECRET`/DB password on exposure.
- Registration is closed; only the admin creates users (capped at `MAX_USERS`).
- Per-user isolation: every query is scoped to the authenticated user; admin-only
  routes require `is_admin`.
- **No auto-submit**: LinkedIn/Bayt are discovery-only; standalone-ATS forms are
  pre-filled but the human submits. Sensitive fields (salary, visa, "why this
  company") are always left blank.
- Caddy terminates TLS; only 80/443 are exposed. The DB/Redis/API/web ports are
  internal to the compose network.
- Consider provider rate/cost limits if you enable an LLM key; the app falls back
  to deterministic CV assembly without one.

## 7. Health
Every service has a healthcheck; `docker compose ps` shows `healthy`. The API
liveness probe is `GET /api/health` → `{"status":"ok"}`.
