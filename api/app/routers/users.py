"""Admin user management. Registration is closed; the admin adds users (capped)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_admin
from app.config import settings
from app.db import get_session
from app.models import AppUser
from app.schemas import UserCreate, UserOut
from app.seed import create_user

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut])
async def list_users(
    _: AppUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
) -> list[AppUser]:
    result = await session.execute(select(AppUser).order_by(AppUser.created_at))
    return list(result.scalars().all())


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def add_user(
    body: UserCreate,
    _: AppUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
) -> AppUser:
    count = await session.scalar(select(func.count()).select_from(AppUser))
    if count is not None and count >= settings.max_users:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User cap reached (max {settings.max_users})",
        )
    try:
        user = await create_user(
            session,
            email=body.email,
            password=body.password,
            display_name=body.display_name,
            is_admin=body.is_admin,
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already exists"
        )
    await session.refresh(user)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    admin: AppUser = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
):
    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own account",
        )
    user = await session.get(AppUser, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    await session.delete(user)
    await session.commit()
