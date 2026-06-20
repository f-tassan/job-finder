"""Browser-worker task: actually submit an application form end to end.

This is the ONE place that performs a real submission, and it runs only when the
user explicitly triggers it (POST /applications/{id}/auto-submit) — never from
the automatic discovery/auto-apply pipeline. Per CLAUDE.md this is allowed for
standalone ATS forms ("pre-fill and finalize only on the user's confirmation")
and must never be used for LinkedIn/Bayt.

Flow: open the form → fill known fields (and sign in if a credential is stored)
→ click the final submit button → look for a confirmation → screenshot → record
the outcome. If a confirmation can't be detected, the application is left in
`ready_to_submit` for the human to finish, and we say so.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path

from sqlalchemy import select

from app.appliers.base import candidate_values, get_applier
from app.config import settings
from app.db import SessionLocal
from app.models import (
    AnswerBank,
    Application,
    ApplicationEvent,
    ApplicationStatus,
    CvVersion,
    Job,
)
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# LinkedIn/Bayt must never be auto-submitted (hard rule).
_BLOCKED_HOSTS = ("linkedin.com", "bayt.com")

# Text that signals the portal accepted the application.
_CONFIRM_MARKERS = (
    "thank you for applying",
    "thank you for your application",
    "application received",
    "application has been received",
    "application has been submitted",
    "we have received your application",
    "successfully submitted",
    "your application was submitted",
    "thank you for your interest",
)

# Text that signals the portal demands an emailed verification/OTP code before it
# will accept the application (e.g. Greenhouse "verified applications"). The
# throwaway headless browser can't read the user's inbox, so we can't pass this —
# we stop, leave the app unsent, and tell the human to finish it themselves.
_VERIFY_MARKERS = (
    "verification code",
    "verify your email",
    "confirm you're a human",
    "confirm you are a human",
    "code was sent",
    "sent a code",
    "enter the code",
    "enter the 6",
    "check your email",
)


async def _submit(app_id: uuid.UUID) -> dict:
    async with SessionLocal() as session:
        app = await session.get(Application, app_id)
        if app is None:
            return {"error": "application not found"}
        job = await session.get(Job, app.job_id)
        url = (job.url or "").lower()
        if any(h in url for h in _BLOCKED_HOSTS):
            return {"error": "auto-submit is not allowed for this portal"}

        bank = (
            await session.execute(
                select(AnswerBank).where(AnswerBank.user_id == app.user_id)
            )
        ).scalar_one_or_none()
        values = candidate_values((bank.data if bank else {}) or {})
        applier = get_applier(job.source, job.url)

        from app.services.credentials import credentials_for_url

        credentials = await credentials_for_url(session, app.user_id, job.url)

        # CV to attach: the application's tailored CV if present, else the user's
        # default CV version. Shared `files` volume → readable by the worker.
        cv_path: str | None = app.tailored_cv_path
        if not cv_path:
            default_cv = (
                await session.execute(
                    select(CvVersion)
                    .where(CvVersion.user_id == app.user_id)
                    .order_by(CvVersion.is_default.desc(), CvVersion.created_at.desc())
                )
            ).scalars().first()
            cv_path = default_cv.file_path if default_cv else None
        if cv_path and not Path(cv_path).exists():
            cv_path = None

        shot_path = str(
            Path(settings.files_dir) / str(app.user_id) / "submit" / f"{app.id}.png"
        )
        Path(shot_path).parent.mkdir(parents=True, exist_ok=True)

        prefill = {"filled": {}, "missing": []}
        cv_attached = False
        clicked = False
        confirmed = False
        needs_verification = False
        otp_asked = False
        otp_code_received = False
        error: str | None = None

        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--no-sandbox"])
            try:
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                    )
                )
                page = await context.new_page()
                try:
                    await page.goto(
                        job.url, wait_until="domcontentloaded", timeout=45000
                    )
                    await page.wait_for_timeout(1200)
                    prefill = await applier.prefill(
                        page,
                        values,
                        credentials=credentials,
                        save_draft=False,
                        # Re-apply what the human reviewed/completed (salary,
                        # "why this company", verified answers) so the one-click
                        # finalize submits a complete form, not a blank one.
                        overrides=app.prefilled_answers or {},
                    )
                    if prefill.get("needs_credentials"):
                        error = "portal requires a login that isn't stored"
                    else:
                        if cv_path:
                            cv_attached = await applier.attach_cv(page, cv_path)
                        clicked = await applier.submit(page)
                        await page.wait_for_timeout(1500)
                        try:
                            body = ((await page.content()) or "").lower()
                            confirmed = clicked and any(
                                m in body for m in _CONFIRM_MARKERS
                            )
                            needs_verification = (
                                clicked
                                and not confirmed
                                and any(m in body for m in _VERIFY_MARKERS)
                            )
                        except Exception:  # noqa: BLE001
                            confirmed = False

                        # OTP relay: the portal emailed a code. Ask the user for it
                        # over Telegram and enter it here (browser still open), so
                        # verified portals can actually finish.
                        if needs_verification and settings.telegram_bot_token:
                            from app.services.notify import (
                                chat_id_for_user,
                                send_telegram,
                                wait_for_telegram_code,
                            )

                            chat_id = await chat_id_for_user(session, app.user_id)
                            if chat_id:
                                otp_asked = True
                                ask_ts = int(time.time())
                                mins = max(1, settings.submit_otp_wait_seconds // 60)
                                await send_telegram(
                                    chat_id,
                                    f"🔐 {job.title}: reply here with the verification "
                                    f"code emailed to you to finish submitting "
                                    f"(within {mins} min).",
                                )
                                code = await wait_for_telegram_code(
                                    chat_id, ask_ts, settings.submit_otp_wait_seconds
                                )
                                if code:
                                    otp_code_received = True
                                    if await applier.submit_verification_code(
                                        page, code
                                    ):
                                        body = ((await page.content()) or "").lower()
                                        confirmed = any(
                                            m in body for m in _CONFIRM_MARKERS
                                        )
                                        needs_verification = (not confirmed) and any(
                                            m in body for m in _VERIFY_MARKERS
                                        )
                except Exception as exc:  # noqa: BLE001
                    error = str(exc)[:300]
                    logger.exception("auto-submit navigation/submit failed")
                try:
                    await page.screenshot(path=shot_path, full_page=True)
                    app.screenshot_path = shot_path
                except Exception:  # noqa: BLE001
                    logger.exception("screenshot failed")
            finally:
                await browser.close()

        app.prefilled_answers = prefill.get("filled", {}) or app.prefilled_answers
        app.missing_fields = prefill.get("missing", []) or app.missing_fields
        app.ai_suggested_fields = (
            prefill.get("ai_suggested", []) or app.ai_suggested_fields
        )
        app.needs_credentials = bool(prefill.get("needs_credentials"))

        verify_note = (
            "⚠ This portal emailed you a verification code to finish submitting — "
            "auto-submit can't receive it. Open the posting and submit there "
            "yourself (your answers are filled and the CV is attached)."
        )
        if confirmed:
            from datetime import datetime, timezone

            app.status = ApplicationStatus.submitted
            if app.submitted_at is None:
                app.submitted_at = datetime.now(timezone.utc)
        elif needs_verification:
            # Can't pass an emailed OTP from a throwaway browser — route it to the
            # human with a clear explanation instead of silently failing.
            app.status = ApplicationStatus.needs_attention
            app.missing_fields = [verify_note] + [
                m for m in (app.missing_fields or []) if m != verify_note
            ]
        session.add(
            ApplicationEvent(
                application_id=app.id,
                type=(
                    "submitted_auto"
                    if confirmed
                    else "submit_needs_verification"
                    if needs_verification
                    else "submit_attempt"
                ),
                payload={
                    "applier": applier.name,
                    "cv_attached": cv_attached,
                    "clicked_submit": clicked,
                    "confirmed": confirmed,
                    "needs_verification": needs_verification,
                    "filled": len(prefill.get("filled", {})),
                    "missing": len(prefill.get("missing", [])),
                    "error": error,
                },
            )
        )
        await session.commit()

        from app.services.notify import notify_user

        if confirmed:
            via = (
                " — verified with the code you sent."
                if otp_code_received
                else " — confirmation detected on the portal."
            )
            msg = (
                f"✅ Auto-submitted: {job.title}"
                + (f" at {job.company}" if job.company else "")
                + via
            )
        elif needs_verification:
            if otp_asked and not otp_code_received:
                extra = " I asked for the code on Telegram but didn't get it in time."
            elif otp_code_received:
                extra = " The code didn't go through — please finish in your browser."
            else:
                extra = ""
            msg = (
                f"📧 {job.title}: needs an emailed verification code to submit.{extra} "
                "Open the posting and submit there yourself; everything's filled in."
            )
        elif clicked:
            msg = (
                f"⚠️ Tried to submit {job.title} but couldn't confirm it went "
                "through. Open the posting and check / finish it manually."
            )
        else:
            why = error or "no submit button was found"
            msg = f"⚠️ Couldn't auto-submit {job.title}: {why}. Review it manually."
        await notify_user(session, app.user_id, msg)

    return {
        "application_id": str(app_id),
        "clicked_submit": clicked,
        "confirmed": confirmed,
        "needs_verification": needs_verification,
        "error": error,
    }


@celery_app.task(name="submit.run")
def submit_application(app_id: str) -> dict:
    return asyncio.run(_submit(uuid.UUID(app_id)))
