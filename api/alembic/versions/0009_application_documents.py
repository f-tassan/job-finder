"""Versioned tailored documents (application_documents).

Every tailor/regenerate run now appends a row here instead of overwriting, so
the user can generate multiple CVs / cover letters per job and review every
version on the web page. The Application's tailored_cv_path / cover_letter(_path)
columns are kept as a mirror of the latest version (existing download +
preview paths use them). Backfills a v1 row from any existing tailored output.

Revision ID: 0009_application_documents
Revises: 0008_telegram_first_pivot
Create Date: 2026-07-04
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_application_documents"
down_revision: str | None = "0008_telegram_first_pivot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "application_documents",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "application_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),  # cv | cover_letter
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.Text()),
        sa.Column("text", sa.Text()),
        sa.Column("keyword_coverage", sa.Float()),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("application_id", "kind", "version"),
    )
    op.create_index(
        "application_documents_app_kind_idx",
        "application_documents",
        ["application_id", "kind", "version"],
    )

    # Backfill v1 from whatever tailored output already exists on each app.
    op.execute(
        """
        INSERT INTO application_documents
            (application_id, kind, version, file_path, keyword_coverage, created_at)
        SELECT id, 'cv', 1, tailored_cv_path, keyword_coverage, updated_at
        FROM applications
        WHERE tailored_cv_path IS NOT NULL
        """
    )
    op.execute(
        """
        INSERT INTO application_documents
            (application_id, kind, version, file_path, text, created_at)
        SELECT id, 'cover_letter', 1, cover_letter_path, cover_letter, updated_at
        FROM applications
        WHERE cover_letter IS NOT NULL OR cover_letter_path IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("application_documents_app_kind_idx", "application_documents")
    op.drop_table("application_documents")
