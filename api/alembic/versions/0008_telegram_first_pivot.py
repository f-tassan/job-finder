"""Telegram-first pivot: simplify statuses, drop pre-fill columns, add letter PDF.

The auto-apply pipeline (pre-fill / browser submit) is gone. Applications now
move discovered -> ready (tailored docs generated) -> submitted -> interview ->
offer / rejected, so the enum shrinks and the pre-fill bookkeeping columns
(prefilled_answers, missing_fields, ai_suggested_fields, needs_credentials,
screenshot_path) are dropped. The cover letter now also gets rendered to a PDF
(sent over Telegram), stored at cover_letter_path.

Revision ID: 0008_telegram_first_pivot
Revises: 0007_status_needs_attention
Create Date: 2026-07-04
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_telegram_first_pivot"
down_revision: str | None = "0007_status_needs_attention"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW = ("discovered", "ready", "submitted", "interview", "offer", "rejected")
_OLD = (
    "discovered",
    "drafting",
    "needs_attention",
    "ready_to_submit",
    "submitted",
    "interview",
    "offer",
    "rejected",
    "withdrawn",
)


def _swap_enum(target: tuple[str, ...], mapping: dict[str, str]) -> None:
    """Replace application_status with a new value set, remapping rows. Postgres
    can't remove enum values, so: rename old type -> create new -> cast the
    column through a CASE -> drop old type."""
    op.execute("ALTER TYPE application_status RENAME TO application_status_old")
    op.execute(
        "CREATE TYPE application_status AS ENUM ({})".format(
            ", ".join(f"'{v}'" for v in target)
        )
    )
    cases = " ".join(
        f"WHEN '{old}' THEN '{new}'::application_status"
        for old, new in mapping.items()
    )
    op.execute("ALTER TABLE applications ALTER COLUMN status DROP DEFAULT")
    op.execute(
        "ALTER TABLE applications ALTER COLUMN status TYPE application_status "
        f"USING (CASE status::text {cases} "
        "ELSE 'discovered'::application_status END)"
    )
    op.execute(
        "ALTER TABLE applications ALTER COLUMN status "
        "SET DEFAULT 'discovered'::application_status"
    )
    op.execute("DROP TYPE application_status_old")


def upgrade() -> None:
    _swap_enum(
        _NEW,
        {
            "discovered": "discovered",
            # drafting meant "tailoring ran"; ready_to_submit meant "pre-filled".
            # Both collapse into the new ready (docs generated) stage.
            "drafting": "ready",
            "ready_to_submit": "ready",
            "needs_attention": "discovered",
            "submitted": "submitted",
            "interview": "interview",
            "offer": "offer",
            "rejected": "rejected",
            "withdrawn": "rejected",
        },
    )
    op.add_column("applications", sa.Column("cover_letter_path", sa.Text()))
    op.drop_column("applications", "prefilled_answers")
    op.drop_column("applications", "missing_fields")
    op.drop_column("applications", "ai_suggested_fields")
    op.drop_column("applications", "needs_credentials")
    op.drop_column("applications", "screenshot_path")


def downgrade() -> None:
    _swap_enum(
        _OLD,
        {
            "discovered": "discovered",
            "ready": "ready_to_submit",
            "submitted": "submitted",
            "interview": "interview",
            "offer": "offer",
            "rejected": "rejected",
        },
    )
    op.drop_column("applications", "cover_letter_path")
    op.add_column(
        "applications",
        sa.Column(
            "prefilled_answers",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
    )
    op.add_column(
        "applications",
        sa.Column(
            "missing_fields",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
    )
    op.add_column(
        "applications",
        sa.Column(
            "ai_suggested_fields",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
    )
    op.add_column(
        "applications",
        sa.Column(
            "needs_credentials",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column("applications", sa.Column("screenshot_path", sa.Text()))
