"""Per-user notifications (Telegram).

Each user stores their own Telegram chat id in their notification settings; the
bot token is a single shared server secret (TELEGRAM_BOT_TOKEN). All sends are
best-effort and never raise into the caller — a failed notification must not
break a task or request.
"""
from __future__ import annotations

import logging
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import AnswerBank

logger = logging.getLogger(__name__)


async def send_telegram(chat_id: str, text: str) -> bool:
    token = settings.telegram_bot_token
    if not token or not chat_id:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            )
            return resp.status_code == 200
    except Exception:  # noqa: BLE001 - notifications are best-effort
        logger.exception("telegram send failed")
        return False


async def notify_user(session: AsyncSession, user_id: uuid.UUID, text: str) -> bool:
    """Send `text` to a user's configured channel(s). No-op if unconfigured."""
    bank = (
        await session.execute(
            select(AnswerBank).where(AnswerBank.user_id == user_id)
        )
    ).scalar_one_or_none()
    if bank is None:
        return False
    prefs = bank.notifications or {}
    if not prefs.get("enabled", True):
        return False
    chat_id = prefs.get("telegram_chat_id")
    if not chat_id:
        return False
    return await send_telegram(str(chat_id), text)
