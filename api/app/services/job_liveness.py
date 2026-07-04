"""Check whether a job posting is still live, so discovery can prune removed
ones from the catalog and each user's board.

Deliberately CONSERVATIVE: `is_removed` returns True only on strong, positive
signals that a posting is gone (HTTP 404/410, or LinkedIn's explicit "No longer
accepting applications"). Any ambiguity — timeouts, 200s, 403/999 anti-bot,
network errors — returns False, so a transient hiccup never deletes a valid job.
Manual (user-added) jobs and jobs without a URL are never pruned.
"""
from __future__ import annotations

import logging

import httpx

from app.services.linkedin_resolve import extract_job_id, is_linkedin_url
from app.services.throttle import pace_host

logger = logging.getLogger(__name__)

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    )
}
_LI_GUEST = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"
# LinkedIn renders this exact phrase on a closed posting's guest page.
_LI_CLOSED = "no longer accepting applications"


async def _linkedin_removed(job) -> bool:
    jid = extract_job_id(job.url) or extract_job_id(job.external_id)
    if not jid:
        return False
    # LinkedIn is the most ban-aggressive host — pace liveness checks too.
    await pace_host("www.linkedin.com", min_gap=6.0, jitter=4.0)
    try:
        async with httpx.AsyncClient(
            timeout=15, follow_redirects=True, headers=_UA
        ) as client:
            r = await client.get(_LI_GUEST.format(id=jid))
    except Exception:  # noqa: BLE001 - network error: never treat as removed
        logger.debug("linkedin liveness failed for %s", jid, exc_info=True)
        return False
    if r.status_code in (404, 410):
        return True
    if r.status_code == 200 and _LI_CLOSED in (r.text or "").lower():
        return True
    return False


async def is_removed(job) -> bool:
    """True only when the posting is confidently gone; False on any doubt."""
    url = (job.url or "").strip()
    src = (job.source or "").lower()
    if not url or src == "manual":
        return False
    if src == "linkedin" or is_linkedin_url(url):
        return await _linkedin_removed(job)
    # ATS / company careers pages: a removed posting 404s (Greenhouse, Lever,
    # Ashby, most careers sites). Only 404/410 counts as removed.
    try:
        async with httpx.AsyncClient(
            timeout=15, follow_redirects=True, headers=_UA
        ) as client:
            r = await client.get(url)
    except Exception:  # noqa: BLE001
        logger.debug("liveness check failed for %s", url, exc_info=True)
        return False
    return r.status_code in (404, 410)
