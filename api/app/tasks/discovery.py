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
    JobSkip,
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
) -> tuple[int, list[tuple[str, Job, float]]]:
    """Returns (matched, auto_tracked) where auto_tracked is a list of
    (application_id, job, score) for newly tracked high matches — the caller
    messages each one to the user on Telegram with action buttons.

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
        return 0, []
    ptext = embeddings.profile_text(bank.field, bank.data or {})
    if not ptext.strip():
        return 0, []
    pemb = embeddings.embed(ptext)
    bank.embedding = pemb

    prefs = bank.prefs or {}
    ksa_only = prefs.get("ksa_only", True)

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

    skipped_ids = set(
        (
            await session.execute(
                select(JobSkip.job_id).where(JobSkip.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )

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
        # Same for anything this user tapped 🙈 Skip on: the application row is
        # gone, so only job_skips stops us re-tracking and re-announcing it.
        if job.id in skipped_ids:
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
    auto_tracked: list[tuple[str, Job, float]] = []
    for job, cos in candidates:
        score = (llm_scores or {}).get(str(job.id), cos)
        session.add(
            JobMatch(user_id=user.id, job_id=job.id, relevance_score=score)
        )
        matched += 1

        if score < settings.auto_track_threshold:
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
            auto_tracked.append((str(app.id), job, score))
    await session.commit()
    return matched, auto_tracked


async def _prune_removed_jobs(session: AsyncSession) -> dict:
    """Delete postings that are no longer live from the catalog and each user's
    board. Candidates are the jobs users actually see — those with a
    `discovered` application (checked first) and those in the ranked feed
    (`job_matches`) — bounded by `liveness_check_cap` per run.

    A confirmed-removed job is stripped from the feed (job_matches) and from
    every user's `discovered` column (those applications are deleted). The job
    row itself is deleted when nothing else references it; if a user already has
    a non-discovered application for it (submitted/interview/…), the row is kept
    but flagged closed so it stays out of the feed while preserving that history.
    Returns {'checked', 'removed', 'by_user': {user_id: [(title, company, url)]}}
    — the jobs, not just a count, so each user can be told exactly which of their
    cards vanished.
    """
    from sqlalchemy import func

    from app.services import job_liveness

    disc_ids = (
        await session.execute(
            select(Application.job_id)
            .where(Application.status == ApplicationStatus.discovered)
            .distinct()
        )
    ).scalars().all()
    feed_ids = (
        await session.execute(select(JobMatch.job_id).distinct())
    ).scalars().all()

    seen: set = set()
    ordered: list = []
    for jid in list(disc_ids) + list(feed_ids):
        if jid not in seen:
            seen.add(jid)
            ordered.append(jid)
    ordered = ordered[: settings.liveness_check_cap]

    checked = removed = 0
    by_user: dict = {}
    for jid in ordered:
        job = await session.get(Job, jid)
        if job is None or (job.raw or {}).get("closed"):
            continue
        checked += 1
        try:
            gone = await job_liveness.is_removed(job)
        except Exception:  # noqa: BLE001 - one bad check shouldn't sink the run
            logger.exception("liveness check errored for job %s", jid)
            continue
        if not gone:
            continue
        removed += 1
        disc_apps = (
            await session.execute(
                select(Application).where(
                    Application.job_id == jid,
                    Application.status == ApplicationStatus.discovered,
                )
            )
        ).scalars().all()
        for a in disc_apps:
            by_user.setdefault(a.user_id, []).append(
                (job.title, job.company, job.url)
            )
            await session.delete(a)
        await session.execute(delete(JobMatch).where(JobMatch.job_id == jid))
        remaining = await session.scalar(
            select(func.count())
            .select_from(Application)
            .where(Application.job_id == jid)
        )
        if not remaining:
            await session.delete(job)
        else:
            job.raw = {**(job.raw or {}), "closed": True}
    await session.commit()
    logger.info("prune removed jobs: checked=%s removed=%s", checked, removed)
    return {"checked": checked, "removed": removed, "by_user": by_user}


def _removed_jobs_message(gone_jobs: list[tuple[str, str | None, str | None]]) -> str:
    """Telegram HTML naming each posting the employer pulled off this user's
    board: '<title> at <company>', linked to the (now dead) posting."""
    from app.bot import _esc

    lines = []
    for title, company, url in gone_jobs:
        label = _esc(title) + (f" at {_esc(company)}" if company else "")
        lines.append(f'• <a href="{_esc(url)}">{label}</a>' if url else f"• {label}")
    head = (
        "🗑 <b>A job was removed by the employer</b> and taken off your board:"
        if len(gone_jobs) == 1
        else f"🗑 <b>{len(gone_jobs)} jobs were removed by the employer</b> and "
        "taken off your board:"
    )
    return head + "\n" + "\n".join(lines)


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
        # Prune postings that are no longer live BEFORE matching, so removed jobs
        # leave both the discovered column and the ranked feed and aren't
        # re-surfaced this run.
        emit("Checking removed postings", 66)
        pruned = await _prune_removed_jobs(session)
        emit("Loading catalog", 68)
        jobs = (
            (await session.execute(select(Job).where(Job.embedding.is_not(None))))
            .scalars()
            .all()
        )
        users = (await session.execute(select(AppUser))).scalars().all()
        total_matches = 0
        from app.bot import format_job_html, job_buttons
        from app.services.notify import chat_id_for_user, notify_user, send_telegram

        # Tell each user whose discovered card(s) vanished because the employer
        # pulled the posting — naming each job, since a bare count leaves them
        # wondering which one they lost.
        for uid, gone_jobs in (pruned.get("by_user") or {}).items():
            await notify_user(
                session, uid, _removed_jobs_message(gone_jobs), parse_mode="HTML"
            )

        n_users = max(len(users), 1)
        for ui, user in enumerate(users):
            lo = 70 + 28 * ui / n_users
            hi = 70 + 28 * (ui + 1) / n_users

            def _report(frac: float, detail: str = "", lo=lo, hi=hi, email=user.email):
                emit("Ranking matches", lo + (hi - lo) * frac, detail or email)

            _report(0.0)
            matched, auto_tracked = await _match_user(
                session, user, jobs, report=_report
            )
            total_matches += matched
            if not auto_tracked:
                continue
            # Each new high match goes to Telegram as its own card with action
            # buttons (tailor CV / letter, mark applied, skip) — the chat is the
            # primary place to act on jobs. Capped per run to avoid flooding;
            # the rest are one summary line (they're all in the web feed).
            chat_id = await chat_id_for_user(session, user.id)
            if not chat_id:
                continue
            cap = settings.telegram_jobs_per_run
            for app_id, job, score in auto_tracked[:cap]:
                await send_telegram(
                    chat_id,
                    format_job_html(job, score, header="🆕 <b>New job discovered</b>"),
                    parse_mode="HTML",
                    reply_markup=job_buttons(
                        app_id, linkedin="linkedin" in (job.source or "")
                    ),
                )
            if len(auto_tracked) > cap:
                await send_telegram(
                    chat_id,
                    f"…and {len(auto_tracked) - cap} more — see the Jobs feed, "
                    "or send /jobs for the next batch.",
                )
    summary = {
        "searches": n_searches,
        "fetched": fetched,
        "newly_embedded": embedded,
        "removed_jobs": pruned.get("removed", 0),
        "jobs_total": len(jobs),
        "users": len(users),
        "matches": total_matches,
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
