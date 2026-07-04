# job-finder — Build Specification

> Source of truth for building the app. Keep at repo root, copy to `CLAUDE.md` so
> Claude Code reads it every session, and build **phase by phase** (commit per phase).

## 0. What we are building

A private, **multi-user** (designed for ~3 users, seeded with one) system for the
**Saudi Arabia** job market, for **Saudi nationals**. **Telegram-first**: the bot
is where actions happen; the web app is for tracking, analysis, and history.

1. **Discovers** relevant jobs from Saudi sources on a schedule — the heart of
   the product (LinkedIn especially, plus ATS boards, national portals, company
   careers pages).
2. **Ranks** them per user (hard filters + semantic similarity + LLM re-rank).
3. **Sends** each strong match to that user on **Telegram** — title, company,
   link — with **inline buttons**: 📄 CV · ✉️ Letter · 📄+✉️ Both · ✅ I applied ·
   🙈 Skip (+ 🔗 Apply link on LinkedIn posts, resolved via the user's cookie).
4. **Tailors on demand** (cheap model, gpt-4o-mini): an ATS-safe CV and/or cover
   letter for that exact job, grounded in the user's answer bank — rendered to
   PDFs, **sent back over Telegram** and saved on the job's web page.
5. The user applies **manually** (opens the link, fills the form, uploads the
   PDFs) — no auto-fill, no auto-submit, nothing to break or get banned for.
6. **Marks submitted automatically**: one tap on “✅ I applied” in Telegram, or
   hands-free via the IMAP watcher that spots “thank you for applying”
   confirmation emails.
7. Gives each user a **dashboard**: a small kanban (discovered → docs ready →
   submitted → interview → offer / rejected), a page per job with the extracted
   description + saved documents, CV upload/versioning, and the answer bank.

Each user is fully isolated: their own profile, field, CVs, saved searches, matches,
applications, and notifications. The job catalog itself is shared (deduplicated), but
**relevance and applications are per user.**

### Hard design rules — read before writing code
- **No automated form filling or submission anywhere.** (Pivoted 2026-07: the
  per-ATS applier / pre-fill / browser-agent stack was removed — platform-by-
  platform automation was too brittle to trust.) Automation stops at discovery
  and document generation; the human applies. Playwright is used ONLY to read
  JS careers pages during discovery, never to act on a form.
- **Never invent qualifications** during tailoring — only data in that user's answer
  bank / parsed CV may be used.
- **Keep generation cheap.** Documents are generated per job on a button tap, so
  everything runs on the cheap model (gpt-4o-mini) unless there's a strong
  reason not to.
- The bot service is the ONLY getUpdates consumer, and every chat is bound to
  one user (their telegram_chat_id setting) — a callback may only ever touch
  that user's rows.

## 1. Tech stack (do not substitute without reason)

| Layer            | Choice                                                              |
|------------------|---------------------------------------------------------------------|
| Backend API      | Python 3.12, **FastAPI**, Pydantic v2, SQLAlchemy 2.0 (async), Alembic |
| Task queue       | **Celery** + Redis broker; **Celery Beat** for scheduling           |
| Telegram bot     | Long-polling service (`app.bot`, httpx) — commands + inline buttons |
| Browser worker   | **Playwright (Python)**, own container/queue — discovery rendering ONLY |
| Database         | **PostgreSQL 16** + **pgvector**                                    |
| Embeddings       | `sentence-transformers` (`all-MiniLM-L6-v2`, 384-dim, local & free); pluggable to Voyage |
| LLM              | **OpenAI API** (`openai` Python SDK); pluggable to Anthropic Claude |
| CV rendering     | **WeasyPrint** (HTML→PDF, ATS-safe) + optional `python-docx`        |
| Frontend         | **Next.js 14** (App Router), TypeScript, Tailwind, **shadcn/ui**, TanStack Query, react-hook-form + zod, dnd-kit (kanban) |
| Auth             | **Multi-user** JWT; first user seeded from env; admin adds the rest |
| File storage     | Docker volume, served through the authed API (per-user paths)       |
| Notifications    | **Telegram bot** (per-user chat id) + optional SMTP/email           |
| Reverse proxy    | **Caddy** (automatic HTTPS)                                         |
| Deployment       | **Docker Compose**, single VPS                                     |

### LLM model routing (provider: **OpenAI** — the deployed default)
This deployment runs on OpenAI (`LLM_PROVIDER=openai`, `OPENAI_API_KEY` set).
Everything runs on the cheap model — generation cost per document is the
constraint, not maximum polish:
- `gpt-4o-mini` (`OPENAI_PARSE_MODEL`) — CV parsing, relevance re-rank, the
  Telegram chat assistant.
- `gpt-4o-mini` (`OPENAI_TAILOR_MODEL`) — CV tailoring + cover letters (bump to
  `gpt-4o` via env only if quality genuinely disappoints).
All JSON-returning calls use OpenAI structured outputs (`response_format`
json_schema, strict). The provider is pluggable: set `LLM_PROVIDER=anthropic` +
`ANTHROPIC_API_KEY` to switch to Claude (Haiku 4.5 for parse, Sonnet 5 for
tailoring — Sonnet 5 because it supports structured outputs).

## 2. Repository layout

```
job-finder/
├── BUILD_SPEC.md            # this file (also copy to CLAUDE.md)
├── docker-compose.yml
├── .env.example             # copy to .env and fill
├── Caddyfile
├── db/
│   └── schema.sql           # reference schema; real migrations via Alembic
├── api/                     # FastAPI + Celery (one image, multiple commands)
│   ├── Dockerfile
│   ├── Dockerfile.browser   # Playwright base image for the browser worker
│   ├── pyproject.toml
│   ├── alembic/
│   └── app/
│       ├── main.py          # FastAPI app + routers
│       ├── bot.py           # Telegram bot service (long-poll, buttons, /jobs, LLM chat)
│       ├── config.py        # pydantic-settings
│       ├── db.py            # async engine/session
│       ├── auth.py          # JWT, current_user dependency, password hashing
│       ├── seed.py          # seed first user; admin "create user" helper/CLI
│       ├── constants.py     # FIELD_OPTIONS (see §4)
│       ├── models/          # SQLAlchemy models
│       ├── schemas/         # Pydantic DTOs
│       ├── routers/         # auth, users(admin), profile, cvs, jobs, applications, searches, settings, credentials
│       ├── services/
│       │   ├── llm.py            # provider layer (structured JSON + plain text)
│       │   ├── embeddings.py     # sentence-transformers, pgvector helpers
│       │   ├── relevance.py      # hard filters + per-user cosine ranking
│       │   ├── tailoring.py      # CV + cover letter generation
│       │   ├── cv_render.py      # HTML→PDF (WeasyPrint): CV + cover letter
│       │   ├── cv_parse.py       # uploaded CV → structured profile
│       │   ├── linkedin_resolve.py # LinkedIn post -> employer's direct apply link
│       │   ├── throttle.py       # polite pacing + human-like Playwright context
│       │   └── notify.py         # Telegram sends (messages, documents), per-user
│       ├── connectors/      # discovery sources (pluggable)
│       │   ├── base.py           # Connector ABC -> normalized Job dicts
│       │   ├── greenhouse.py     # public board JSON API
│       │   ├── lever.py          # public postings API
│       │   ├── ashby.py          # public job board API
│       │   ├── gov_portals.py    # Jadarat / Qiwa / Taqat (national portals)
│       │   ├── email_alerts.py   # IMAP: parse Bayt/Indeed/LinkedIn alert emails
│       │   ├── company_site.py   # careers pages (+ render.careers for JS portals)
│       │   ├── bayt.py           # human-paced (optional)
│       │   └── linkedin.py       # paced guest API, DISCOVERY ONLY
│       ├── tasks/           # Celery tasks
│       │   ├── celery_app.py
│       │   ├── discovery.py      # upsert jobs -> embed -> match -> Telegram job cards
│       │   ├── tailor.py         # CV/letter PDFs -> saved + sent over Telegram
│       │   ├── render.py         # browser-worker: render JS careers pages (discovery)
│       │   ├── email_watch.py    # IMAP confirmations -> auto-mark submitted
│       │   └── schedule.py       # Beat entries
│       └── tests/
└── web/                     # Next.js app
    ├── Dockerfile
    ├── package.json
    └── src/
        ├── app/             # /login /dashboard /jobs /applications/[id] /profile /cvs /searches /settings /admin/users
        ├── components/      # KanbanBoard, ApplicationCard, AnswerBankForm, FieldSelect, CvUploader, JobTable
        └── lib/             # api client, auth, types
```

## 3. Data model (multi-user)

Concrete DDL in `db/schema.sql`. Key points:

- **app_user** — `email, hashed_password, display_name, is_admin`. First user seeded
  from env (admin); admin creates up to ~3 total. Registration is closed by default.
- **answer_bank** — one row **per user**: `field` (their job field, see §4),
  Saudi-national identity fields, salaries (nullable), structured master profile,
  writing-style samples, and a per-user profile `embedding`.
- **cv_versions**, **saved_searches** — per user.
- **jobs** — shared, deduplicated catalog with a **job** `embedding`. No per-user data.
- **job_matches** — per-user relevance: `(user_id, job_id, relevance_score)`. This is
  what powers each user's ranked feed.
- **applications** — per user; `UNIQUE(user_id, job_id)` so two users can each apply to
  the same job independently.
- **application_events** — per-application timeline; drives notifications.

`status` enum (deliberately small): `discovered, ready, submitted, interview,
offer, rejected` — `ready` means the tailored documents exist.

## 4. The "field" per user (selectable or free text)

Each user sets a **field** in their answer bank. The UI renders a `FieldSelect`:
a dropdown of common options plus **"Other…" → free text**. Store the final value as
free text in `answer_bank.field`. Seed `app/constants.py` with `FIELD_OPTIONS`:

```
Software Engineering, Data & AI, IT & Cybersecurity, Finance & Accounting,
Banking, Project & Program Management, Civil Engineering, Mechanical Engineering,
Electrical Engineering, Oil, Gas & Energy, Healthcare & Medical, Human Resources,
Sales & Business Development, Marketing & Communications, Supply Chain & Logistics,
Legal, Education & Training, Government & Public Sector, Hospitality & Tourism, Other
```

The field is used three ways: it seeds the default saved-search query, weights hard
filters, and is included in the profile text that gets embedded for relevance.

## 5. How relevance works (per user)

1. User uploads a CV → `cv_parse` (Haiku, structured output) seeds the master profile;
   **the user confirms/edits it** — the answer bank, not the raw CV, is the truth.
2. Discovery upserts each posting once into the shared `jobs` catalog and embeds the
   **job** text.
3. For every **enabled user**: apply that user's hard filters (location in KSA / Riyadh
   / Jeddah / Dammam / NEOM / remote-KSA, seniority, salary floor, include/exclude
   keywords, and their field) → for survivors compute cosine similarity between the
   **user profile embedding** and the **job embedding** → upsert `job_matches`.
4. UI ranks by `relevance_score`; above a threshold, auto-create an `applications` row
   in `discovered` for that user; the rest stay browsable in their jobs feed.

## 6. Saudi-national answer bank (replace expat/Iqama fields)

`answer_bank.data` (jsonb) should hold, at minimum: full name (Arabic + English),
**National ID**, date of birth, city / National Address, nationality (default
"Saudi"), phone, email, LinkedIn, years of experience, education, certifications,
notice period, current salary (nullable), expected salary (nullable). **No visa or
Iqama fields.** Because the users are Saudi nationals, discovery should also surface
**Saudization-linked roles** and the **national portals (Jadarat, Qiwa, Taqat)**,
where nationals have an advantage.

## 7. Application flow (Telegram-first)

Discovery tracks a strong match (`discovered`) and messages it to the user on
Telegram with buttons → user taps 📄/✉️/📄+✉️ → `tailor` task (gpt-4o-mini)
generates the documents, renders PDFs, saves them on the application, sends them
back over Telegram (→ `ready`) → the user opens the job link, applies manually,
uploads the PDFs → taps “✅ I applied” (or the `email_watch` task spots the ATS
confirmation email) → `submitted` + `application_events` + notify. The user (or
future emails) later flips it to `interview`/`offer`/`rejected`. The web page per
job shows the extracted description, the saved documents (regenerate buttons live
inside each document's box), notes, and the timeline.

## 8. ATS optimization rules (enforce in cv_render)
Single column. No tables, text boxes, headers/footers, or images. Standard headings
(Experience, Education, Skills). Real selectable text (never an image-PDF). Mirror the
job's exact skill/keyword terms only where true of the candidate. Compute and display
a keyword-coverage %.

## 9. Build plan for Claude Code — do these in order

**Phase 0 — Skeleton & infra.** Scaffold the repo above; write `docker-compose.yml`
(provided), `Caddyfile`, `.env.example`, the three Dockerfiles. FastAPI `/health`,
Next.js login page, Postgres+pgvector up, Alembic initialized from `db/schema.sql`.
Goal: `docker compose up` brings all services healthy and web reaches the API.

**Phase 1 — Auth, users, profile, CVs, tracking.** Multi-user JWT; seed first user;
admin "create user" route + `/admin/users` page (cap at 3). Per-user answer-bank form
incl. `FieldSelect`. CV upload + `cv_parse` seeding. Applications CRUD + kanban with
drag-to-change status + manual add. *Useful on its own.*

**Phase 2 — Discovery + per-user relevance.** Connector ABC + `greenhouse`, `lever`,
`ashby`, `gov_portals`, `email_alerts`. `embeddings` + pgvector. `relevance` (filters +
per-user cosine → `job_matches`). `discovery` Celery task + Beat. Ranked jobs feed.

**Phase 3 — Tailoring.** `llm` + prompts. `tailoring` (Sonnet) → structured CV JSON +
cover letter, constrained to that user's answer-bank data, using their style samples.
`cv_render` (WeasyPrint, ATS rules) → PDF. Preview + keyword-coverage % in UI.

**Phase 4 — Telegram bot.** `app.bot` long-polling service: job cards with
inline buttons (tailor CV/letter, ✅ I applied, 🙈 skip, 🔗 apply link), /jobs,
/status, LLM chat fallback. Tailored PDFs delivered in-chat.

**Phase 5 — Notifications & timeline.** `notify` (per-user Telegram). `application_events`
timeline; emit + notify on submit/status change. `email_watch` auto-marks
submitted from ATS confirmation emails.

**Phase 6 — Bayt/LinkedIn (human-paced) + deploy.** Optional `bayt`/`linkedin`
connectors, low velocity, randomized delays, discovery only. Harden, runbook,
deploy via compose behind Caddy.

> **2026-07 pivot note:** the original Phase 4 (per-ATS pre-fill appliers +
> browser-agent auto-submit) was built, then removed — per-platform form
> automation was too brittle to trust. Do not reintroduce it. The product is
> discovery + on-demand tailored documents + manual apply, driven from Telegram.

### Working agreement for Claude Code
- Commit after every phase; keep phases independently runnable.
- Match SQLAlchemy models to `db/schema.sql`, then generate Alembic migrations.
- Enforce per-user isolation everywhere: every query is scoped by `current_user`
  (and in the bot, by the chat's bound user).
- pytest for `relevance`, connectors (mock HTTP), field-mapping, and auth isolation.
- All secrets in `.env`; never hardcode. See `.env.example` for the list.
- Connectors are plugins implementing their ABC so new sources are drop-in.
