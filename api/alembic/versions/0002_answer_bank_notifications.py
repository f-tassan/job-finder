"""answer_bank.notifications (per-user notification prefs)

Adds a JSONB column holding per-user notification settings (e.g. Telegram chat
id, enabled flag). Kept separate from `data` so saving the profile form never
clobbers notification settings.

Revision ID: 0002_answer_bank_notifications
Revises: 0001_initial_schema
Create Date: 2026-06-18
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_answer_bank_notifications"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE answer_bank "
        "ADD COLUMN IF NOT EXISTS notifications JSONB NOT NULL DEFAULT '{}'::jsonb"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE answer_bank DROP COLUMN IF EXISTS notifications")
