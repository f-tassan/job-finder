"""answer_bank.prefs (discovery / auto-apply preferences)

JSONB column for per-user discovery prefs: ksa_only, auto_apply_enabled,
auto_apply_threshold. Separate from `data` (answer bank) and `notifications`.

Revision ID: 0003_answer_bank_prefs
Revises: 0002_answer_bank_notifications
Create Date: 2026-06-18
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003_answer_bank_prefs"
down_revision: str | None = "0002_answer_bank_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE answer_bank "
        "ADD COLUMN IF NOT EXISTS prefs JSONB NOT NULL DEFAULT '{}'::jsonb"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE answer_bank DROP COLUMN IF EXISTS prefs")
