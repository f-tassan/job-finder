"""Ranked per-user jobs feed + track action + manual discovery trigger."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_admin, current_user
from app.db import get_session
from app.models import Application, ApplicationEvent, ApplicationStatus, AppUser, Job, JobMatch
from app.schemas import ApplicationOut, JobMatchOut

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobMatchOut])
async def ranked_feed(
    limit: int = 100,
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[JobMatchOut]:
    rows = (
        await session.execute(
            select(JobMatch, Job)
            .join(Job, Job.id == JobMatch.job_id)
            .where(JobMatch.user_id == user.id)
            .order_by(JobMatch.relevance_score.desc())
            .limit(limit)
        )
    ).all()

    tracked_ids = set(
        (
            await session.execute(
                select(Application.job_id).where(Application.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )

    return [
        JobMatchOut(
            job=job,  # type: ignore[arg-type]
            relevance_score=match.relevance_score,
            tracked=job.id in tracked_ids,
        )
        for match, job in rows
    ]


@router.post("/{job_id}/track", response_model=ApplicationOut, status_code=status.HTTP_201_CREATED)
async def track_job(
    job_id: uuid.UUID,
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Application:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    existing = await session.scalar(
        select(Application).where(
            Application.user_id == user.id, Application.job_id == job_id
        )
    )
    if existing:
        return existing

    app = Application(
        user_id=user.id, job_id=job_id, status=ApplicationStatus.discovered
    )
    session.add(app)
    await session.flush()
    session.add(
        ApplicationEvent(application_id=app.id, type="created", payload={"tracked": True})
    )
    await session.commit()
    await session.refresh(app)

    # Send the same job card to Telegram as discovery does, so a manually tracked
    # job behaves like an auto-discovered one (buttons: generate CV / letter,
    # I applied, skip). Its relevance score, if any, rides along.
    from app.bot import notify_job_card

    score = await session.scalar(
        select(JobMatch.relevance_score).where(
            JobMatch.user_id == user.id, JobMatch.job_id == job_id
        )
    )
    await notify_job_card(
        session, user.id, app.id, job, score=score, header="🆕 <b>Job tracked</b>"
    )
    return app


@router.post("/discover", status_code=status.HTTP_202_ACCEPTED)
async def trigger_discovery(_: AppUser = Depends(current_admin)) -> dict:
    """Enqueue a discovery run on the worker (admin only)."""
    from app.tasks.discovery import run_discovery

    result = run_discovery.delay()
    return {"task_id": result.id, "status": "queued"}


@router.get("/discovery-status/{task_id}")
async def discovery_status(
    task_id: str, _: AppUser = Depends(current_user)
) -> dict:
    """Progress of a discovery run for the ranked-jobs progress bar. Reads the
    Celery result backend; returns {state, pct, phase?, detail?, summary?}."""
    from app.tasks.celery_app import celery_app

    res = celery_app.AsyncResult(task_id)
    state = res.state
    info = res.info if isinstance(res.info, dict) else {}
    out: dict = {"state": state, "pct": int(info.get("pct", 0))}
    if state == "PROGRESS":
        out["phase"] = info.get("phase")
        out["detail"] = info.get("detail")
    elif state == "SUCCESS":
        out["pct"] = 100
        out["summary"] = res.result if isinstance(res.result, dict) else None
    elif state == "FAILURE":
        out["pct"] = 100
        out["error"] = str(res.info)[:300]
    return out
