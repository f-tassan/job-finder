"""Per-user applications: kanban feed, manual add, detail, status updates.

Every query is scoped to current_user (per-user isolation, CLAUDE.md §working-agreement).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import current_user
from app.db import get_session
from app.models import (
    Application,
    ApplicationEvent,
    ApplicationStatus,
    AppUser,
    CvVersion,
    Job,
)
from app.schemas import (
    AnswersUpdate,
    ApplicationCreate,
    ApplicationDetailOut,
    ApplicationOut,
    ApplicationUpdate,
)

router = APIRouter(prefix="/applications", tags=["applications"])


async def _owned(session: AsyncSession, user_id, app_id, *, with_events=False):
    stmt = select(Application).where(
        Application.id == app_id, Application.user_id == user_id
    )
    if with_events:
        stmt = stmt.options(selectinload(Application.events))
    app = (await session.execute(stmt)).scalar_one_or_none()
    if app is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return app


async def _validate_cv(session: AsyncSession, user_id, cv_id) -> None:
    cv = await session.get(CvVersion, cv_id)
    if cv is None or cv.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid cv_version_id"
        )


@router.get("", response_model=list[ApplicationOut])
async def list_applications(
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[Application]:
    result = await session.execute(
        select(Application)
        .where(Application.user_id == user.id)
        .order_by(Application.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("", response_model=ApplicationDetailOut, status_code=status.HTTP_201_CREATED)
async def create_application(
    body: ApplicationCreate,
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Application:
    if body.cv_version_id is not None:
        await _validate_cv(session, user.id, body.cv_version_id)

    # Manual add: create a dedicated `manual` job row, then the application.
    job = Job(
        source="manual",
        external_id=str(uuid.uuid4()),
        title=body.title,
        company=body.company,
        location=body.location,
        url=body.url or "",
    )
    session.add(job)
    await session.flush()

    app = Application(
        user_id=user.id,
        job_id=job.id,
        cv_version_id=body.cv_version_id,
        status=body.status,
        notes=body.notes,
    )
    session.add(app)
    await session.flush()
    session.add(
        ApplicationEvent(
            application_id=app.id, type="created", payload={"manual": True}
        )
    )
    await session.commit()
    return await _owned(session, user.id, app.id, with_events=True)


@router.get("/{app_id}", response_model=ApplicationDetailOut)
async def get_application(
    app_id: uuid.UUID,
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Application:
    return await _owned(session, user.id, app_id, with_events=True)


@router.patch("/{app_id}", response_model=ApplicationDetailOut)
async def update_application(
    app_id: uuid.UUID,
    body: ApplicationUpdate,
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Application:
    app = await _owned(session, user.id, app_id)

    if body.cv_version_id is not None:
        await _validate_cv(session, user.id, body.cv_version_id)
        app.cv_version_id = body.cv_version_id
    if body.notes is not None:
        app.notes = body.notes

    if body.status is not None and body.status != app.status:
        old = app.status
        app.status = body.status
        if body.status == ApplicationStatus.submitted and app.submitted_at is None:
            app.submitted_at = datetime.now(timezone.utc)
        session.add(
            ApplicationEvent(
                application_id=app.id,
                type="status_changed",
                payload={"from": old.value, "to": body.status.value},
            )
        )

    await session.commit()
    return await _owned(session, user.id, app_id, with_events=True)


@router.post("/{app_id}/tailor", status_code=status.HTTP_202_ACCEPTED)
async def tailor_application(
    app_id: uuid.UUID,
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Enqueue tailoring (ATS CV + cover letter) for this application."""
    await _owned(session, user.id, app_id)
    from app.tasks.tailor import tailor_application as task

    result = task.delay(str(app_id))
    return {"task_id": result.id, "status": "queued"}


@router.post("/{app_id}/prefill", status_code=status.HTTP_202_ACCEPTED)
async def prefill_application(
    app_id: uuid.UUID,
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Enqueue form pre-fill on the browser-worker (fills known fields, flags gaps)."""
    await _owned(session, user.id, app_id)
    from app.tasks.prefill import prefill_application as task

    result = task.apply_async(args=[str(app_id)], queue="browser")
    return {"task_id": result.id, "status": "queued"}


@router.patch("/{app_id}/answers", response_model=ApplicationDetailOut)
async def update_answers(
    app_id: uuid.UUID,
    body: AnswersUpdate,
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Application:
    """User completes the gaps left at review."""
    app = await _owned(session, user.id, app_id)
    app.prefilled_answers = body.prefilled_answers
    await session.commit()
    return await _owned(session, user.id, app_id, with_events=True)


@router.post("/{app_id}/submit", response_model=ApplicationDetailOut)
async def submit_application(
    app_id: uuid.UUID,
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Application:
    """Mark the application submitted (the human performs the actual submit)."""
    app = await _owned(session, user.id, app_id)
    app.status = ApplicationStatus.submitted
    if app.submitted_at is None:
        app.submitted_at = datetime.now(timezone.utc)
    session.add(
        ApplicationEvent(application_id=app.id, type="submitted", payload={})
    )
    await session.commit()
    return await _owned(session, user.id, app_id, with_events=True)


@router.get("/{app_id}/screenshot")
async def get_screenshot(
    app_id: uuid.UUID,
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    app = await _owned(session, user.id, app_id)
    if not app.screenshot_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No screenshot yet"
        )
    return FileResponse(app.screenshot_path, media_type="image/png")


@router.get("/{app_id}/cv")
async def download_tailored_cv(
    app_id: uuid.UUID,
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    app = await _owned(session, user.id, app_id)
    if not app.tailored_cv_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No tailored CV yet"
        )
    return FileResponse(app.tailored_cv_path, filename="tailored_cv.pdf")


@router.delete("/{app_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_application(
    app_id: uuid.UUID,
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    app = await _owned(session, user.id, app_id)
    await session.delete(app)
    await session.commit()
