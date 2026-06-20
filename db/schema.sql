-- job-finder — reference schema (multi-user, Saudi nationals).
-- Real migrations should be managed by Alembic; this is the target shape.

CREATE EXTENSION IF NOT EXISTS vector;        -- pgvector
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TYPE application_status AS ENUM (
    'discovered', 'drafting', 'ready_to_submit',
    'submitted', 'interview', 'offer', 'rejected', 'withdrawn'
);

-- Users (built for ~3; first one seeded from env as admin). Registration closed.
CREATE TABLE app_user (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email           TEXT UNIQUE NOT NULL,
    hashed_password TEXT NOT NULL,
    display_name    TEXT,
    is_admin        BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row PER USER: their field, Saudi-national identity, salaries (nullable),
-- master profile, writing-style samples, and a profile embedding for relevance.
CREATE TABLE answer_bank (
    id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id    UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    field      TEXT,                              -- selectable-or-free-text job field
    data       JSONB NOT NULL DEFAULT '{}'::jsonb, -- national_id, city, education, salaries, etc.
    notifications JSONB NOT NULL DEFAULT '{}'::jsonb, -- telegram_chat_id, enabled, etc.
    embedding  vector(384),                       -- profile embedding (all-MiniLM-L6-v2)
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id)
);

CREATE TABLE cv_versions (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id           UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    label             TEXT NOT NULL,
    original_filename TEXT,
    file_path         TEXT NOT NULL,              -- per-user path on the files volume
    parsed            JSONB,
    is_default        BOOLEAN NOT NULL DEFAULT false,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE saved_searches (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    platform    TEXT NOT NULL,                    -- greenhouse|lever|ashby|gov_portals|email_alerts|bayt|linkedin
    query       TEXT,
    filters     JSONB NOT NULL DEFAULT '{}'::jsonb, -- locations, seniority, salary_floor, include/exclude kw
    enabled     BOOLEAN NOT NULL DEFAULT true,
    last_run_at TIMESTAMPTZ
);

-- Per-user, per-tenant ATS logins (the user's OWN account on each employer's
-- Workday/SuccessFactors/Taleo). secret = Fernet ciphertext, never returned by
-- the API. Used by the prefill task to sign in and save a draft application.
CREATE TABLE portal_credentials (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    host        TEXT NOT NULL,                   -- tenant domain, e.g. acme.wd1.myworkdayjobs.com
    username    TEXT NOT NULL,
    secret      TEXT NOT NULL,                   -- encrypted password (Fernet)
    label       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, host)
);

-- Shared, deduplicated job catalog. No per-user columns here.
CREATE TABLE jobs (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source        TEXT NOT NULL,                  -- connector name
    external_id   TEXT NOT NULL,                  -- id within that source
    title         TEXT NOT NULL,
    company       TEXT,
    location      TEXT,
    url           TEXT NOT NULL,
    description   TEXT,
    posted_at     TIMESTAMPTZ,
    raw           JSONB,
    embedding     vector(384),                    -- job embedding
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, external_id)
);
CREATE INDEX jobs_embedding_idx ON jobs USING hnsw (embedding vector_cosine_ops);

-- Per-user relevance: which jobs matched which user, and how strongly.
CREATE TABLE job_matches (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    job_id          UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    relevance_score DOUBLE PRECISION NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, job_id)
);
CREATE INDEX job_matches_user_score_idx ON job_matches(user_id, relevance_score DESC);

CREATE TABLE applications (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id           UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    job_id            UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    cv_version_id     UUID REFERENCES cv_versions(id) ON DELETE SET NULL,
    status            application_status NOT NULL DEFAULT 'discovered',
    tailored_cv_path  TEXT,
    cover_letter      TEXT,
    prefilled_answers JSONB NOT NULL DEFAULT '{}'::jsonb,
    missing_fields    JSONB NOT NULL DEFAULT '[]'::jsonb,  -- fields the human must complete
    needs_credentials BOOLEAN NOT NULL DEFAULT false,      -- portal login required but not stored
    keyword_coverage  DOUBLE PRECISION,
    screenshot_path   TEXT,
    submitted_at      TIMESTAMPTZ,
    notes             TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, job_id)                       -- one application per user per job
);
CREATE INDEX applications_user_status_idx ON applications(user_id, status);

CREATE TABLE application_events (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    application_id UUID NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    type           TEXT NOT NULL,                  -- created|tailored|prefilled|submitted|status_changed|note
    payload        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX application_events_app_idx ON application_events(application_id, created_at);
