"""Discovery: pull jobs from enabled saved searches into the shared catalog,
embed new postings, then score relevance per enabled user.

Pipeline (CLAUDE.md §5):
  1. For each enabled saved_search: connector.fetch -> upsert into `jobs`.
  2. Embed any jobs missing an embedding.
  3. For each user with a profile: embed their profile, apply their searches'
     hard filters to every embedded job, score survivors by cosine ->
     upsert `job_matches`. Above `auto_track_threshold`, auto-create a
     `discovered` application.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.connectors.base import get_connector
from app.db import SessionLocal
from app.models import (
    AnswerBank,
    Application,
    ApplicationEvent,
    ApplicationStatus,
    AppUser,
    Job,
    JobMatch,
    SavedSearch,
)
from app.services import embeddings, relevance
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _ingest(session: AsyncSession) -> tuple[int, int]:
    """Run all enabled searches; upsert normalized jobs. Returns (searches, fetched)."""
    searches = (
        (await session.execute(select(SavedSearch).where(SavedSearch.enabled)))
        .scalars()
        .all()
    )
    fetched = 0
    for s in searches:
        connector = get_connector(s.platform)
        if connector is None:
            logger.warning("no connector for platform %s", s.platform)
            continue
        try:
            jobs = await connector.fetch(s.query, s.filters or {})
        except Exception:  # noqa: BLE001 - one bad source shouldn't sink discovery
            logger.exception("connector %s failed for search %s", s.platform, s.id)
            jobs = []
        for j in jobs:
            if not j.get("title") or not j.get("url"):
                continue
            stmt = (
                pg_insert(Job)
                .values(
                    source=j["source"],
                    external_id=j["external_id"],
                    title=j["title"],
                    company=j.get("company"),
                    location=j.get("location"),
                    url=j["url"],
                    description=j.get("description"),
                    raw=j.get("raw"),
                )
                .on_conflict_do_update(
                    index_elements=["source", "external_id"],
                    set_={
                        "title": j["title"],
                        "company": j.get("company"),
                        "location": j.get("location"),
                        "url": j["url"],
                        "description": j.get("description"),
                    },
                )
            )
            await session.execute(stmt)
            fetched += 1
        s.last_run_at = datetime.now(timezone.utc)
    await session.commit()
    return len(searches), fetched


async def _embed_new_jobs(session: AsyncSession) -> int:
    rows = (
        (await session.execute(select(Job).where(Job.embedding.is_(None))))
        .scalars()
        .all()
    )
    for job in rows:
        text = embeddings.job_text(job.title, job.company, job.location, job.description)
        job.embedding = embeddings.embed(text)
    await session.commit()
    return len(rows)


async def _match_user(session: AsyncSession, user: AppUser, jobs: list[Job]) -> int:
    bank = (
        await session.execute(
            select(AnswerBank).where(AnswerBank.user_id == user.id)
        )
    ).scalar_one_or_none()
    if bank is None:
        return 0
    ptext = embeddings.profile_text(bank.field, bank.data or {})
    if not ptext.strip():
        return 0
    pemb = embeddings.embed(ptext)
    bank.embedding = pemb

    filter_sets = [
        s.filters or {}
        for s in (
            await session.execute(
                select(SavedSearch).where(
                    SavedSearch.user_id == user.id, SavedSearch.enabled
                )
            )
        )
        .scalars()
        .all()
    ]

    matched = 0
    for job in jobs:
        if filter_sets and not any(
            relevance.passes_hard_filters(
                title=job.title,
                location=job.location,
                description=job.description,
                filters=f,
            )
            for f in filter_sets
        ):
            continue
        score = relevance.cosine_similarity(pemb, job.embedding)
        if score < settings.match_threshold:
            continue
        await session.execute(
            pg_insert(JobMatch)
            .values(user_id=user.id, job_id=job.id, relevance_score=score)
            .on_conflict_do_update(
                index_elements=["user_id", "job_id"],
                set_={"relevance_score": score},
            )
        )
        matched += 1

        if score >= settings.auto_track_threshold:
            exists = await session.scalar(
                select(Application.id).where(
                    Application.user_id == user.id, Application.job_id == job.id
                )
            )
            if not exists:
                app = Application(
                    user_id=user.id,
                    job_id=job.id,
                    status=ApplicationStatus.discovered,
                )
                session.add(app)
                await session.flush()
                session.add(
                    ApplicationEvent(
                        application_id=app.id,
                        type="created",
                        payload={"auto": True, "relevance_score": round(score, 4)},
                    )
                )
    await session.commit()
    return matched


async def _run_discovery() -> dict:
    async with SessionLocal() as session:
        n_searches, fetched = await _ingest(session)
        embedded = await _embed_new_jobs(session)
        jobs = (
            (await session.execute(select(Job).where(Job.embedding.is_not(None))))
            .scalars()
            .all()
        )
        users = (await session.execute(select(AppUser))).scalars().all()
        total_matches = 0
        for user in users:
            total_matches += await _match_user(session, user, jobs)
    summary = {
        "searches": n_searches,
        "fetched": fetched,
        "newly_embedded": embedded,
        "jobs_total": len(jobs),
        "users": len(users),
        "matches": total_matches,
    }
    logger.info("discovery complete: %s", summary)
    return summary


@celery_app.task(name="discovery.run")
def run_discovery() -> dict:
    return asyncio.run(_run_discovery())
