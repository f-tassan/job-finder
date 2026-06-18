# job-finder — Quickstart

## 1. Put these files in your `job-finder` project repo
```
job-finder/
  BUILD_SPEC.md   docker-compose.yml   .env.example   Caddyfile   db/schema.sql
```
```bash
cp BUILD_SPEC.md CLAUDE.md   # so Claude Code loads it automatically
cp .env.example .env         # then fill in .env
git init && git add -A && git commit -m "Phase 0: spec + infra scaffolding"
```

## 2. Get keys before you start
- **Anthropic API key** → console.anthropic.com (`ANTHROPIC_API_KEY`)
- **Telegram bot** → message @BotFather, create one bot (shared); each user stores
  their own chat id in-app
- An **email inbox** that receives job-alert emails from Bayt / Indeed / LinkedIn
  saved searches (for IMAP discovery)

## 3. Build one phase at a time
Start with the kickoff prompt below (also reproduced in chat). After Phase 0, say
*"Now build Phase 1 from the spec,"* review, commit, and continue. After **Phase 1**
you already have a working multi-user tracker (login, answer bank + field, CV upload,
kanban). Discovery (2), tailoring (3), pre-fill review queue (4), notifications (5)
layer on; Bayt/LinkedIn + deploy (6) come last.

## 4. Run it
```bash
docker compose up -d --build
docker compose logs -f api
```
Visit `https://$DOMAIN` (or map to localhost for dev). Log in as the seeded admin,
then create the other users from `/admin/users` (capped at `MAX_USERS`).

## Guardrails baked into the spec
- Multi-user with strict per-user isolation; built for ~3, seeded with one.
- Saudi-national profile fields (National ID, no Iqama/visa); national portals
  (Jadarat/Qiwa/Taqat) included in discovery.
- Each user picks a **field** from a dropdown or types their own.
- Nothing auto-submits to LinkedIn/Bayt — discovery + pre-fill only, you click submit.
- Unknown/sensitive fields (expected salary, etc.) stay **blank** until you fill them.
- Tailoring never invents qualifications — only your answer-bank / CV data is used.
