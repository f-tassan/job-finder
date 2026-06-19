"""Per-user portal credentials: the user's OWN logins to employer ATS sites.

The user pre-creates an account on each company's Workday/SuccessFactors/Taleo
and stores it here; the prefill task uses it to sign in and save a draft. The
password is encrypted at rest (Fernet) and never returned by the API — list/get
only ever expose host + username + label.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.db import get_session
from app.models import AppUser, PortalCredential
from app.schemas import PortalCredentialOut, PortalCredentialUpsert
from app.services.credentials import tenant_key
from app.services.crypto import encrypt

router = APIRouter(prefix="/credentials", tags=["credentials"])


@router.get("", response_model=list[PortalCredentialOut])
async def list_credentials(
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[PortalCredential]:
    rows = (
        await session.execute(
            select(PortalCredential)
            .where(PortalCredential.user_id == user.id)
            .order_by(PortalCredential.host)
        )
    ).scalars().all()
    return list(rows)


@router.put("", response_model=PortalCredentialOut)
async def upsert_credential(
    body: PortalCredentialUpsert,
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> PortalCredential:
    # Accept a full job URL or a bare host; store the normalized tenant host.
    host = tenant_key(body.host) or body.host.strip().lower()
    if not host:
        raise HTTPException(status_code=422, detail="could not parse a host")
    row = (
        await session.execute(
            select(PortalCredential).where(
                PortalCredential.user_id == user.id,
                PortalCredential.host == host,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = PortalCredential(user_id=user.id, host=host)
        session.add(row)
    row.username = body.username
    row.secret = encrypt(body.password)
    row.label = body.label
    await session.commit()
    await session.refresh(row)
    return row


@router.delete("/{cred_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    cred_id: uuid.UUID,
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    row = await session.get(PortalCredential, cred_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="credential not found")
    await session.delete(row)
    await session.commit()
