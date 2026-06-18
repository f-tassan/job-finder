"""Per-user notification settings (Telegram chat id, enable flag) + test send."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.config import settings as app_settings
from app.db import get_session
from app.models import AnswerBank, AppUser
from app.schemas import NotificationSettingsOut, NotificationSettingsUpdate
from app.services import notify

router = APIRouter(prefix="/settings", tags=["settings"])


async def _bank(session: AsyncSession, user_id) -> AnswerBank | None:
    return (
        await session.execute(select(AnswerBank).where(AnswerBank.user_id == user_id))
    ).scalar_one_or_none()


@router.get("", response_model=NotificationSettingsOut)
async def get_settings(
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> NotificationSettingsOut:
    bank = await _bank(session, user.id)
    prefs = (bank.notifications if bank else {}) or {}
    return NotificationSettingsOut(
        telegram_chat_id=prefs.get("telegram_chat_id"),
        enabled=prefs.get("enabled", True),
        telegram_configured=bool(app_settings.telegram_bot_token),
    )


@router.put("", response_model=NotificationSettingsOut)
async def update_settings(
    body: NotificationSettingsUpdate,
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> NotificationSettingsOut:
    bank = await _bank(session, user.id)
    prefs = {
        "telegram_chat_id": body.telegram_chat_id or None,
        "enabled": body.enabled,
    }
    if bank is None:
        bank = AnswerBank(user_id=user.id, notifications=prefs)
        session.add(bank)
    else:
        bank.notifications = prefs
    await session.commit()
    return NotificationSettingsOut(
        telegram_chat_id=prefs["telegram_chat_id"],
        enabled=prefs["enabled"],
        telegram_configured=bool(app_settings.telegram_bot_token),
    )


@router.post("/test")
async def test_notification(
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    sent = await notify.notify_user(
        session, user.id, "✅ job-finder test notification — you're all set."
    )
    return {"sent": sent}
