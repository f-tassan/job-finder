"""application_status: add 'needs_attention'

A kanban stage between drafting and ready_to_submit for applications the pipeline
prepared but couldn't fully finish (error, login required, nothing fillable, or
genuine unfilled required fields). The human opens these, fixes the gaps, and
advances them to ready_to_submit.

Revision ID: 0007_status_needs_attention
Revises: 0006_app_ai_suggested
Create Date: 2026-06-20
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007_status_needs_attention"
down_revision: str | None = "0006_app_ai_suggested"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # PG16 allows ADD VALUE in a transaction (the value just can't be used until
    # this migration's transaction commits — nothing here uses it).
    op.execute(
        "ALTER TYPE application_status "
        "ADD VALUE IF NOT EXISTS 'needs_attention' BEFORE 'ready_to_submit'"
    )


def downgrade() -> None:
    # Postgres cannot drop a single enum value; leaving it is harmless.
    pass
