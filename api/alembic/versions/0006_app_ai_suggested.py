"""applications.ai_suggested_fields (answers the human must verify)

JSONB list of field labels whose values were derived by the LLM during pre-fill.
Their values are stored clean in prefilled_answers (no inline marker, so nothing
odd is ever submitted); this list just drives a "Check" flag in the review UI.

Revision ID: 0006_app_ai_suggested
Revises: 0005_app_needs_credentials
Create Date: 2026-06-20
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006_app_ai_suggested"
down_revision: str | None = "0005_app_needs_credentials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE applications "
        "ADD COLUMN IF NOT EXISTS ai_suggested_fields JSONB NOT NULL DEFAULT '[]'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE applications DROP COLUMN IF EXISTS ai_suggested_fields")
