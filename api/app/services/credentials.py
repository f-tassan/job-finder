"""Resolve the right stored portal credential for a job URL.

Enterprise ATS accounts are per-tenant, so the storage key is the URL's host
(e.g. `acme.wd1.myworkdayjobs.com`). The prefill task uses `credentials_for_url`
to fetch and decrypt the user's login for that tenant, if they saved one.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PortalCredential
from app.services.ats_url import tenant_key
from app.services.crypto import decrypt

__all__ = ["tenant_key", "credentials_for_url"]


async def credentials_for_url(
    session: AsyncSession, user_id: uuid.UUID, url: str | None
) -> dict[str, str] | None:
    """Return {'username', 'password'} for the tenant of `url`, or None."""
    host = tenant_key(url)
    if not host:
        return None
    row = (
        await session.execute(
            select(PortalCredential).where(
                PortalCredential.user_id == user_id,
                PortalCredential.host == host,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    password = decrypt(row.secret)
    if not password:
        return None
    return {"username": row.username, "password": password}
