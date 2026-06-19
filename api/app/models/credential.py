"""Per-user, per-portal ATS credentials (encrypted at rest).

Enterprise ATS accounts are per-employer-tenant (each company's Workday /
SuccessFactors / Taleo is a separate site with its own login), so credentials
are keyed by `host` (the tenant's domain). The password is stored as a Fernet
ciphertext in `secret`; it is never returned by the API. Used by the prefill
task to log into the user's own account and save a draft application.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PortalCredential(Base):
    __tablename__ = "portal_credentials"
    __table_args__ = (UniqueConstraint("user_id", "host"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    host: Mapped[str] = mapped_column(Text, nullable=False)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    secret: Mapped[str] = mapped_column(Text, nullable=False)  # Fernet ciphertext
    label: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
