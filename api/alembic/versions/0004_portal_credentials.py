"""portal_credentials (per-user, per-tenant encrypted ATS logins)

Stores the user's own login to each employer ATS (Workday/SuccessFactors/Taleo),
keyed by host. `secret` is a Fernet ciphertext, never returned by the API. Used
by the prefill task to sign in and save a draft application.

Revision ID: 0004_portal_credentials
Revises: 0003_answer_bank_prefs
Create Date: 2026-06-20
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004_portal_credentials"
down_revision: str | None = "0003_answer_bank_prefs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS portal_credentials (
            id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id    UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
            host       TEXT NOT NULL,
            username   TEXT NOT NULL,
            secret     TEXT NOT NULL,
            label      TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (user_id, host)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS portal_credentials")
