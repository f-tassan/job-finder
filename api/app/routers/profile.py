"""Per-user answer bank (profile + field). Strictly scoped to current_user."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.constants import FIELD_OPTIONS
from app.db import get_session
from app.models import AnswerBank, AppUser
from app.schemas import AnswerBankOut, AnswerBankUpdate

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("/field-options", response_model=list[str])
async def field_options() -> list[str]:
    return FIELD_OPTIONS


async def _get_bank(session: AsyncSession, user_id) -> AnswerBank | None:
    result = await session.execute(
        select(AnswerBank).where(AnswerBank.user_id == user_id)
    )
    return result.scalar_one_or_none()


@router.get("", response_model=AnswerBankOut)
async def get_profile(
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> AnswerBank | AnswerBankOut:
    bank = await _get_bank(session, user.id)
    if bank is None:
        return AnswerBankOut()  # empty profile until the user fills it
    return bank


@router.put("", response_model=AnswerBankOut)
async def update_profile(
    body: AnswerBankUpdate,
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> AnswerBank:
    bank = await _get_bank(session, user.id)
    if bank is None:
        bank = AnswerBank(user_id=user.id, field=body.field, data=body.data)
        session.add(bank)
    else:
        bank.field = body.field
        bank.data = body.data
    await session.commit()
    await session.refresh(bank)
    return bank
