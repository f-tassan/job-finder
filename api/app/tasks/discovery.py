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

from sqlalchemy import case, delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.connectors.base import clean_field, get_connector
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


async def _ingest(session: AsyncSession, on_search=None) -> tuple[int, int]:
    """Run all enabled searches; upsert normalized jobs. Returns (searches, fetched).

    `on_search(i, total, name)` is called before each search AND after it
    finishes, so the caller can advance a progress bar through the slow,
    network-bound fetch phase instead of jumping only once per source."""
    searches = (
        (await session.execute(select(SavedSearch).where(SavedSearch.enabled)))
        .scalars()
        .all()
    )
    fetched = 0
    for i, s in enumerate(searches):
        if on_search:
            on_search(i, len(searches), s.platform)
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
            # Decode HTML entities in display fields (e.g. "Sales &amp; Marketing"
            # -> "Sales & Marketing") regardless of whether the source is HTML or
            # a JSON API, so titles read naturally everywhere they're shown.
            title = clean_field(j["title"])
            company = clean_field(j.get("company"))
            location = clean_field(j.get("location"))
            description = j.get("description")
            # Only invalidate the cached embedding when the text we actually embed
            # (title/company/location/description) changed. Most jobs reappear in
            # every discovery run, so unconditionally nulling the embedding would
            # needlessly re-embed the whole catalog (CPU-bound) each time.
            embed_unchanged = (
                (Job.title == title)
                & Job.company.is_not_distinct_from(company)
                & Job.location.is_not_distinct_from(location)
                & Job.description.is_not_distinct_from(description)
            )
            stmt = (
                pg_insert(Job)
                .values(
                    source=j["source"],
                    external_id=j["external_id"],
                    title=title,
                    company=company,
                    location=location,
                    url=j["url"],
                    description=description,
                    raw=j.get("raw"),
                )
                .on_conflict_do_update(
                    index_elements=["source", "external_id"],
                    set_={
                        "title": title,
                        "company": company,
                        "location": location,
                        "url": j["url"],
                        "description": description,
                        # Keep the existing embedding when the embedded text is
                        # unchanged; reset (re-embed) only when it actually changed.
                        "embedding": case(
                            (embed_unchanged, Job.embedding), else_=None
                        ),
                    },
                )
            )
            await session.execute(stmt)
            fetched += 1
        s.last_run_at = datetime.now(timezone.utc)
        # Advance the bar as each source completes (the fetch above is the slow
        # part), so a run with few-but-slow sources still moves steadily.
        if on_search:
            on_search(i + 1, len(searches), s.platform)
    await session.commit()
    return len(searches), fetched


async def _embed_new_jobs(session: AsyncSession, report=None) -> int:
    rows = (
        (await session.execute(select(Job).where(Job.embedding.is_(None))))
        .scalars()
        .all()
    )
    n = len(rows)
    for idx, job in enumerate(rows):
        text = embeddings.job_text(job.title, job.company, job.location, job.description)
        job.embedding = embeddings.embed(text)
        # Embedding a large new batch is slow; report through it so the bar moves.
        if report and n and idx % 20 == 0:
            report(idx / n, f"{idx}/{n}")
    await session.commit()
    return n


async def _match_user(
    session: AsyncSession, user: AppUser, jobs: list[Job], report=None
) -> tuple[int, list[str], list[str]]:
    """Returns (matched, auto_tracked_titles, auto_prepare_app_ids).

    `report(frac, detail)` (0..1 within this user's progress slice) is called at
    the slow points (cosine sweep, LLM re-rank) so the bar keeps moving."""

    def step(frac: float, detail: str = "") -> None:
        if report:
            report(frac, detail)

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
        prefs.get("auto_apply_threshold", settings.auto_apply_threshold_default)
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
    step(0.1, "filtering")
    candidates: list[tuple[Job, float]] = []
    for job in jobs:
        # Skip postings a submit attempt found closed/removed — don't re-surface or
        # re-track them (the application was deleted on purpose).
        if (job.raw or {}).get("closed"):
            continue
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
    step(0.6, "AI re-ranking")
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

    step(0.85, "saving matches")
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


async def _run_discovery(progress=None) -> dict:
    """`progress(phase, pct, detail)` (optional) reports 0–100% so the UI can show
    a bar. Phases: fetching sources (≤60%), embedding (~65%), ranking (70–98%)."""

    def emit(phase: str, pct: float, detail: str = "") -> None:
        if progress:
            progress(phase, max(0, min(100, round(pct))), detail)

    async with SessionLocal() as session:
        emit("Fetching sources", 3)
        n_searches, fetched = await _ingest(
            session,
            on_search=lambda i, t, name: emit(
                "Fetching sources", 5 + 55 * i / max(t, 1), name
            ),
        )
        emit("Embedding new jobs", 62)
        embedded = await _embed_new_jobs(
            session,
            report=lambda f, d="": emit("Embedding new jobs", 62 + 6 * f, d),
        )
        emit("Loading catalog", 68)
        jobs = (
            (await session.execute(select(Job).where(Job.embedding.is_not(None))))
            .scalars()
            .all()
        )
        users = (await session.execute(select(AppUser))).scalars().all()
        total_matches = 0
        total_auto_prepared = 0
        from app.services.notify import notify_user

        n_users = max(len(users), 1)
        for ui, user in enumerate(users):
            lo = 70 + 28 * ui / n_users
            hi = 70 + 28 * (ui + 1) / n_users

            def _report(frac: float, detail: str = "", lo=lo, hi=hi, email=user.email):
                emit("Ranking matches", lo + (hi - lo) * frac, detail or email)

            _report(0.0)
            matched, auto_tracked, auto_prepare = await _match_user(
                session, user, jobs, report=_report
            )
            total_matches += matched
            # Auto-apply: pre-fill only (-> ready_to_submit). We deliberately do
            # NOT auto-tailor the CV/cover letter here — that's an LLM token cost
            # the user opts into per-application via the "Tailor" button. Pre-fill
            # attaches the user's default CV; the human still does the final submit.
            from app.services.throttle import on_cooldown
            from app.tasks.prefill import prefill_application

            queued = 0
            for app_id in auto_prepare:
                # Don't double-queue a prefill for the same app across back-to-back
                # discovery runs (Beat + a manual trigger, or an acks_late redelivery)
                # before the first prefill has run and moved it out of `discovered`.
                if on_cooldown(f"autoprefill:{app_id}", seconds=6 * 3600):
                    continue
                prefill_application.apply_async(args=[app_id], queue="browser")
                queued += 1
            total_auto_prepared += queued
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
    if progress:
        progress("Done", 100, "")
    return summary


@celery_app.task(bind=True, name="discovery.run")
def run_discovery(self) -> dict:
    """Discovery run. Reports PROGRESS meta ({phase, pct, detail}) as it goes so
    the ranked-jobs page can render a progress bar via /jobs/discovery-status."""

    def progress(phase: str, pct: int, detail: str = "") -> None:
        try:
            self.update_state(
                state="PROGRESS",
                meta={"phase": phase, "pct": pct, "detail": detail},
            )
        except Exception:  # noqa: BLE001 - progress is best-effort, never fatal
            pass

    # Single-flight: two concurrent discovery runs deadlock on the jobs upserts
    # (Beat + a manual trigger, or an acks_late redelivery). Take a short-lived
    # Redis lock; if another run holds it, skip rather than collide.
    import redis as _redis

    client = _redis.from_url(settings.celery_broker_url)
    lock = client.lock("discovery:run:lock", timeout=3600, blocking=False)
    if not lock.acquire(blocking=False):
        logger.info("discovery already running; skipping this trigger")
        return {"skipped": "another discovery run is in progress"}
    try:
        return asyncio.run(_run_discovery(progress))
    finally:
        try:
            lock.release()
        except Exception:  # noqa: BLE001 - lock may have expired; safe to ignore
            pass
