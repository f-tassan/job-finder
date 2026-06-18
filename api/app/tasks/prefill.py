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
                    result = await applier.prefill(page, values)
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

        app.prefilled_answers = result.get("filled", {})
        app.missing_fields = result.get("missing", [])
        if app.status in (ApplicationStatus.discovered, ApplicationStatus.drafting):
            app.status = ApplicationStatus.ready_to_submit
        session.add(
            ApplicationEvent(
                application_id=app.id,
                type="prefilled",
                payload={
                    "applier": applier.name,
                    "filled": len(result.get("filled", {})),
                    "missing": len(result.get("missing", [])),
                    "error": error,
                },
            )
        )
        await session.commit()
    return {
        "application_id": str(app_id),
        "filled": len(result.get("filled", {})),
        "missing": len(result.get("missing", [])),
        "error": error,
    }


@celery_app.task(name="prefill.run")
def prefill_application(app_id: str) -> dict:
    return asyncio.run(_prefill(uuid.UUID(app_id)))
