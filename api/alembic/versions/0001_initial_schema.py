"""initial schema (reproduces db/schema.sql)

Multi-user, Saudi-nationals job-finder schema: pgvector + uuid-ossp extensions,
the application_status enum, and all base tables/indexes. This migration is the
authoritative re-creation of db/schema.sql (which is also mounted into Postgres'
initdb for fresh dev volumes).

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-06-18
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    op.execute(
        """
        CREATE TYPE application_status AS ENUM (
            'discovered', 'drafting', 'ready_to_submit',
            'submitted', 'interview', 'offer', 'rejected', 'withdrawn'
        )
        """
    )

    op.execute(
        """
        CREATE TABLE app_user (
            id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            email           TEXT UNIQUE NOT NULL,
            hashed_password TEXT NOT NULL,
            display_name    TEXT,
            is_admin        BOOLEAN NOT NULL DEFAULT false,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE answer_bank (
            id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id    UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
            field      TEXT,
            data       JSONB NOT NULL DEFAULT '{}'::jsonb,
            embedding  vector(384),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (user_id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE cv_versions (
            id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id           UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
            label             TEXT NOT NULL,
            original_filename TEXT,
            file_path         TEXT NOT NULL,
            parsed            JSONB,
            is_default        BOOLEAN NOT NULL DEFAULT false,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE saved_searches (
            id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id     UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
            name        TEXT NOT NULL,
            platform    TEXT NOT NULL,
            query       TEXT,
            filters     JSONB NOT NULL DEFAULT '{}'::jsonb,
            enabled     BOOLEAN NOT NULL DEFAULT true,
            last_run_at TIMESTAMPTZ
        )
        """
    )

    op.execute(
        """
        CREATE TABLE jobs (
            id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            source        TEXT NOT NULL,
            external_id   TEXT NOT NULL,
            title         TEXT NOT NULL,
            company       TEXT,
            location      TEXT,
            url           TEXT NOT NULL,
            description   TEXT,
            posted_at     TIMESTAMPTZ,
            raw           JSONB,
            embedding     vector(384),
            discovered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (source, external_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX jobs_embedding_idx ON jobs USING hnsw (embedding vector_cosine_ops)"
    )

    op.execute(
        """
        CREATE TABLE job_matches (
            id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id         UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
            job_id          UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            relevance_score DOUBLE PRECISION NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (user_id, job_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX job_matches_user_score_idx ON job_matches(user_id, relevance_score DESC)"
    )

    op.execute(
        """
        CREATE TABLE applications (
            id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id           UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
            job_id            UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            cv_version_id     UUID REFERENCES cv_versions(id) ON DELETE SET NULL,
            status            application_status NOT NULL DEFAULT 'discovered',
            tailored_cv_path  TEXT,
            cover_letter      TEXT,
            prefilled_answers JSONB NOT NULL DEFAULT '{}'::jsonb,
            missing_fields    JSONB NOT NULL DEFAULT '[]'::jsonb,
            keyword_coverage  DOUBLE PRECISION,
            screenshot_path   TEXT,
            submitted_at      TIMESTAMPTZ,
            notes             TEXT,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (user_id, job_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX applications_user_status_idx ON applications(user_id, status)"
    )

    op.execute(
        """
        CREATE TABLE application_events (
            id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            application_id UUID NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
            type           TEXT NOT NULL,
            payload        JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX application_events_app_idx ON application_events(application_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS application_events")
    op.execute("DROP TABLE IF EXISTS applications")
    op.execute("DROP TABLE IF EXISTS job_matches")
    op.execute("DROP TABLE IF EXISTS jobs")
    op.execute("DROP TABLE IF EXISTS saved_searches")
    op.execute("DROP TABLE IF EXISTS cv_versions")
    op.execute("DROP TABLE IF EXISTS answer_bank")
    op.execute("DROP TABLE IF EXISTS app_user")
    op.execute("DROP TYPE IF EXISTS application_status")
