"""Tailor an application: build an ATS CV + cover letter, render the PDF, and
move the application to `drafting`."""
from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import (
    AnswerBank,
    Application,
    ApplicationEvent,
    ApplicationStatus,
    AppUser,
    CvVersion,
    Job,
)
from app.services import cv_render, tailoring
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _tailor(app_id: uuid.UUID) -> dict:
    async with SessionLocal() as session:
        app = await session.get(Application, app_id)
        if app is None:
            return {"error": "application not found"}
        job = await session.get(Job, app.job_id)
        user = await session.get(AppUser, app.user_id)
        bank = (
            await session.execute(
                select(AnswerBank).where(AnswerBank.user_id == app.user_id)
            )
        ).scalar_one_or_none()

        # Choose the CV: the one attached to the application, else the default.
        cv = None
        if app.cv_version_id:
            cv = await session.get(CvVersion, app.cv_version_id)
        if cv is None:
            cv = (
                await session.execute(
                    select(CvVersion)
                    .where(CvVersion.user_id == app.user_id)
                    .order_by(CvVersion.is_default.desc(), CvVersion.created_at.desc())
                )
            ).scalars().first()

        data = (bank.data if bank else {}) or {}
        field = bank.field if bank else None
        applicant = tailoring.build_applicant(field, data, cv.parsed if cv else None)
        job_dict = {
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "description": job.description,
        }

        # Generate a cover letter only when the application form actually has one
        # (detected at pre-fill: a "cover letter" field is flagged sensitive in
        # missing_fields). If the job hasn't been pre-filled yet we don't know, so
        # generate one to be safe. Saves tokens on forms that never ask for one.
        mf = [str(m).lower() for m in (app.missing_fields or [])]
        prefilled = bool(app.missing_fields) or bool(app.prefilled_answers)
        # A cover letter is warranted when the form has a literal cover-letter
        # field OR a free-text motivation / "why this company" question.
        _cover_signals = (
            "cover letter",
            "cover_letter",
            "motivation",
            "why do you",
            "why this",
            "why us",
            "why join",
            "why you want",
            "tell us why",
        )
        form_has_cover_letter = any(
            any(sig in m for sig in _cover_signals) for m in mf
        )
        want_cover_letter = form_has_cover_letter or not prefilled

        result = await tailoring.tailor(
            applicant, job_dict, want_cover_letter=want_cover_letter
        )

        contact = {
            "full_name_en": data.get("full_name_en"),
            "email": data.get("email") or user.email,
            "phone": data.get("phone"),
            "city": data.get("city"),
            "linkedin": data.get("linkedin"),
        }
        out_path = str(
            Path(settings.files_dir) / str(app.user_id) / "tailored" / f"{app.id}.pdf"
        )
        try:
            cv_render.render_cv_pdf(result["cv"], contact, out_path)
            app.tailored_cv_path = out_path
        except Exception:  # noqa: BLE001 - keep text output even if PDF fails
            logger.exception("PDF render failed for application %s", app.id)

        app.cover_letter = result["cover_letter"] or None
        app.keyword_coverage = result["keyword_coverage"]
        if app.status == ApplicationStatus.discovered:
            app.status = ApplicationStatus.drafting
        session.add(
            ApplicationEvent(
                application_id=app.id,
                type="tailored",
                payload={
                    "used_llm": result["used_llm"],
                    "keyword_coverage": result["keyword_coverage"],
                },
            )
        )
        await session.commit()

        from app.services.notify import notify_user

        await notify_user(
            session,
            app.user_id,
            f"📝 Tailored CV{' + cover letter' if app.cover_letter else ''} ready: "
            f"{job.title}" + (f" at {job.company}" if job.company else ""),
        )
    return {
        "application_id": str(app_id),
        "used_llm": result["used_llm"],
        "keyword_coverage": result["keyword_coverage"],
    }


@celery_app.task(name="tailor.run")
def tailor_application(app_id: str, then_prefill: bool = False) -> dict:
    result = asyncio.run(_tailor(uuid.UUID(app_id)))
    # Auto-apply chain: after tailoring, queue pre-fill on the browser worker
    # (advances to ready_to_submit). The human still does the final submit.
    if then_prefill:
        from app.tasks.prefill import prefill_application

        prefill_application.apply_async(args=[app_id], queue="browser")
    return result
