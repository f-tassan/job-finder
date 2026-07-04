"""Per-user encrypted secrets, keyed by host.

Today the only stored secret is the user's LinkedIn session cookie (host
``linkedin.com``), which the resolver uses to read the real employer apply link
behind a LinkedIn posting. The secret is a Fernet ciphertext; it is never
returned by the API.
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
