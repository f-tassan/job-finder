"""Per-user notifications (Telegram).

Each user stores their own Telegram chat id in their notification settings; the
bot token is a single shared server secret (TELEGRAM_BOT_TOKEN). All sends are
best-effort and never raise into the caller — a failed notification must not
break a task or request.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
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


async def notify_user(session: AsyncSession, user_id: uuid.UUID, text: str) -> bool:
    """Send `text` to a user's configured channel(s). No-op if unconfigured."""
    chat_id = await chat_id_for_user(session, user_id)
    if not chat_id:
        return False
    return await send_telegram(chat_id, text)


# --- Inbound: wait for a one-time code the user sends back over Telegram --------

# A verification code from the user's reply. Codes contain a digit, so we require
# one — that filters out English words ("code", "here") in messages like
# "the code is 7321". Prefer a 6-char token (Greenhouse's length).
def _extract_code(text: str) -> str | None:
    text = (text or "").strip()
    if re.fullmatch(r"[A-Za-z0-9]{4,8}", text) and any(c.isdigit() for c in text):
        return text
    cands = [
        m.group(0)
        for m in re.finditer(r"\b[A-Za-z0-9]{4,8}\b", text)
        if any(c.isdigit() for c in m.group(0))
    ]
    if not cands:
        # last resort: a whole-message all-letters code (rare)
        return text if re.fullmatch(r"[A-Za-z]{4,8}", text) else None
    six = [c for c in cands if len(c) == 6]
    return six[0] if six else cands[0]


async def _drain_telegram(r, token: str) -> None:
    """Fetch new Telegram updates and stash each message into a per-chat inbox in
    Redis. Serialized across worker processes by a short lock, and a persisted
    offset means every update is acked exactly once (so no message is lost or
    double-read even when two submits wait at the same time)."""
    if not await r.set("tg:poll:lock", "1", nx=True, ex=20):
        return  # another worker is draining right now
    try:
        params: dict = {"timeout": 0, "allowed_updates": json.dumps(["message"])}
        offset = await r.get("tg:update_offset")
        if offset:
            params["offset"] = int(offset)
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://api.telegram.org/bot{token}/getUpdates", params=params
            )
        if resp.status_code != 200:
            return
        for u in resp.json().get("result", []):
            await r.set("tg:update_offset", u["update_id"] + 1)
            msg = u.get("message") or u.get("edited_message")
            if not msg or not msg.get("text"):
                continue
            cid = str((msg.get("chat") or {}).get("id"))
            entry = json.dumps({"date": int(msg.get("date", 0)), "text": msg["text"]})
            key = f"tg:inbox:{cid}"
            await r.rpush(key, entry)
            await r.ltrim(key, -20, -1)
            await r.expire(key, 900)
    except Exception:  # noqa: BLE001 - best-effort
        logger.exception("telegram getUpdates failed")
    finally:
        await r.delete("tg:poll:lock")


async def wait_for_telegram_code(
    chat_id: str, after_ts: int, timeout: int
) -> str | None:
    """Poll Telegram until `chat_id` sends a code (a message dated >= after_ts that
    looks like a one-time code), or `timeout` seconds elapse. Returns the code."""
    token = settings.telegram_bot_token
    if not token or not chat_id:
        return None
    import redis.asyncio as aioredis

    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            await _drain_telegram(r, token)
            for raw in await r.lrange(f"tg:inbox:{chat_id}", 0, -1):
                try:
                    m = json.loads(raw)
                except Exception:  # noqa: BLE001
                    continue
                if int(m.get("date", 0)) >= after_ts:
                    code = _extract_code(m.get("text", ""))
                    if code:
                        await r.delete(f"tg:inbox:{chat_id}")  # consume
                        return code
            await asyncio.sleep(2.5)
    finally:
        try:
            await r.aclose()
        except Exception:  # noqa: BLE001
            pass
    return None
