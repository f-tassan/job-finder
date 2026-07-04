"""Auto-mark applications as submitted from ATS confirmation emails.

Nearly every ATS sends a "thank you for applying" email the moment an
application lands. This Beat task scans the configured IMAP inbox for such
confirmations and matches them to tracked, not-yet-submitted applications by
company (and title) tokens — so an application gets marked *submitted* without
the user touching the web page or even the ✅ button on Telegram.

Matching is deliberately conservative: a message must (a) look like a
confirmation (subject/body phrasing), and (b) name the application's company —
otherwise nothing changes. When several users track the same company, the
recipient address is used to pick the right user; with no address match the
email is skipped (never guess across users).

No-op unless IMAP is configured. Only messages newer than the last scan are
read (UID cursor persisted in Redis).
"""
from __future__ import annotations

import asyncio
import email
import imaplib
import logging
import re
from datetime import datetime, timezone
from email.header import decode_header, make_header

import redis as redis_lib
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import (
    Application,
    ApplicationEvent,
    ApplicationStatus,
    AppUser,
    Job,
)
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

_CURSOR_KEY = "email_watch:last_uid"

# Subject/body phrases that mark an application-received confirmation. Kept
# tight: a recruiter newsletter or a job alert must not match.
_CONFIRM_PATTERNS = (
    "thank you for applying",
    "thanks for applying",
    "thank you for your application",
    "we received your application",
    "we've received your application",
    "we have received your application",
    "your application was sent",
    "your application has been received",
    "your application has been submitted",
    "application received",
    "successfully applied",
    "شكراً لتقديمك",  # "thank you for applying"
    "تم استلام طلبك",  # "your application was received"
)

_TAG_RE = re.compile(r"<[^>]+>")


def _text_of(msg: email.message.Message) -> str:
    """Plain text of the message (subject + best-effort body)."""
    parts: list[str] = [str(make_header(decode_header(msg.get("Subject", ""))))]
    payloads = msg.walk() if msg.is_multipart() else [msg]
    for part in payloads:
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        try:
            body = part.get_payload(decode=True).decode(
                part.get_content_charset() or "utf-8", errors="replace"
            )
        except Exception:  # noqa: BLE001
            continue
        if ctype == "text/html":
            body = _TAG_RE.sub(" ", body)
        parts.append(body)
        if len(" ".join(parts)) > 20000:
            break
    return " ".join(parts)


def _is_confirmation(text: str) -> bool:
    low = text.lower()
    return any(p in low for p in _CONFIRM_PATTERNS)


def _company_tokens(company: str | None) -> list[str]:
    """Distinctive lowercase tokens of a company name ("Saudi Aramco" ->
    ["saudi", "aramco"]); generic words are dropped so "Company Ltd" can't
    match everything."""
    generic = {
        "the", "company", "co", "ltd", "llc", "inc", "group", "holding",
        "international", "saudi", "arabia", "ksa", "and", "of", "for",
    }
    toks = [
        t
        for t in re.split(r"[^\w؀-ۿ]+", (company or "").lower())
        if len(t) >= 3 and t not in generic
    ]
    # If everything was generic (e.g. "Saudi Company"), fall back to the full
    # normalized name so we still require a real mention.
    return toks or ([re.sub(r"\s+", " ", (company or "").lower()).strip()] if company else [])


async def _scan() -> dict:
    if not (settings.imap_host and settings.imap_user and settings.imap_password):
        return {"skipped": "imap not configured"}

    r = redis_lib.from_url(settings.redis_url, decode_responses=True)
    last_uid = int(r.get(_CURSOR_KEY) or 0)

    def _fetch_new() -> tuple[int, list[tuple[str, str]]]:
        """Returns (max_uid, [(recipients, text)]) for messages with UID > cursor."""
        out: list[tuple[str, str]] = []
        max_uid = last_uid
        conn = imaplib.IMAP4_SSL(settings.imap_host)  # type: ignore[arg-type]
        try:
            conn.login(settings.imap_user, settings.imap_password)  # type: ignore[arg-type]
            conn.select(settings.imap_folder)
            typ, data = conn.uid("search", None, f"UID {last_uid + 1}:*")
            if typ != "OK" or not data or not data[0]:
                return max_uid, out
            for uid_b in data[0].split()[-200:]:
                uid = int(uid_b)
                if uid <= last_uid:
                    continue  # servers echo the last UID on "n:*" searches
                max_uid = max(max_uid, uid)
                typ, msg_data = conn.uid("fetch", uid_b, "(RFC822)")
                if typ != "OK" or not msg_data or not msg_data[0]:
                    continue
                msg = email.message_from_bytes(msg_data[0][1])
                recipients = " ".join(
                    str(msg.get(h, "")) for h in ("To", "Cc", "Delivered-To")
                ).lower()
                text = _text_of(msg)
                if _is_confirmation(text):
                    out.append((recipients, text.lower()))
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass
        return max_uid, out

    max_uid, confirmations = await asyncio.to_thread(_fetch_new)
    marked = 0
    if confirmations:
        async with SessionLocal() as session:
            pending = (
                await session.execute(
                    select(Application, Job, AppUser)
                    .join(Job, Job.id == Application.job_id)
                    .join(AppUser, AppUser.id == Application.user_id)
                    .where(
                        Application.status.in_(
                            (ApplicationStatus.discovered, ApplicationStatus.ready)
                        )
                    )
                )
            ).all()
            for recipients, text in confirmations:
                for app, job, user in pending:
                    if app.status == ApplicationStatus.submitted:
                        continue  # already flipped by an earlier email this run
                    toks = _company_tokens(job.company)
                    if not toks or not all(t in text for t in toks):
                        continue
                    # Multi-user safety: if the mail names a recipient, it must
                    # be this applicant.
                    if "@" in recipients and user.email.lower() not in recipients:
                        continue
                    app.status = ApplicationStatus.submitted
                    if app.submitted_at is None:
                        app.submitted_at = datetime.now(timezone.utc)
                    session.add(
                        ApplicationEvent(
                            application_id=app.id,
                            type="submitted",
                            payload={"via": "email_confirmation"},
                        )
                    )
                    marked += 1
                    from app.services.notify import notify_user

                    await notify_user(
                        session,
                        user.id,
                        f"📬 Confirmation email spotted — marked as submitted: "
                        f"{job.title}"
                        + (f" at {job.company}" if job.company else ""),
                    )
            await session.commit()
    if max_uid > last_uid:
        r.set(_CURSOR_KEY, max_uid)
    return {"confirmations": len(confirmations), "marked_submitted": marked}


@celery_app.task(name="email_watch.run")
def watch_confirmations() -> dict:
    result = asyncio.run(_scan())
    logger.info("email_watch: %s", result)
    return result
