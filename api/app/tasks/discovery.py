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

from sqlalchemy import delete, select
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
from app.services import embeddings, llm, relevance
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
                        # Reset so the (possibly now-richer) text is re-embedded.
                        "embedding": None,
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


async def _match_user(
    session: AsyncSession, user: AppUser, jobs: list[Job]
) -> tuple[int, list[str], list[str]]:
    """Returns (matched, auto_tracked_titles, auto_prepare_app_ids)."""
    bank = (
        await session.execute(
            select(AnswerBank).where(AnswerBank.user_id == user.id)
        )
    ).scalar_one_or_none()
    if bank is None:
        return 0, [], []
    ptext = embeddings.profile_text(bank.field, bank.data or {})
    if not ptext.strip():
        return 0, [], []
    pemb = embeddings.embed(ptext)
    bank.embedding = pemb

    prefs = bank.prefs or {}
    ksa_only = prefs.get("ksa_only", True)
    auto_enabled = prefs.get("auto_apply_enabled", False)
    auto_threshold = float(
        prefs.get("auto_apply_threshold", settings.auto_track_threshold)
    )

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

    # Rebuild this user's matches from scratch so location/threshold changes (and
    # newly-filtered-out jobs) are reflected immediately.
    await session.execute(delete(JobMatch).where(JobMatch.user_id == user.id))

    # 1) Recall: cosine over all jobs passing KSA + saved-search hard filters.
    candidates: list[tuple[Job, float]] = []
    for job in jobs:
        # KSA filter:
        #  - jobs WITH a location must be in Saudi Arabia;
        #  - null-location jobs (user-curated company_site careers pages) are kept,
        #    EXCEPT when the title clearly names a foreign place (PIF's global
        #    portfolio companies list mostly non-KSA roles, e.g. "… Austin, TX").
        if ksa_only:
            if job.location:
                if not relevance.is_ksa(job.location, job.description):
                    continue
            elif relevance.mentions_non_ksa(job.title):
                continue
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
        cos = relevance.cosine_similarity(pemb, job.embedding)
        if cos >= settings.match_threshold:
            candidates.append((job, cos))

    candidates.sort(key=lambda c: c[1], reverse=True)

    # 2) Precision: LLM re-rank the top candidates (uses the configured provider).
    llm_scores: dict[str, float] | None = None
    top = candidates[: settings.rerank_top_k]
    if top:
        llm_scores = await llm.rank_jobs(
            ptext,
            [
                {
                    "id": str(job.id),
                    "title": job.title,
                    "company": job.company,
                    "location": job.location,
                    "description": (job.description or "")[:600],
                }
                for job, _ in top
            ],
        )

    matched = 0
    auto_tracked: list[str] = []
    auto_prepare: list[str] = []
    for job, cos in candidates:
        score = (llm_scores or {}).get(str(job.id), cos)
        session.add(
            JobMatch(user_id=user.id, job_id=job.id, relevance_score=score)
        )
        matched += 1

        should_track = score >= settings.auto_track_threshold
        should_autoapply = auto_enabled and score >= auto_threshold
        if not (should_track or should_autoapply):
            continue

        app = (
            await session.execute(
                select(Application).where(
                    Application.user_id == user.id, Application.job_id == job.id
                )
            )
        ).scalar_one_or_none()
        if app is None:
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
            auto_tracked.append(job.title)

        # Auto-apply: prepare (tailor -> pre-fill) high-scoring, not-yet-started apps.
        if should_autoapply and app.status == ApplicationStatus.discovered:
            session.add(
                ApplicationEvent(
                    application_id=app.id,
                    type="auto_apply_queued",
                    payload={"relevance_score": round(score, 4)},
                )
            )
            auto_prepare.append(str(app.id))
    await session.commit()
    return matched, auto_tracked, auto_prepare


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
        total_auto_prepared = 0
        from app.services.notify import notify_user

        for user in users:
            matched, auto_tracked, auto_prepare = await _match_user(
                session, user, jobs
            )
            total_matches += matched
            # Auto-apply: kick off tailor -> pre-fill (-> ready_to_submit). The
            # human still does the final submit (no auto-submit, CLAUDE.md rule).
            for app_id in auto_prepare:
                from app.tasks.tailor import tailor_application

                tailor_application.delay(app_id, then_prefill=True)
            total_auto_prepared += len(auto_prepare)
            if auto_tracked:
                preview = "; ".join(auto_tracked[:3])
                more = (
                    f" (+{len(auto_tracked) - 3} more)"
                    if len(auto_tracked) > 3
                    else ""
                )
                extra = (
                    f" · auto-preparing {len(auto_prepare)}" if auto_prepare else ""
                )
                await notify_user(
                    session,
                    user.id,
                    f"🔎 {len(auto_tracked)} new high-match job(s): {preview}{more}{extra}",
                )
    summary = {
        "searches": n_searches,
        "fetched": fetched,
        "newly_embedded": embedded,
        "jobs_total": len(jobs),
        "users": len(users),
        "matches": total_matches,
        "auto_prepared": total_auto_prepared,
    }
    logger.info("discovery complete: %s", summary)
    return summary


@celery_app.task(name="discovery.run")
def run_discovery() -> dict:
    return asyncio.run(_run_discovery())
