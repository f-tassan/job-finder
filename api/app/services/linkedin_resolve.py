"""Resolve a LinkedIn posting to its real (offsite) company application URL.

LinkedIn jobs come in two flavors:

  * **Easy Apply** — the form lives on linkedin.com; the user applies there
    themselves. Resolution returns kind ``"easyapply"`` and no URL.
  * **Offsite apply** — "Apply" bounces the candidate to the employer's own ATS
    (Greenhouse / Lever / Workday / SuccessFactors / Oracle / a careers page).
    Resolving it hands the user a direct link to the employer's real form (the
    🔗 button on Telegram job messages), skipping the LinkedIn login-wall.
    Resolution returns kind ``"offsite"`` and the external ``companyApplyUrl``.

The external URL is only exposed to a logged-in member, so resolution needs the
user's own LinkedIn cookie (``li_at`` + ``JSESSIONID``), stored as a
``PortalCredential`` under host ``linkedin.com`` (the user pastes it once in
Settings). Reading the apply URL with the user's own session is *discovery*,
not automation **on** LinkedIn — we never act there.

The resolved URL is cached on ``job.raw["apply_url"]`` so we resolve each posting
at most once.
"""
from __future__ import annotations

import logging
import re
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job, PortalCredential
from app.services.crypto import decrypt

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)
_VOYAGER = "https://www.linkedin.com/voyager/api/jobs/jobPostings/{job_id}"
_DECORATION = "com.linkedin.voyager.deco.jobs.web.shared.WebFullJobPosting-65"


def is_linkedin_url(url: str | None) -> bool:
    return "linkedin.com" in (url or "").lower()


def extract_job_id(value: str | None) -> str | None:
    """Pull the numeric LinkedIn job id from a URL or our ``linkedin:<id>``
    external_id. Tolerates the slugged ``/jobs/view/<title>-<id>`` form and the
    ``currentJobId=<id>`` query param used by the search UI."""
    if not value:
        return None
    m = re.search(r"currentJobId=(\d+)", value)
    if m:
        return m.group(1)
    m = re.search(r"/jobs/view/(?:[^/?#]*?-)?(\d{6,})", value)
    if m:
        return m.group(1)
    # external_id like "linkedin:4428125825" or a bare id; take the longest run.
    nums = re.findall(r"\d{6,}", value)
    return max(nums, key=len) if nums else None


def _csrf_from_cookie(cookie: str) -> str | None:
    """Voyager requires the ``csrf-token`` header to equal the JSESSIONID cookie
    value (quotes stripped)."""
    m = re.search(r'JSESSIONID=(?:")?([^";]+)(?:")?', cookie)
    return m.group(1) if m else None


def parse_apply_method(payload: dict) -> tuple[str | None, str | None]:
    """Map a Voyager jobPosting payload to ``(kind, url)``:
    ``("offsite", url)`` / ``("offsite", None)`` / ``("easyapply", None)`` /
    ``(None, None)`` when the shape is unrecognized."""
    apply_method = (payload or {}).get("applyMethod") or {}
    for key, val in apply_method.items():
        if "OffsiteApply" in key:
            url = (val or {}).get("companyApplyUrl")
            return ("offsite", url or None)
        if "OnsiteApply" in key or "EasyApply" in key:
            return ("easyapply", None)
    return (None, None)


async def resolve_via_voyager(
    job_id: str, cookie: str
) -> tuple[str | None, str | None]:
    """Call the member Voyager API with the user's cookie. Returns the same
    ``(kind, url)`` as :func:`parse_apply_method`; ``(None, None)`` on any
    HTTP/parse failure (caller treats that as "couldn't resolve")."""
    headers = {
        "cookie": cookie,
        "csrf-token": _csrf_from_cookie(cookie) or "",
        "accept": "application/json",
        "x-restli-protocol-version": "2.0.0",
        "user-agent": _UA,
    }
    # LinkedIn is the most ban-aggressive host — pace member-API calls firmly.
    from app.services.throttle import pace_host

    await pace_host("www.linkedin.com", min_gap=10.0, jitter=8.0)
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(
                _VOYAGER.format(job_id=job_id),
                params={"decorationId": _DECORATION},
                headers=headers,
            )
    except Exception:  # noqa: BLE001 - network error
        logger.exception("voyager resolve %s failed", job_id)
        return (None, None)
    # 401/403 (and LinkedIn's 999 anti-bot) mean the session is rejected — almost
    # always an expired/invalid cookie. Signal "auth" so the caller can nudge the
    # user to paste a fresh one, rather than silently treating it as unresolved.
    if resp.status_code in (401, 403, 999):
        logger.warning(
            "voyager resolve %s -> HTTP %s (cookie expired/invalid)",
            job_id,
            resp.status_code,
        )
        return ("auth", None)
    if resp.status_code != 200:
        logger.warning("voyager resolve %s -> HTTP %s", job_id, resp.status_code)
        return (None, None)
    try:
        return parse_apply_method(resp.json())
    except Exception:  # noqa: BLE001 - non-JSON body
        # A 200 that isn't JSON is usually the login/authwall page served to a
        # logged-out session — also an expired cookie.
        body = (resp.text or "").lower()
        if "authwall" in body or "session_redirect" in body or "/uas/login" in body:
            logger.warning("voyager resolve %s -> authwall (cookie expired)", job_id)
            return ("auth", None)
        logger.exception("voyager resolve %s: bad JSON", job_id)
        return (None, None)


async def linkedin_cookie_for_user(
    session: AsyncSession, user_id: uuid.UUID
) -> str | None:
    """The user's stored LinkedIn session cookie (decrypted), or None."""
    row = (
        await session.execute(
            select(PortalCredential).where(
                PortalCredential.user_id == user_id,
                PortalCredential.host.in_(("linkedin.com", "www.linkedin.com")),
            )
        )
    ).scalars().first()
    if row is None:
        return None
    return decrypt(row.secret) or None


async def resolve_apply_target(
    session: AsyncSession, user_id: uuid.UUID, job: Job
) -> tuple[str | None, str, str | None]:
    """Resolve where an application form actually lives for ``job``.

    Returns ``(target_url, kind, note)``:
      * non-LinkedIn job           -> ``(job.url, "direct", None)``
      * LinkedIn, offsite apply    -> ``(external_url, "offsite", None)``
      * LinkedIn, Easy Apply       -> ``(None, "easyapply", note)``
      * LinkedIn, unresolved/no cookie -> ``(None, "unresolved", note)``

    On a successful offsite resolve the URL is cached into ``job.raw`` so we never
    hit Voyager twice for the same posting. ``note`` is a human-facing
    explanation for the cases we deliberately can't automate.
    """
    if not is_linkedin_url(job.url) and (job.source or "").lower() != "linkedin":
        return (job.url, "direct", None)

    raw = job.raw or {}
    cached = raw.get("apply_url")
    if cached:
        return (cached, "offsite", None)
    if raw.get("apply_kind") == "easyapply":
        return (None, "easyapply", _EASYAPPLY_NOTE)

    cookie = await linkedin_cookie_for_user(session, user_id)
    if not cookie:
        return (None, "unresolved", _NO_COOKIE_NOTE)

    job_id = extract_job_id(job.url) or extract_job_id(job.external_id)
    if not job_id:
        return (None, "unresolved", _NO_ID_NOTE)

    kind, url = await resolve_via_voyager(job_id, cookie)
    if kind == "offsite" and url:
        # Cache the resolved destination (reassign for JSONB change-tracking).
        job.raw = {**raw, "apply_url": url, "apply_kind": "offsite"}
        return (url, "offsite", None)
    if kind == "offsite":
        # Offsite, but LinkedIn didn't expose the company URL (rare).
        return (None, "unresolved", _OFFSITE_NO_URL_NOTE)
    if kind == "easyapply":
        job.raw = {**raw, "apply_kind": "easyapply"}
        return (None, "easyapply", _EASYAPPLY_NOTE)
    if kind == "auth":
        return (None, "auth", _AUTH_NOTE)
    return (None, "unresolved", _UNRESOLVED_NOTE)


_EASYAPPLY_NOTE = (
    "⚠ This is a LinkedIn Easy Apply posting — the form lives on LinkedIn. Open "
    "the posting and apply there, then tap “✅ I applied”."
)
_NO_COOKIE_NOTE = (
    "⚠ To get direct employer apply links for LinkedIn jobs, save your LinkedIn "
    "session cookie in Settings → LinkedIn session cookie. Without it LinkedIn "
    "hides the company application link behind its login."
)
_AUTH_NOTE = (
    "🔐 Your LinkedIn session cookie has expired — refresh it in Settings → "
    "LinkedIn session cookie (copy it from your browser the same way as before)."
)
_NO_ID_NOTE = "⚠ Couldn't read a LinkedIn job id from this posting to resolve its apply link."
_OFFSITE_NO_URL_NOTE = (
    "⚠ LinkedIn says this is an external application but didn't expose the company "
    "URL. Open the posting and click Apply to continue on the employer's site."
)
_UNRESOLVED_NOTE = (
    "⚠ Couldn't resolve this posting's application link (the saved cookie may "
    "have expired). Re-save your LinkedIn cookie, or apply via the posting link."
)
