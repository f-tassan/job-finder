"""Per-user notifications (Telegram).

Each user stores their own Telegram chat id in their notification settings; the
bot token is a single shared server secret (TELEGRAM_BOT_TOKEN). All sends are
best-effort and never raise into the caller — a failed notification must not
break a task or request.

Inbound traffic (commands, button taps) is handled exclusively by the bot
service (`app.bot`) — nothing here may call getUpdates, or the two consumers
would steal each other's updates.
"""
from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import AnswerBank

logger = logging.getLogger(__name__)

_API = "https://api.telegram.org/bot{token}/{method}"


async def send_telegram(
    chat_id: str,
    text: str,
    *,
    reply_markup: dict | None = None,
    parse_mode: str | None = None,
) -> bool:
    """Send a message. `reply_markup` is a Telegram InlineKeyboardMarkup dict
    (e.g. {"inline_keyboard": [[{"text": ..., "callback_data": ...}]]})."""
    token = settings.telegram_bot_token
    if not token or not chat_id:
        return False
    payload: dict = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                _API.format(token=token, method="sendMessage"), json=payload
            )
            return resp.status_code == 200
    except Exception:  # noqa: BLE001 - notifications are best-effort
        logger.exception("telegram send failed")
        return False


async def send_telegram_document(
    chat_id: str,
    file_path: str,
    *,
    filename: str | None = None,
    caption: str | None = None,
) -> bool:
    """Send a file (e.g. a tailored CV PDF) to the chat."""
    token = settings.telegram_bot_token
    if not token or not chat_id:
        return False
    path = Path(file_path)
    if not path.is_file():
        logger.warning("telegram document missing: %s", file_path)
        return False
    data: dict = {"chat_id": chat_id}
    if caption:
        data["caption"] = caption
    try:
        with path.open("rb") as fh:
            files = {"document": (filename or path.name, fh, "application/pdf")}
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    _API.format(token=token, method="sendDocument"),
                    data=data,
                    files=files,
                )
        return resp.status_code == 200
    except Exception:  # noqa: BLE001 - notifications are best-effort
        logger.exception("telegram sendDocument failed")
        return False


async def chat_id_for_user(session: AsyncSession, user_id: uuid.UUID) -> str | None:
    """The user's Telegram chat id, if notifications are enabled and configured."""
    bank = (
        await session.execute(
            select(AnswerBank).where(AnswerBank.user_id == user_id)
        )
    ).scalar_one_or_none()
    if bank is None:
        return None
    prefs = bank.notifications or {}
    if not prefs.get("enabled", True):
        return None
    chat_id = prefs.get("telegram_chat_id")
    return str(chat_id) if chat_id else None


async def notify_user(
    session: AsyncSession,
    user_id: uuid.UUID,
    text: str,
    *,
    reply_markup: dict | None = None,
    parse_mode: str | None = None,
) -> bool:
    """Send `text` to a user's configured channel(s). No-op if unconfigured."""
    chat_id = await chat_id_for_user(session, user_id)
    if not chat_id:
        return False
    return await send_telegram(
        chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode
    )


async def notify_user_document(
    session: AsyncSession,
    user_id: uuid.UUID,
    file_path: str,
    *,
    filename: str | None = None,
    caption: str | None = None,
) -> bool:
    chat_id = await chat_id_for_user(session, user_id)
    if not chat_id:
        return False
    return await send_telegram_document(
        chat_id, file_path, filename=filename, caption=caption
    )


async def notify_user_throttled(
    session: AsyncSession,
    user_id: uuid.UUID,
    text: str,
    *,
    key: str,
    ttl_seconds: int,
) -> bool:
    """Like `notify_user`, but sends at most once per `ttl_seconds` for a given
    `key` (e.g. an expired-cookie nudge). The last-sent timestamp is persisted in
    the user's notification prefs so a burst of failing jobs yields one message,
    not dozens. Best-effort: storage failures fall back to sending."""
    bank = (
        await session.execute(
            select(AnswerBank).where(AnswerBank.user_id == user_id)
        )
    ).scalar_one_or_none()
    if bank is None:
        return False
    prefs = dict(bank.notifications or {})
    throttle = dict(prefs.get("_throttle") or {})
    now = int(time.time())
    last = throttle.get(key)
    if isinstance(last, (int, float)) and now - last < ttl_seconds:
        return False
    throttle[key] = now
    prefs["_throttle"] = throttle
    bank.notifications = prefs  # reassign for JSONB change-tracking
    try:
        await session.commit()
    except Exception:  # noqa: BLE001 - don't let bookkeeping block the nudge
        await session.rollback()
    return await notify_user(session, user_id, text)
