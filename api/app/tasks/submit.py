"""Browser-worker task: actually submit an application form end to end.

This is the ONE place that performs a real submission, and it runs only when the
user explicitly triggers it (POST /applications/{id}/auto-submit) — never from
the automatic discovery/auto-apply pipeline. Per CLAUDE.md this is allowed for
standalone ATS forms ("pre-fill and finalize only on the user's confirmation")
and must never be used for LinkedIn/Bayt.

Flow: open the form → fill known fields (and sign in if a credential is stored)
→ click the final submit button → look for a confirmation → screenshot → record
the outcome. If a confirmation can't be detected, the application is left in
`ready_to_submit` for the human to finish, and we say so.
"""
from __future__ import annotations

import asyncio
import logging
import time
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

# LinkedIn/Bayt must never be auto-submitted (hard rule).
_BLOCKED_HOSTS = ("linkedin.com", "bayt.com")

# Text that signals the portal accepted the application.
_CONFIRM_MARKERS = (
    "thank you for applying",
    "thank you for your application",
    "application received",
    "application has been received",
    "application has been submitted",
    "we have received your application",
    "successfully submitted",
    "your application was submitted",
    "thank you for your interest",
    "application submitted",
    "thanks for applying",
    "submitted your application",
    "we'll be in touch",
)

# Text that signals the portal demands an emailed verification/OTP code before it
# will accept the application (e.g. Greenhouse "verified applications"). The
# throwaway headless browser can't read the user's inbox, so we can't pass this —
# we stop, leave the app unsent, and tell the human to finish it themselves.
_VERIFY_MARKERS = (
    "verification code",
    "verify your email",
    "confirm you're a human",
    "confirm you are a human",
    "code was sent",
    "sent a code",
    "enter the code",
    "enter the 6",
    "check your email",
)

# Text that signals the posting is gone — nothing can be submitted. Routes the app
# to the closed outcome instead of a misleading "couldn't confirm".
_CLOSED_MARKERS = (
    "no longer available",
    "no longer accepting",
    "not accepting applications",
    "has been filled",
    "already been filled",
    "position is filled",
    "job not found",
    "posting is closed",
    "this job post is no longer",
    "no longer active",
    "this position has been filled",
    "has expired",
)


async def _agent_submit(
    session, app, job, values, cv_path, shot_path, target_url, credentials=None
) -> dict:
    """Primary/fallback auto-submit for unknown ATS via the LLM browser agent: fills
    and submits the form, then records a conservative outcome (only marks
    `submitted` on a real confirmation). Routes a closed posting out of the queue and
    signs in / registers with a stored portal login when a login wall blocks it."""
    from datetime import datetime, timezone

    from app.appliers.agent import run_agent_prefill
    from app.services.notify import chat_id_for_user, notify_user

    # Telegram OTP relay: if the user has Telegram configured, hand the agent a tool
    # to fetch an emailed verification code from them when a portal demands one.
    chat_id = await chat_id_for_user(session, app.user_id)

    # Include the answers the human reviewed/completed (salary, "why this company",
    # availability) plus the role/company, so the agent can fill gaps and ground a
    # genuine motivation. Reviewed answers win on key clashes.
    candidate = {**values, **(app.prefilled_answers or {})}
    candidate.setdefault("applying_for_role", job.title or "")
    if job.company:
        candidate.setdefault("applying_at_company", job.company)
    res = await run_agent_prefill(
        job_url=target_url,
        candidate=candidate,
        cv_path=cv_path,
        shot_path=shot_path,
        do_submit=True,
        credentials=credentials,
        chat_id=chat_id,
        job_title=job.title or "",
        otp_wait_seconds=settings.submit_otp_wait_seconds,
    )
    err = res.get("error")
    submitted = bool(res.get("submitted"))
    closed = bool(res.get("closed"))
    if res.get("screenshot_path"):
        app.screenshot_path = res["screenshot_path"]

    # Closed/removed posting: delete the application entirely (user preference — no
    # clutter, not even Withdrawn) and flag the shared job so discovery won't re-add it.
    if closed and not submitted:
        app_id = str(app.id)
        job.raw = {**(job.raw or {}), "closed": True}
        msg = (
            f"🗑️ {job.title}"
            + (f" at {job.company}" if job.company else "")
            + " is closed (no longer accepting applications) — removed from your list."
        )
        await session.delete(app)
        await session.commit()
        await notify_user(session, app.user_id, msg)
        return {"application_id": app_id, "closed": True, "deleted": True, "agent": True}

    if submitted:
        app.status = ApplicationStatus.submitted
        if app.submitted_at is None:
            app.submitted_at = datetime.now(timezone.utc)
        msg = (
            f"✅ Auto-submitted (AI agent): {job.title}"
            + (f" at {job.company}" if job.company else "")
            + " — the agent reported a confirmation."
        )
    else:
        note = (
            "⚠ The AI agent "
            + (f"hit an error: {err}" if err else "couldn't confirm a submission")
            + ". Open the posting to finish it yourself (a screenshot of where it "
            "got to is attached)."
        )
        app.status = ApplicationStatus.needs_attention
        app.missing_fields = [note] + [
            m for m in (app.missing_fields or []) if m != note
        ]
        msg = (
            f"⚠️ {job.title}: AI auto-submit couldn't confirm it went through — "
            "moved to Needs Fixes. Open the posting to check/finish it."
        )
    session.add(
        ApplicationEvent(
            application_id=app.id,
            type="submitted_auto_agent" if submitted else "submit_attempt_agent",
            payload={
                "applier": "agent",
                "submitted": submitted,
                "error": err,
                "summary": (res.get("summary") or "")[:500],
            },
        )
    )
    await session.commit()
    await notify_user(session, app.user_id, msg)
    return {
        "application_id": str(app.id),
        "confirmed": submitted,
        "closed": closed,
        "agent": True,
        "error": err,
    }


async def _submit(app_id: uuid.UUID) -> dict:
    async with SessionLocal() as session:
        app = await session.get(Application, app_id)
        if app is None:
            return {"error": "application not found"}
        job = await session.get(Job, app.job_id)

        # Anti-throttle: refuse to re-hit the same posting within a short window
        # (stops retry-storms / accidental double-submits that look like a bot).
        from app.services.throttle import on_cooldown

        if on_cooldown(f"submit:{app_id}", seconds=120):
            from app.services.notify import notify_user

            await notify_user(
                session,
                app.user_id,
                f"⏳ {job.title}: auto-submit was just attempted — waiting a bit "
                "before trying the same posting again (avoids looking like a bot). "
                "Give it ~2 minutes, then retry.",
            )
            return {"application_id": str(app_id), "cooldown": True}

        # Resolve where the form actually lives. For a LinkedIn redirect job this
        # turns the linkedin.com URL into the employer's real ATS URL (using the
        # user's own LinkedIn cookie); for Easy Apply / unresolved it returns no
        # URL and we route the application back to the human with an explanation.
        from app.services.linkedin_resolve import resolve_apply_target

        target_url, kind, note = await resolve_apply_target(session, app.user_id, job)
        if target_url is None or any(
            h in target_url.lower() for h in _BLOCKED_HOSTS
        ):
            reason = note or "auto-submit is not allowed for this portal"
            app.status = ApplicationStatus.needs_attention
            app.missing_fields = [reason] + [
                m for m in (app.missing_fields or []) if m != reason
            ]
            session.add(
                ApplicationEvent(
                    application_id=app.id,
                    type="submit_blocked",
                    payload={"kind": kind, "reason": reason},
                )
            )
            await session.commit()
            if kind == "auth":
                # Expired LinkedIn cookie — nudge at most once an hour, not per job.
                from app.services.notify import notify_user_throttled

                await notify_user_throttled(
                    session,
                    app.user_id,
                    reason,
                    key="linkedin_cookie_expired",
                    ttl_seconds=3600,
                )
            else:
                from app.services.notify import notify_user

                await notify_user(session, app.user_id, f"{job.title}: {reason}")
            return {"application_id": str(app_id), "kind": kind, "blocked": True}

        bank = (
            await session.execute(
                select(AnswerBank).where(AnswerBank.user_id == app.user_id)
            )
        ).scalar_one_or_none()
        values = candidate_values((bank.data if bank else {}) or {})
        applier = get_applier(job.source, target_url)

        from app.services.credentials import credentials_for_url

        credentials = await credentials_for_url(session, app.user_id, target_url)

        # CV to attach: the application's tailored CV if present, else the user's
        # default CV version. Shared `files` volume → readable by the worker.
        cv_path: str | None = app.tailored_cv_path
        if not cv_path:
            default_cv = (
                await session.execute(
                    select(CvVersion)
                    .where(CvVersion.user_id == app.user_id)
                    .order_by(CvVersion.is_default.desc(), CvVersion.created_at.desc())
                )
            ).scalars().first()
            cv_path = default_cv.file_path if default_cv else None
        if cv_path and not Path(cv_path).exists():
            cv_path = None

        shot_path = str(
            Path(settings.files_dir) / str(app.user_id) / "submit" / f"{app.id}.png"
        )
        Path(shot_path).parent.mkdir(parents=True, exist_ok=True)

        # Unknown/long-tail platform: no dedicated ATS adapter matched (the generic
        # heuristic sweep barely generalizes), so drive the whole fill-and-submit
        # with the LLM browser agent — it reads the page like a human and works on
        # arbitrary company career sites — instead of clicking Submit on a mostly
        # empty form. Known ATS keep the fast deterministic path below (with the
        # agent only as a fallback). _agent_submit attaches the CV and re-applies
        # the answers the human reviewed (app.prefilled_answers).
        if applier.name == "generic" and settings.agent_applier_enabled:
            return await _agent_submit(
                session, app, job, values, cv_path, shot_path, target_url,
                credentials=credentials,
            )

        prefill = {"filled": {}, "missing": []}
        cv_attached = False
        clicked = False
        confirmed = False
        closed = False
        needs_verification = False
        otp_asked = False
        otp_code_received = False
        submit_diag: str | None = None
        error: str | None = None
        use_agent = False

        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            from app.services.throttle import (
                LAUNCH_ARGS,
                new_human_context,
                pace_host,
            )

            browser = await p.chromium.launch(args=LAUNCH_ARGS)
            try:
                context = await new_human_context(browser)
                page = await context.new_page()
                try:
                    # Polite, human-paced access to this employer's host.
                    await pace_host(target_url)
                    await page.goto(
                        target_url, wait_until="domcontentloaded", timeout=45000
                    )
                    await page.wait_for_timeout(1200)
                    prefill = await applier.prefill(
                        page,
                        values,
                        credentials=credentials,
                        save_draft=False,
                        # Re-apply what the human reviewed/completed (salary,
                        # "why this company", verified answers) so the one-click
                        # finalize submits a complete form, not a blank one.
                        overrides=app.prefilled_answers or {},
                    )
                    if prefill.get("needs_credentials"):
                        # Behind a sign-in / create-account wall. If we have a
                        # (shared) portal login and the agent is on, hand off to the
                        # agent — it signs in, or registers a new account with it if
                        # none exists. Otherwise flag it for the human.
                        if settings.agent_applier_enabled and credentials:
                            use_agent = True
                        else:
                            error = "portal requires a login that isn't stored"
                    elif (
                        settings.agent_applier_enabled
                        and len(prefill.get("filled", {})) < 2
                    ):
                        # The deterministic applier barely filled anything — likely
                        # an obfuscated/SPA form (e.g. Rippling's randomized field
                        # names). Hand off to the Claude agent to fill + submit
                        # instead of clicking submit on a near-empty form.
                        use_agent = True
                    else:
                        if cv_path:
                            cv_attached = await applier.attach_cv(page, cv_path)
                        clicked = await applier.submit(page)
                        # Deterministic fill worked but the applier couldn't find/
                        # click the submit button (obfuscated/SPA form like Rippling,
                        # or required fields it couldn't complete) — escalate to the
                        # Claude agent to finish and submit instead of failing.
                        if not clicked and settings.agent_applier_enabled:
                            use_agent = True
                        # The SPA can take several seconds to transition to the
                        # confirmation or email-verification screen — poll instead
                        # of checking once (a too-early check reads the old form).
                        if clicked:
                            for _ in range(10):  # ~15s
                                await page.wait_for_timeout(1500)
                                try:
                                    body = ((await page.content()) or "").lower()
                                except Exception:  # noqa: BLE001
                                    continue
                                if any(m in body for m in _CONFIRM_MARKERS):
                                    confirmed = True
                                    break
                                if any(m in body for m in _VERIFY_MARKERS):
                                    needs_verification = True
                                    break

                        # OTP relay: the portal emailed a code. Ask the user for it
                        # over Telegram and enter it here (browser still open), so
                        # verified portals can actually finish.
                        if needs_verification and settings.telegram_bot_token:
                            from app.services.notify import (
                                chat_id_for_user,
                                send_telegram,
                                wait_for_telegram_code,
                            )

                            chat_id = await chat_id_for_user(session, app.user_id)
                            if chat_id:
                                otp_asked = True
                                ask_ts = int(time.time())
                                mins = max(1, settings.submit_otp_wait_seconds // 60)
                                await send_telegram(
                                    chat_id,
                                    f"🔐 {job.title}: reply here with the verification "
                                    f"code emailed to you to finish submitting "
                                    f"(within {mins} min).",
                                )
                                code = await wait_for_telegram_code(
                                    chat_id, ask_ts, settings.submit_otp_wait_seconds
                                )
                                if code:
                                    otp_code_received = True
                                    if await applier.submit_verification_code(
                                        page, code
                                    ):
                                        body = ((await page.content()) or "").lower()
                                        confirmed = any(
                                            m in body for m in _CONFIRM_MARKERS
                                        )
                                        needs_verification = (not confirmed) and any(
                                            m in body for m in _VERIFY_MARKERS
                                        )

                        # Closed posting: the page says the job is gone. Detect it so
                        # we route to the closed outcome instead of a misleading
                        # "clicked but couldn't confirm" / "no submit button".
                        if not confirmed and not needs_verification:
                            try:
                                body = ((await page.content()) or "").lower()
                                if any(m in body for m in _CLOSED_MARKERS):
                                    closed = True
                            except Exception:  # noqa: BLE001
                                pass

                        # Ambiguous: clicked but neither confirmed nor a verification
                        # screen appeared — capture any error/alert text so the card
                        # can tell the human what to check.
                        if clicked and not confirmed and not needs_verification and not closed:
                            try:
                                errs = await page.evaluate(
                                    "()=>[...document.querySelectorAll("
                                    "'[role=alert],[aria-invalid=true],[class*=error i]')]"
                                    ".map(e=>(e.innerText||'').trim())"
                                    ".filter(Boolean).slice(0,4)"
                                )
                                submit_diag = "; ".join(errs)[:200] or None
                            except Exception:  # noqa: BLE001
                                submit_diag = None
                except Exception as exc:  # noqa: BLE001
                    error = str(exc)[:300]
                    logger.exception("auto-submit navigation/submit failed")
                try:
                    await page.screenshot(path=shot_path, full_page=True)
                    app.screenshot_path = shot_path
                except Exception:  # noqa: BLE001
                    logger.exception("screenshot failed")
            finally:
                await browser.close()

        # Weak deterministic fill → finish with the LLM agent (its own browser).
        if use_agent:
            return await _agent_submit(
                session, app, job, values, cv_path, shot_path, target_url,
                credentials=credentials,
            )

        # Closed/removed posting: delete the application and flag the shared job so
        # discovery won't re-add it (user preference — remove, don't Withdraw).
        if closed and not confirmed:
            from app.services.notify import notify_user

            app_id = str(app.id)
            job.raw = {**(job.raw or {}), "closed": True}
            msg = (
                f"🗑️ {job.title}"
                + (f" at {job.company}" if job.company else "")
                + " is closed (no longer accepting applications) — removed from "
                "your list."
            )
            await session.delete(app)
            await session.commit()
            await notify_user(session, app.user_id, msg)
            return {"application_id": app_id, "closed": True, "deleted": True}

        app.prefilled_answers = prefill.get("filled", {}) or app.prefilled_answers
        app.missing_fields = prefill.get("missing", []) or app.missing_fields
        app.ai_suggested_fields = (
            prefill.get("ai_suggested", []) or app.ai_suggested_fields
        )
        app.needs_credentials = bool(prefill.get("needs_credentials"))

        verify_note = (
            "⚠ This portal emailed you a verification code to finish submitting — "
            "auto-submit can't receive it. Open the posting and submit there "
            "yourself (your answers are filled and the CV is attached)."
        )
        ambiguous_note = (
            "⚠ Clicked submit but couldn't confirm it went through"
            + (f": {submit_diag}" if submit_diag else " (no confirmation page appeared)")
            + ". Open the posting to check whether it submitted — if not, finish it "
            "there (your answers are filled and the CV is attached)."
        )
        if confirmed:
            from datetime import datetime, timezone

            app.status = ApplicationStatus.submitted
            if app.submitted_at is None:
                app.submitted_at = datetime.now(timezone.utc)
        elif needs_verification:
            # Can't pass an emailed OTP from a throwaway browser — route it to the
            # human with a clear explanation instead of silently failing.
            app.status = ApplicationStatus.needs_attention
            app.missing_fields = [verify_note] + [
                m for m in (app.missing_fields or []) if m != verify_note
            ]
        elif clicked:
            # Submitted but no confirmation detected — don't claim success and don't
            # leave it in Ready (risking a double-submit); flag for the human to
            # verify on the portal.
            app.status = ApplicationStatus.needs_attention
            app.missing_fields = [ambiguous_note] + [
                m for m in (app.missing_fields or []) if m != ambiguous_note
            ]
        else:
            # Couldn't even click submit (error / no button) — surface it.
            err_note = (
                "⚠ Couldn't submit automatically: "
                + (error or "no submit button was found")
                + ". Open the posting and submit it manually."
            )
            app.status = ApplicationStatus.needs_attention
            app.missing_fields = [err_note] + [
                m for m in (app.missing_fields or []) if m != err_note
            ]
        session.add(
            ApplicationEvent(
                application_id=app.id,
                type=(
                    "submitted_auto"
                    if confirmed
                    else "submit_needs_verification"
                    if needs_verification
                    else "submit_attempt"
                ),
                payload={
                    "applier": applier.name,
                    "cv_attached": cv_attached,
                    "clicked_submit": clicked,
                    "confirmed": confirmed,
                    "needs_verification": needs_verification,
                    "diag": submit_diag,
                    "filled": len(prefill.get("filled", {})),
                    "missing": len(prefill.get("missing", [])),
                    "error": error,
                },
            )
        )
        await session.commit()

        from app.services.notify import notify_user

        if confirmed:
            via = (
                " — verified with the code you sent."
                if otp_code_received
                else " — confirmation detected on the portal."
            )
            msg = (
                f"✅ Auto-submitted: {job.title}"
                + (f" at {job.company}" if job.company else "")
                + via
            )
        elif needs_verification:
            if otp_asked and not otp_code_received:
                extra = " I asked for the code on Telegram but didn't get it in time."
            elif otp_code_received:
                extra = " The code didn't go through — please finish in your browser."
            else:
                extra = ""
            msg = (
                f"📧 {job.title}: needs an emailed verification code to submit.{extra} "
                "Open the posting and submit there yourself; everything's filled in."
            )
        elif clicked:
            detail = f" ({submit_diag})" if submit_diag else ""
            msg = (
                f"⚠️ {job.title}: clicked submit but couldn't confirm it went "
                f"through{detail}. Moved to Needs Fixes — open the posting to check "
                "whether it submitted, and finish it there if not."
            )
        else:
            why = error or "no submit button was found"
            msg = (
                f"⚠️ Couldn't auto-submit {job.title}: {why}. Moved to Needs Fixes — "
                "review it on the board."
            )
        await notify_user(session, app.user_id, msg)

    return {
        "application_id": str(app_id),
        "clicked_submit": clicked,
        "confirmed": confirmed,
        "needs_verification": needs_verification,
        "error": error,
    }


@celery_app.task(name="submit.run")
def submit_application(app_id: str) -> dict:
    return asyncio.run(_submit(uuid.UUID(app_id)))
