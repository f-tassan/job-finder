"""Politeness / anti-throttling layer for DISCOVERY — make every automated read
look human so we never get rate-limited or banned for bot behaviour.

Two tools, all best-effort (never raise into the caller):

1. `pace_host(url)` — space out requests to a host. Backed by Redis so ALL
   workers cooperate: each call reserves the next "slot", at least a randomized
   gap after the previous one, and sleeps until then. Used by careers-page
   rendering and the LinkedIn apply-link resolver.
2. `new_human_context(browser)` + `LAUNCH_ARGS` — a realistic, non-headless-
   looking Playwright context (real UA, viewport, locale, timezone, webdriver
   masked) to reduce automation fingerprinting.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from urllib.parse import urlparse

import redis as _redis

from app.config import settings

logger = logging.getLogger(__name__)

# Reserve the next polite slot for a host atomically across workers: the slot is
# max(now, stored_next); we bump stored_next by `gap`. Returns the slot time.
_NEXT_SLOT_LUA = """
local cur = tonumber(redis.call('GET', KEYS[1]) or '0')
local now = tonumber(ARGV[1])
local gap = tonumber(ARGV[2])
local slot = now
if cur > now then slot = cur end
redis.call('SET', KEYS[1], slot + gap, 'EX', 3600)
return tostring(slot)
"""

_client = None


def _redis_client():
    global _client
    if _client is None:
        _client = _redis.from_url(settings.celery_broker_url)
    return _client


def host_of(url: str | None) -> str:
    """The bare host of a URL (no scheme/port, no leading www.)."""
    if not url:
        return ""
    netloc = urlparse(url).netloc.lower()
    if not netloc:
        netloc = urlparse("//" + url).netloc.lower()
    host = netloc.split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


async def pace_host(
    url: str | None,
    *,
    min_gap: float = 6.0,
    jitter: float = 5.0,
    max_wait: float = 90.0,
) -> None:
    """Block until it's polite to hit `url`'s host again — at least
    `min_gap + rand(0, jitter)` seconds after the previous access by any worker.
    No-op if Redis is unavailable (falls back to a small random pause)."""
    host = host_of(url)
    if not host:
        return
    gap = min_gap + random.uniform(0, jitter)
    wait = 0.0
    try:
        slot = float(
            _redis_client().eval(
                _NEXT_SLOT_LUA, 1, f"throttle:host:{host}", repr(time.time()), repr(gap)
            )
        )
        wait = slot - time.time()
    except Exception:  # noqa: BLE001 - never let pacing break the task
        logger.debug("pace_host redis failed; using local jitter", exc_info=True)
        wait = random.uniform(0, jitter)
    if wait > 0:
        await asyncio.sleep(min(wait, max_wait))


# --- Human-like Playwright context -----------------------------------------

# A pool of current, realistic desktop UAs (rotated per context).
_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like "
    "Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36",
]

# Chromium launch args that reduce "I'm an automated browser" signals.
LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
]

# Hide the most-checked automation tells before any page script runs.
_STEALTH_JS = (
    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
    "window.chrome=window.chrome||{runtime:{}};"
    "Object.defineProperty(navigator,'languages',{get:()=>['en-US','en']});"
    "Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});"
)


async def new_human_context(browser, **extra):
    """A Playwright context that looks like a normal desktop browser: realistic
    UA, viewport, locale, timezone, and the webdriver flag masked."""
    ctx = await browser.new_context(
        user_agent=random.choice(_UA_POOL),
        viewport={"width": 1366, "height": 768},
        locale="en-US",
        timezone_id="Asia/Riyadh",
        **extra,
    )
    try:
        await ctx.add_init_script(_STEALTH_JS)
    except Exception:  # noqa: BLE001
        logger.debug("stealth init script failed", exc_info=True)
    return ctx
