"""Browser-worker task: open an application form, pre-fill known fields from the
answer bank, flag the gaps, screenshot, and move the application to
`ready_to_submit`. Never submits — the human does that at review.

Runs on the `browser` queue (Playwright). Playwright is imported lazily so the
non-browser worker can still import this module for task registration.
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
    CvVersion,
    Job,
)
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _prefill(app_id: uuid.UUID) -> dict:
    async with SessionLocal() as session:
        app = await session.get(Application, app_id)
        if app is None:
            return {"error": "application not found"}
        job = await session.get(Job, app.job_id)
        bank = (
            await session.execute(
                select(AnswerBank).where(AnswerBank.user_id == app.user_id)
            )
        ).scalar_one_or_none()
        data = (bank.data if bank else {}) or {}
        values = candidate_values(data)
        applier = get_applier(job.source, job.url)

        # If the user saved a login for this employer portal, sign in and save a
        # draft on their account (never submit). Otherwise just rehearse-fill.
        from app.services.credentials import credentials_for_url

        credentials = await credentials_for_url(session, app.user_id, job.url)

        shot_path = str(
            Path(settings.files_dir) / str(app.user_id) / "prefill" / f"{app.id}.png"
        )
        Path(shot_path).parent.mkdir(parents=True, exist_ok=True)

        result = {"filled": {}, "missing": []}
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
                        job.url, wait_until="domcontentloaded", timeout=30000
                    )
                    await page.wait_for_timeout(1000)
                    result = await applier.prefill(
                        page,
                        values,
                        credentials=credentials,
                        save_draft=bool(credentials),
                        profile=data,
                    )
                except Exception as exc:  # noqa: BLE001
                    error = str(exc)[:300]
                    logger.exception("prefill navigation/fill failed")
                try:
                    await page.screenshot(path=shot_path, full_page=True)
                    app.screenshot_path = shot_path
                except Exception:  # noqa: BLE001
                    logger.exception("screenshot failed")
            finally:
                await browser.close()

        # Opt-in fallback: when the deterministic applier filled little and the
        # agent applier is enabled, let the LLM browser agent try. It owns its own
        # browser session and never submits.
        if settings.agent_applier_enabled and len(result.get("filled", {})) < 3:
            cv = (
                await session.execute(
                    select(CvVersion)
                    .where(CvVersion.user_id == app.user_id)
                    .order_by(
                        CvVersion.is_default.desc(), CvVersion.created_at.desc()
                    )
                )
            ).scalars().first()
            from app.appliers.agent import run_agent_prefill

            agent_res = await run_agent_prefill(
                job_url=job.url,
                candidate=values,
                cv_path=cv.file_path if cv else None,
                shot_path=shot_path,
            )
            if not agent_res.get("error"):
                result["agent_summary"] = agent_res.get("summary")
                if agent_res.get("screenshot_path"):
                    app.screenshot_path = agent_res["screenshot_path"]
            else:
                logger.info("agent applier fallback skipped: %s", agent_res["error"])

        draft_saved = bool(result.get("draft_saved"))
        needs_credentials = bool(result.get("needs_credentials"))
        filled = result.get("filled", {})
        missing = list(result.get("missing", []))
        # Surface a hard failure as a visible gap so the card explains itself.
        if error:
            missing.insert(0, f"⚠ Couldn't load/fill the form: {error}")
        # Nothing filled and no error/login flag means we reached a page but found
        # no application form we could use (dead link, sign-in wall, an unsupported
        # widget, or a discovery-only source like LinkedIn). Say so, otherwise the
        # card lands in "Needs Fixes" with no explanation of what to do.
        elif not needs_credentials and not draft_saved and not filled:
            missing.insert(
                0,
                "⚠ No fillable application form was found at this link — it may "
                "require sign-in, use an unsupported form, or be a discovery-only "
                "source (e.g. LinkedIn). Open the posting to apply manually.",
            )

        # Genuine gaps = required fields we couldn't fill that AREN'T the
        # deliberately-blank sensitive ones (salary / "why us", which the human
        # always completes at final submit and don't count as a pipeline problem).
        hard_gaps = [m for m in missing if "(left blank — sensitive)" not in m]
        # An application is only "ready" when the pipeline finished cleanly: no
        # error, no login needed, something actually got filled, and no genuine
        # required gaps. Otherwise it goes to "needs attention" for the human.
        has_issue = bool(error) or needs_credentials or (
            not draft_saved and (len(filled) == 0 or bool(hard_gaps))
        )

        app.prefilled_answers = filled
        app.missing_fields = missing
        app.ai_suggested_fields = result.get("ai_suggested", [])
        app.needs_credentials = needs_credentials
        target = (
            ApplicationStatus.needs_attention
            if has_issue
            else ApplicationStatus.ready_to_submit
        )
        if app.status in (
            ApplicationStatus.discovered,
            ApplicationStatus.drafting,
            ApplicationStatus.needs_attention,
            ApplicationStatus.ready_to_submit,
        ):
            app.status = target
        session.add(
            ApplicationEvent(
                application_id=app.id,
                type="draft_saved" if draft_saved else "prefilled",
                payload={
                    "applier": applier.name,
                    "filled": len(filled),
                    "missing": len(missing),
                    "hard_gaps": len(hard_gaps),
                    "status": target.value,
                    "logged_in": bool(result.get("logged_in")),
                    "draft_saved": draft_saved,
                    "needs_credentials": needs_credentials,
                    "error": error,
                },
            )
        )
        await session.commit()

        from app.services.notify import notify_user

        n_filled = len(filled)
        if needs_credentials:
            msg = (
                f"🔐 {job.title} needs a portal login before it can be filled. "
                "Add your account for this employer in Settings → Employer portal "
                "logins, then hit Retry on the card."
            )
        elif draft_saved:
            msg = (
                f"📝 Draft saved on the employer portal: {job.title} — "
                f"{n_filled} field(s) filled on your account, {len(missing)} to "
                "complete. Log in and submit when ready."
            )
        elif has_issue:
            why = (
                f"couldn't load/fill the form ({error})"
                if error
                else (
                    "nothing could be auto-filled"
                    if len(filled) == 0
                    else f"{len(hard_gaps)} required field(s) need you"
                )
            )
            msg = (
                f"⚠️ Needs fixes: {job.title} — {why}. Open it on the board to "
                "complete the gaps, then move it to Ready."
            )
        else:
            msg = (
                f"✅ Ready to submit: {job.title} — pre-filled "
                f"{n_filled} field(s); only your final submit remains."
            )
        await notify_user(session, app.user_id, msg)
    return {
        "application_id": str(app_id),
        "filled": len(result.get("filled", {})),
        "missing": len(result.get("missing", [])),
        "error": error,
    }


@celery_app.task(name="prefill.run")
def prefill_application(app_id: str) -> dict:
    return asyncio.run(_prefill(uuid.UUID(app_id)))
