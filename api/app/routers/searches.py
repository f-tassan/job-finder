"""Per-user saved searches (drive discovery). Scoped to current_user."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.db import get_session
from app.models import AppUser, SavedSearch
from app.schemas import SavedSearchCreate, SavedSearchOut, SavedSearchUpdate

router = APIRouter(prefix="/searches", tags=["searches"])

PLATFORMS = {"greenhouse", "lever", "ashby", "gov_portals", "email_alerts"}


async def _owned(session: AsyncSession, user_id, search_id) -> SavedSearch:
    s = await session.get(SavedSearch, search_id)
    if s is None or s.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return s


@router.get("", response_model=list[SavedSearchOut])
async def list_searches(
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[SavedSearch]:
    result = await session.execute(
        select(SavedSearch)
        .where(SavedSearch.user_id == user.id)
        .order_by(SavedSearch.name)
    )
    return list(result.scalars().all())


@router.post("", response_model=SavedSearchOut, status_code=status.HTTP_201_CREATED)
async def create_search(
    body: SavedSearchCreate,
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> SavedSearch:
    if body.platform not in PLATFORMS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown platform. Allowed: {sorted(PLATFORMS)}",
        )
    s = SavedSearch(
        user_id=user.id,
        name=body.name,
        platform=body.platform,
        query=body.query,
        filters=body.filters,
        enabled=body.enabled,
    )
    session.add(s)
    await session.commit()
    await session.refresh(s)
    return s


@router.patch("/{search_id}", response_model=SavedSearchOut)
async def update_search(
    search_id: uuid.UUID,
    body: SavedSearchUpdate,
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> SavedSearch:
    s = await _owned(session, user.id, search_id)
    if body.name is not None:
        s.name = body.name
    if body.query is not None:
        s.query = body.query
    if body.filters is not None:
        s.filters = body.filters
    if body.enabled is not None:
        s.enabled = body.enabled
    await session.commit()
    await session.refresh(s)
    return s


@router.delete("/{search_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_search(
    search_id: uuid.UUID,
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    s = await _owned(session, user.id, search_id)
    await session.delete(s)
    await session.commit()
