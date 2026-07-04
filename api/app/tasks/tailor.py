"""Tailor an application: build an ATS CV and/or cover letter (cheap model),
render PDFs, move the application to `ready`, and deliver the documents to the
user on Telegram so they can attach them while applying manually."""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from pathlib import Path

from sqlalchemy import func, select

from app.config import settings
from app.db import SessionLocal
from app.models import (
    AnswerBank,
    Application,
    ApplicationDocument,
    ApplicationEvent,
    ApplicationStatus,
    AppUser,
    CvVersion,
    Job,
)
from app.services import cv_render, tailoring
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _next_version(session, app_id: uuid.UUID, kind: str) -> int:
    """Next 1-based version number for (application, kind)."""
    current = (
        await session.execute(
            select(func.max(ApplicationDocument.version)).where(
                ApplicationDocument.application_id == app_id,
                ApplicationDocument.kind == kind,
            )
        )
    ).scalar()
    return (current or 0) + 1


def _doc_name(kind: str, job: Job) -> str:
    """Filename the user sees in Telegram, e.g. CV_Acme_Data_Engineer.pdf."""
    stem = "_".join(p for p in (job.company, job.title) if p)
    stem = re.sub(r"[^\w؀-ۿ]+", "_", stem).strip("_")[:60] or "job"
    return f"{kind}_{stem}.pdf"


async def _tailor(app_id: uuid.UUID, make_cv: bool, make_letter: bool) -> dict:
    # CV generation is temporarily disabled globally; never produce a CV even if
    # an old queued task or caller asked for one.
    make_cv = make_cv and settings.cv_generation_enabled
    if not (make_cv or make_letter):
        return {"skipped": "nothing to generate (CV disabled)"}
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

        result = await tailoring.tailor(
            applicant, job_dict, want_cv=make_cv, want_cover_letter=make_letter
        )

        contact = {
            "full_name_en": data.get("full_name_en"),
            "email": data.get("email") or user.email,
            "phone": data.get("phone"),
            "city": data.get("city"),
            "linkedin": data.get("linkedin"),
        }
        out_dir = Path(settings.files_dir) / str(app.user_id) / "tailored"

        # Each run appends a NEW version (a fresh PDF at a versioned path); the
        # app's *_path columns mirror the latest for the single-file endpoints.
        cv_version = letter_version = None
        if make_cv and result["cv"] is not None:
            cv_version = await _next_version(session, app.id, "cv")
            cv_path = str(out_dir / f"{app.id}_cv_v{cv_version}.pdf")
            rendered = False
            try:
                cv_render.render_cv_pdf(result["cv"], contact, cv_path)
                rendered = True
                app.tailored_cv_path = cv_path
            except Exception:  # noqa: BLE001 - keep record even if PDF fails
                logger.exception("CV PDF render failed for application %s", app.id)
            app.keyword_coverage = result["keyword_coverage"]
            session.add(
                ApplicationDocument(
                    application_id=app.id,
                    kind="cv",
                    version=cv_version,
                    file_path=cv_path if rendered else None,
                    keyword_coverage=result["keyword_coverage"],
                )
            )

        if make_letter and result["cover_letter"]:
            letter_version = await _next_version(session, app.id, "cover_letter")
            app.cover_letter = result["cover_letter"]
            letter_path = str(
                out_dir / f"{app.id}_cover_letter_v{letter_version}.pdf"
            )
            rendered = False
            try:
                cv_render.render_letter_pdf(result["cover_letter"], contact, letter_path)
                rendered = True
                app.cover_letter_path = letter_path
            except Exception:  # noqa: BLE001
                logger.exception("letter PDF render failed for application %s", app.id)
            session.add(
                ApplicationDocument(
                    application_id=app.id,
                    kind="cover_letter",
                    version=letter_version,
                    file_path=letter_path if rendered else None,
                    text=result["cover_letter"],
                )
            )

        if app.status == ApplicationStatus.discovered:
            app.status = ApplicationStatus.ready
        session.add(
            ApplicationEvent(
                application_id=app.id,
                type="tailored",
                payload={
                    "cv": make_cv,
                    "cover_letter": make_letter,
                    "used_llm": result["used_llm"],
                    "keyword_coverage": result["keyword_coverage"],
                },
            )
        )
        await session.commit()

        # Deliver the documents on Telegram: the user applies manually with them,
        # then taps "I applied" to mark the application submitted.
        from app.services.notify import (
            chat_id_for_user,
            send_telegram,
            send_telegram_document,
        )

        chat_id = await chat_id_for_user(session, app.user_id)
        if chat_id:
            title = job.title + (f" at {job.company}" if job.company else "")
            # Each document carries its own "🔄 Regenerate" button, so the user
            # can make another version if they don't like this one.
            if app.tailored_cv_path and cv_version:
                vtag = f" (v{cv_version})" if cv_version > 1 else ""
                await send_telegram_document(
                    chat_id,
                    app.tailored_cv_path,
                    filename=_doc_name("CV", job),
                    caption=f"📄 Tailored CV{vtag} — {title}",
                    reply_markup={
                        "inline_keyboard": [
                            [{"text": "🔄 Regenerate CV", "callback_data": f"cv:{app.id}"}]
                        ]
                    },
                )
            if app.cover_letter_path and letter_version:
                vtag = f" (v{letter_version})" if letter_version > 1 else ""
                await send_telegram_document(
                    chat_id,
                    app.cover_letter_path,
                    filename=_doc_name("Cover_Letter", job),
                    caption=f"✉️ Cover letter{vtag} — {title}",
                    reply_markup={
                        "inline_keyboard": [
                            [
                                {
                                    "text": "🔄 Regenerate Cover Letter",
                                    "callback_data": f"cl:{app.id}",
                                }
                            ]
                        ]
                    },
                )
            done = []
            if cv_version:
                done.append("CV")
            if letter_version:
                done.append("cover letter")
            if done:
                await send_telegram(
                    chat_id,
                    f"✅ {' + '.join(done)} ready for {title}.\n"
                    f"Apply here: {job.url}\n"
                    "Not happy with a document? Tap 🔄 Regenerate under it. When "
                    "you've applied, tap ✅ and I'll track it.",
                    reply_markup={
                        "inline_keyboard": [
                            [
                                {
                                    "text": "✅ I applied",
                                    "callback_data": f"applied:{app.id}",
                                }
                            ]
                        ]
                    },
                )
    return {
        "application_id": str(app_id),
        "used_llm": result["used_llm"],
        "keyword_coverage": result["keyword_coverage"],
    }


@celery_app.task(name="tailor.run")
def tailor_application(
    app_id: str, make_cv: bool = True, make_letter: bool = True
) -> dict:
    return asyncio.run(_tailor(uuid.UUID(app_id), make_cv, make_letter))
