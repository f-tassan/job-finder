"""Per-user skipped jobs (job_skips).

Tapping 🙈 Skip in Telegram deleted the tracked application and nothing else, so
the next discovery run saw an unseen job, re-tracked it, and sent the same "new
job discovered" card again. A skip now leaves a durable row here that discovery
and /jobs both honour.

Revision ID: 0010_job_skips
Revises: 0009_application_documents
Create Date: 2026-07-15
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_job_skips"
down_revision: str | None = "0009_application_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_skips",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app_user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("user_id", "job_id"),
    )
    op.create_index("job_skips_user_idx", "job_skips", ["user_id"])


def downgrade() -> None:
    op.drop_index("job_skips_user_idx", "job_skips")
    op.drop_table("job_skips")
