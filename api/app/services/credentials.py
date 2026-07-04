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
    # Prefer a tenant-specific login, then a universal one: a stored host="*" entry
    # (managed in the UI), then the env-configured shared login. The universal login
    # lets the agent sign in / register on any portal with no dedicated credential.
    for h in (host, "*"):
        row = (
            await session.execute(
                select(PortalCredential).where(
                    PortalCredential.user_id == user_id,
                    PortalCredential.host == h,
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            password = decrypt(row.secret)
            if password:
                return {"username": row.username, "password": password}

    from app.config import settings

    if settings.portal_universal_username and settings.portal_universal_password:
        return {
            "username": settings.portal_universal_username,
            "password": settings.portal_universal_password,
        }
    return None
