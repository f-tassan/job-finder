"""User-owned models: app_user, answer_bank, cv_versions, saved_searches.

The pgvector `embedding` columns from db/schema.sql are intentionally omitted
here (added in Phase 2 with the embeddings service); they are nullable in the DB.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class AppUser(Base):
    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    answer_bank: Mapped["AnswerBank | None"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    cv_versions: Mapped[list["CvVersion"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class AnswerBank(Base):
    __tablename__ = "answer_bank"
    __table_args__ = (UniqueConstraint("user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    field: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    notifications: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384))
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[AppUser] = relationship(back_populates="answer_bank")


class CvVersion(Base):
    __tablename__ = "cv_versions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str | None] = mapped_column(Text)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    parsed: Mapped[dict | None] = mapped_column(JSONB)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    user: Mapped[AppUser] = relationship(back_populates="cv_versions")


class SavedSearch(Base):
    __tablename__ = "saved_searches"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    query: Mapped[str | None] = mapped_column(Text)
    filters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column()
