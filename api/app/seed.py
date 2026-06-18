"""Seed the first (admin) user from env, and a helper to create additional users.

Registration is closed; the admin creates the other users (capped at MAX_USERS).
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import hash_password
from app.config import settings
from app.db import SessionLocal
from app.models import AppUser


async def create_user(
    session: AsyncSession,
    email: str,
    password: str,
    display_name: str | None = None,
    is_admin: bool = False,
) -> AppUser:
    user = AppUser(
        email=email.lower(),
        hashed_password=hash_password(password),
        display_name=display_name,
        is_admin=is_admin,
    )
    session.add(user)
    await session.flush()
    return user


async def seed_first_user() -> None:
    """Create the seeded admin if there are no users yet. Idempotent."""
    if not settings.first_user_email or not settings.first_user_password:
        return
    async with SessionLocal() as session:
        count = await session.scalar(select(func.count()).select_from(AppUser))
        if count and count > 0:
            return
        await create_user(
            session,
            email=settings.first_user_email,
            password=settings.first_user_password,
            display_name="Admin",
            is_admin=True,
        )
        await session.commit()
