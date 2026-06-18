# job-finder — Build Specification

> Source of truth for building the app. Keep at repo root, copy to `CLAUDE.md` so
> Claude Code reads it every session, and build **phase by phase** (commit per phase).

## 0. What we are building

A private, **multi-user** (designed for ~3 users, seeded with one) system for the
**Saudi Arabia** job market, for **Saudi nationals**, that:

1. **Discovers** relevant jobs from Saudi sources on a schedule.
2. **Ranks** them per user (hard filters + semantic similarity to that user's profile).
3. **Tailors** an ATS-safe CV + cover letter per job (natural, never fabricated).
4. **Pre-fills** application forms from each user's "answer bank", leaving
   unknown/sensitive fields (e.g. expected salary) **blank** for the human.
5. Routes every application through a **review queue**; the human does the final submit.
6. **Notifies** that user the moment something is submitted.
7. Gives each user a **dashboard**: kanban of applications with editable status
   (discovered → drafting → ready → submitted → interview → offer → rejected),
   CV upload/versioning, and an answer-bank editor that includes their **field**.

Each user is fully isolated: their own profile, field, CVs, saved searches, matches,
applications, and notifications. The job catalog itself is shared (deduplicated), but
**relevance and applications are per user.**

### Hard design rules — read before writing code
- **No fully-automatic submission, especially to LinkedIn.** LinkedIn's User Agreement
  prohibits automated access and enforcement is aggressive; auto-submit risks a
  permanent ban. Automate everything *up to* submission. LinkedIn & Bayt: discovery +
  pre-fill only, the human submits. Standalone ATS forms (Greenhouse, Lever, Ashby,
  Workday): pre-fill and finalize only on the user's confirmation.
- **Never invent qualifications** during tailoring — only data in that user's answer
  bank / parsed CV may be used.
- Sensitive fields (expected/current salary, free-text "why this company") default to
  **blank** until the user fills them at review.

## 1. Tech stack (do not substitute without reason)

| Layer            | Choice                                                              |
|------------------|---------------------------------------------------------------------|
| Backend API      | Python 3.12, **FastAPI**, Pydantic v2, SQLAlchemy 2.0 (async), Alembic |
| Task queue       | **Celery** + Redis broker; **Celery Beat** for scheduling           |
| Browser worker   | **Playwright (Python)** in its own container/queue                  |
| Database         | **PostgreSQL 16** + **pgvector**                                    |
| Embeddings       | `sentence-transformers` (`all-MiniLM-L6-v2`, 384-dim, local & free); pluggable to Voyage |
| LLM              | **Anthropic Claude API** (`anthropic` Python SDK)                   |
| CV rendering     | **WeasyPrint** (HTML→PDF, ATS-safe) + optional `python-docx`        |
| Frontend         | **Next.js 14** (App Router), TypeScript, Tailwind, **shadcn/ui**, TanStack Query, react-hook-form + zod, dnd-kit (kanban) |
| Auth             | **Multi-user** JWT; first user seeded from env; admin adds the rest |
| File storage     | Docker volume, served through the authed API (per-user paths)       |
| Notifications    | **Telegram bot** (per-user chat id) + optional SMTP/email           |
| Reverse proxy    | **Caddy** (automatic HTTPS)                                         |
| Deployment       | **Docker Compose**, single VPS                                     |

### Claude model routing (verified June 2026 — pin these strings)
- `claude-haiku-4-5-20251001` — cheap/high-volume: CV parsing, relevance pre-screen, field mapping.
- `claude-sonnet-4-6` — default for quality: CV tailoring, cover letters, natural writing.
- `claude-opus-4-8` — reserve for unusually hard tailoring only.
Use the SDK's structured outputs for JSON-returning calls. Verify strings at
https://docs.claude.com/en/docs/about-claude/models/overview before deploy.

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
│       ├── config.py        # pydantic-settings
│       ├── db.py            # async engine/session
│       ├── auth.py          # JWT, current_user dependency, password hashing
│       ├── seed.py          # seed first user; admin "create user" helper/CLI
│       ├── constants.py     # FIELD_OPTIONS (see §4)
│       ├── models/          # SQLAlchemy models
│       ├── schemas/         # Pydantic DTOs
│       ├── routers/         # auth, users(admin), profile, cvs, jobs, applications, searches, settings
│       ├── services/
│       │   ├── llm.py            # Anthropic client + prompts
│       │   ├── embeddings.py     # sentence-transformers, pgvector helpers
│       │   ├── relevance.py      # hard filters + per-user cosine ranking
│       │   ├── tailoring.py      # CV + cover letter generation
│       │   ├── cv_render.py      # HTML→PDF (WeasyPrint), docx
│       │   ├── cv_parse.py       # uploaded CV → structured profile
│       │   └── notify.py         # Telegram/email, per-user
│       ├── connectors/      # discovery sources (pluggable)
│       │   ├── base.py           # Connector ABC -> normalized Job dicts
│       │   ├── greenhouse.py     # public board JSON API
│       │   ├── lever.py          # public postings API
│       │   ├── ashby.py          # public job board API
│       │   ├── gov_portals.py    # Jadarat / Qiwa / Taqat (national portals)
│       │   ├── email_alerts.py   # IMAP: parse Bayt/Indeed/LinkedIn alert emails
│       │   ├── bayt.py           # Playwright, human-paced (optional)
│       │   └── linkedin.py       # Playwright, human-paced, DISCOVERY ONLY
│       ├── appliers/        # form pre-fill adapters (Playwright)
│       │   ├── base.py           # Applier ABC -> fill known, flag missing
│       │   ├── greenhouse.py
│       │   ├── lever.py
│       │   └── generic.py        # heuristic label-matching fallback
│       ├── tasks/           # Celery tasks
│       │   ├── celery_app.py
│       │   ├── discovery.py      # upsert global jobs -> embed -> per-user match/score
│       │   ├── tailor.py         # build CV + cover letter for an application
│       │   ├── prefill.py        # browser-worker: pre-fill a form, save state
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

`status` enum: `discovered, drafting, ready_to_submit, submitted, interview, offer,
rejected, withdrawn`.

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

## 7. Application flow (review queue)

`discovered` → select → `tailor` (ATS CV + cover letter) → `drafting` → `prefill`
(browser-worker: fill known fields from answer bank, leave unknown/sensitive blank,
record `missing_fields`, screenshot) → `ready_to_submit` → user reviews at
`/applications/[id]`, completes gaps, submits (LinkedIn/Bayt: user submits in their own
browser; standalone ATS: dashboard finalizes on confirm) → `application_events` →
`notify` that user → `submitted`. User later flips to `interview`/`offer`/`rejected`.

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

**Phase 4 — Pre-fill / review queue.** Applier ABC + `greenhouse`/`lever`/`generic`.
`prefill` task on browser-worker. Application detail page: review, complete gaps,
submit/confirm.

**Phase 5 — Notifications & timeline.** `notify` (per-user Telegram). `application_events`
timeline; emit + notify on submit/status change.

**Phase 6 — Bayt/LinkedIn (human-paced) + deploy.** Optional `bayt`/`linkedin`
connectors in the user's real local browser, low velocity, randomized delays,
discovery only. Harden, runbook, deploy via compose behind Caddy.

### Working agreement for Claude Code
- Commit after every phase; keep phases independently runnable.
- Match SQLAlchemy models to `db/schema.sql`, then generate Alembic migrations.
- Enforce per-user isolation everywhere: every query is scoped by `current_user`.
- pytest for `relevance`, connectors (mock HTTP), field-mapping, and auth isolation.
- All secrets in `.env`; never hardcode. See `.env.example` for the list.
- Connectors/appliers are plugins implementing their ABC so new sources are drop-in.
