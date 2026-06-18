"""Per-user notification settings (Telegram chat id, enable flag) + test send."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.config import settings as app_settings
from app.db import get_session
from app.models import AnswerBank, AppUser
from app.schemas import (
    DiscoveryPrefsOut,
    DiscoveryPrefsUpdate,
    NotificationSettingsOut,
    NotificationSettingsUpdate,
)
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


@router.get("/discovery", response_model=DiscoveryPrefsOut)
async def get_discovery_prefs(
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> DiscoveryPrefsOut:
    bank = await _bank(session, user.id)
    prefs = (bank.prefs if bank else {}) or {}
    return DiscoveryPrefsOut(
        ksa_only=prefs.get("ksa_only", True),
        auto_apply_enabled=prefs.get("auto_apply_enabled", False),
        auto_apply_threshold=prefs.get("auto_apply_threshold", 0.6),
    )


@router.put("/discovery", response_model=DiscoveryPrefsOut)
async def update_discovery_prefs(
    body: DiscoveryPrefsUpdate,
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> DiscoveryPrefsOut:
    prefs = {
        "ksa_only": body.ksa_only,
        "auto_apply_enabled": body.auto_apply_enabled,
        "auto_apply_threshold": body.auto_apply_threshold,
    }
    bank = await _bank(session, user.id)
    if bank is None:
        bank = AnswerBank(user_id=user.id, prefs=prefs)
        session.add(bank)
    else:
        bank.prefs = prefs
    await session.commit()
    return DiscoveryPrefsOut(**prefs)


@router.post("/test")
async def test_notification(
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    sent = await notify.notify_user(
        session, user.id, "✅ job-finder test notification — you're all set."
    )
    return {"sent": sent}
