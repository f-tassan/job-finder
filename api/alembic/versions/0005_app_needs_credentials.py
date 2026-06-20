"""applications.needs_credentials (portal login required but not stored)

Boolean flag set by the prefill task when a job's portal required a login but the
user had no stored credential (or login failed). Drives the kanban "needs login"
badge + Retry.

Revision ID: 0005_app_needs_credentials
Revises: 0004_portal_credentials
Create Date: 2026-06-20
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005_app_needs_credentials"
down_revision: str | None = "0004_portal_credentials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE applications "
        "ADD COLUMN IF NOT EXISTS needs_credentials BOOLEAN NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE applications DROP COLUMN IF EXISTS needs_credentials")
