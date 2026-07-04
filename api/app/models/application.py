"""Per-user applications and their event timeline."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum as SAEnum
from sqlalchemy import Float, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ApplicationStatus(str, enum.Enum):
    """Deliberately small: discovered -> ready (tailored docs generated) ->
    submitted (user applied) -> interview -> offer / rejected."""

    discovered = "discovered"
    ready = "ready"
    submitted = "submitted"
    interview = "interview"
    offer = "offer"
    rejected = "rejected"


# Map to the existing PG enum type; do not let SQLAlchemy try to create it.
application_status_enum = SAEnum(
    ApplicationStatus,
    name="application_status",
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("user_id", "job_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    cv_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cv_versions.id", ondelete="SET NULL")
    )
    status: Mapped[ApplicationStatus] = mapped_column(
        application_status_enum, nullable=False, default=ApplicationStatus.discovered
    )
    tailored_cv_path: Mapped[str | None] = mapped_column(Text)
    cover_letter: Mapped[str | None] = mapped_column(Text)
    cover_letter_path: Mapped[str | None] = mapped_column(Text)  # rendered PDF
    keyword_coverage: Mapped[float | None] = mapped_column(Float)
    submitted_at: Mapped[datetime | None] = mapped_column()
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    job: Mapped["Job"] = relationship(lazy="joined")  # noqa: F821
    events: Mapped[list["ApplicationEvent"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="ApplicationEvent.created_at",
    )
    documents: Mapped[list["ApplicationDocument"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="ApplicationDocument.kind, ApplicationDocument.version",
    )

    @property
    def has_tailored_cv(self) -> bool:
        return bool(self.tailored_cv_path)

    @property
    def has_cover_letter_pdf(self) -> bool:
        return bool(self.cover_letter_path)


class ApplicationDocument(Base):
    """One generated version of a tailored document (CV or cover letter). Each
    tailor/regenerate run appends a new row so every version is kept and
    browsable; the Application's tailored_cv_path/cover_letter(_path) mirror the
    LATEST version for the existing single-file download + preview paths."""

    __tablename__ = "application_documents"
    __table_args__ = (
        UniqueConstraint("application_id", "kind", "version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # "cv" | "cover_letter"
    version: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-based per kind
    file_path: Mapped[str | None] = mapped_column(Text)  # rendered PDF
    text: Mapped[str | None] = mapped_column(Text)  # cover-letter body (display)
    keyword_coverage: Mapped[float | None] = mapped_column(Float)  # cv only
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    application: Mapped[Application] = relationship(back_populates="documents")

    @property
    def has_pdf(self) -> bool:
        return bool(self.file_path)


class ApplicationEvent(Base):
    __tablename__ = "application_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    application: Mapped[Application] = relationship(back_populates="events")
