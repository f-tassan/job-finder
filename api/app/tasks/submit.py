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

        shot_path = str(
            Path(settings.files_dir) / str(app.user_id) / "submit" / f"{app.id}.png"
        )
        Path(shot_path).parent.mkdir(parents=True, exist_ok=True)

        prefill = {"filled": {}, "missing": []}
        clicked = False
        confirmed = False
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
                    )
                    if prefill.get("needs_credentials"):
                        error = "portal requires a login that isn't stored"
                    else:
                        clicked = await applier.submit(page)
                        await page.wait_for_timeout(1500)
                        try:
                            body = (await page.content()) or ""
                            confirmed = clicked and any(
                                m in body.lower() for m in _CONFIRM_MARKERS
                            )
                        except Exception:  # noqa: BLE001
                            confirmed = False
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
        app.needs_credentials = bool(prefill.get("needs_credentials"))
        if confirmed:
            from datetime import datetime, timezone

            app.status = ApplicationStatus.submitted
            if app.submitted_at is None:
                app.submitted_at = datetime.now(timezone.utc)
        session.add(
            ApplicationEvent(
                application_id=app.id,
                type="submitted_auto" if confirmed else "submit_attempt",
                payload={
                    "applier": applier.name,
                    "clicked_submit": clicked,
                    "confirmed": confirmed,
                    "filled": len(prefill.get("filled", {})),
                    "missing": len(prefill.get("missing", [])),
                    "error": error,
                },
            )
        )
        await session.commit()

        from app.services.notify import notify_user

        if confirmed:
            msg = (
                f"✅ Auto-submitted: {job.title}"
                + (f" at {job.company}" if job.company else "")
                + " — confirmation detected on the portal."
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
        "error": error,
    }


@celery_app.task(name="submit.run")
def submit_application(app_id: str) -> dict:
    return asyncio.run(_submit(uuid.UUID(app_id)))
