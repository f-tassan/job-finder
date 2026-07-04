"""Telegram bot service — the primary action surface of job-finder.

Runs as its own container (`python -m app.bot`) and long-polls getUpdates; it is
the ONLY consumer of getUpdates (outbound notifications elsewhere use plain
sendMessage/sendDocument, which don't conflict).

What it does:
  * Discovery messages (sent by the discovery task) carry inline buttons; this
    service handles the taps:
      - 📄 CV / ✉️ Letter / 📄+✉️ Both  -> queue tailoring; the PDFs come back
        to the same chat (tailor task), ready to upload on the job portal.
      - ✅ I applied                    -> mark the application submitted
        (this is how jobs get marked submitted without touching the web page).
      - 🙈 Skip                         -> drop the tracked application.
      - 🔗 Apply link                   -> resolve a LinkedIn posting's real
        employer apply URL (uses the user's stored LinkedIn cookie).
  * Commands: /jobs (top matches), /status (pipeline), /discover (admin),
    /start /help.
  * Any other text goes to the LLM assistant (cheap model) with a compact
    snapshot of the user's pipeline as context.

Users are matched to chats via the telegram_chat_id they saved in Settings —
an unknown chat gets a hint with its chat id and is never given data access.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import func, select

from app.config import settings
from app.db import SessionLocal
from app.models import (
    AnswerBank,
    Application,
    ApplicationEvent,
    ApplicationStatus,
    AppUser,
    Job,
    JobMatch,
)

logger = logging.getLogger(__name__)

_OFFSET_KEY = "tg:bot:offset"

_HELP = (
    "I find jobs for you and prepare tailored documents.\n\n"
    "• When discovery finds a strong match, I message you the job with its "
    "details, link, and buttons.\n"
    "• Tap 📄 Generate CV / ✉️ Generate Cover Letter and I'll build a tailored "
    "PDF for that exact job and send it here — you apply on the site yourself "
    "and upload it. Nothing is generated until you ask (no wasted credits).\n"
    "• Tap ✅ I applied afterwards and I'll track it as submitted — no need to "
    "touch the dashboard.\n\n"
    "Commands:\n"
    "/jobs — your current top matches\n"
    "/status — your pipeline at a glance\n"
    "/help — this message\n\n"
    "You can also just ask me things like “any new data jobs?” or “what did I "
    "apply to this week?”."
)


def job_buttons(app_id: str, *, linkedin: bool = False) -> dict:
    """Inline keyboard for one tracked job. Shared with the discovery task so
    every job message in the chat behaves the same. Documents are generated
    ONLY when their button is tapped — never automatically — so no LLM credits
    are spent on jobs the user doesn't pursue."""
    rows = [
        [{"text": "✅ I applied", "callback_data": f"applied:{app_id}"}],
        [
            {"text": "📄 Generate CV", "callback_data": f"cv:{app_id}"},
            {"text": "✉️ Generate Cover Letter", "callback_data": f"cl:{app_id}"},
        ],
        [{"text": "🙈 Skip", "callback_data": f"skip:{app_id}"}],
    ]
    if linkedin:
        rows[2].append({"text": "🔗 Apply link", "callback_data": f"link:{app_id}"})
    return {"inline_keyboard": rows}


def _esc(s: str | None) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


async def notify_job_card(
    session,
    user_id,
    app_id,
    job: Job,
    *,
    score: float | None = None,
    header: str = "🆕 <b>New job discovered</b>",
) -> bool:
    """Send one job as a card with action buttons to the user's chat. Shared by
    discovery and by manual track/add so every tracked job looks identical.
    No-op (returns False) if the user has no chat configured."""
    from app.services.notify import chat_id_for_user, send_telegram

    chat_id = await chat_id_for_user(session, user_id)
    if not chat_id:
        return False
    return await send_telegram(
        chat_id,
        format_job_html(job, score, header=header),
        parse_mode="HTML",
        reply_markup=job_buttons(str(app_id), linkedin="linkedin" in (job.source or "")),
    )


def format_job_html(
    job: Job, score: float | None = None, *, header: str | None = None
) -> str:
    """A job notification card: headline, company/location, match %, a short
    excerpt of the posting, and the link to apply."""
    parts: list[str] = []
    if header:
        parts.append(header)
    parts.append(f"<b>{_esc(job.title)}</b>")
    line2 = " · ".join(p for p in (job.company, job.location) if p)
    if line2:
        parts.append(f"🏢 {_esc(line2)}")
    meta = [job.source]
    if score is not None:
        meta.append(f"match {round(score * 100)}%")
    parts.append(" · ".join(meta))
    if job.description:
        snippet = " ".join((job.description or "").split())
        if len(snippet) > 300:
            snippet = snippet[:300].rsplit(" ", 1)[0] + "…"
        parts.append(f"<i>{_esc(snippet)}</i>")
    parts.append(f"🔗 {job.url}")
    return "\n".join(parts)


class Bot:
    def __init__(self) -> None:
        self.token = settings.telegram_bot_token
        self.base = f"https://api.telegram.org/bot{self.token}"
        import redis.asyncio as aioredis

        self.redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        self.http = httpx.AsyncClient(timeout=70)

    async def api(self, method: str, **payload) -> dict | None:
        try:
            resp = await self.http.post(f"{self.base}/{method}", json=payload)
            if resp.status_code != 200:
                logger.warning("telegram %s -> %s %s", method, resp.status_code, resp.text[:200])
                return None
            return resp.json().get("result")
        except Exception:  # noqa: BLE001
            logger.exception("telegram %s failed", method)
            return None

    async def send(self, chat_id: str, text: str, **kw) -> None:
        await self.api(
            "sendMessage",
            chat_id=chat_id,
            text=text,
            disable_web_page_preview=True,
            **kw,
        )

    # --- update loop -------------------------------------------------------

    async def run(self) -> None:
        logger.info("bot: long-polling for updates")
        self._tasks: set[asyncio.Task] = set()
        while True:
            offset = await self.redis.get(_OFFSET_KEY)
            params: dict = {
                "timeout": 50,
                # MUST be a JSON-serialized array — Telegram ignores any other
                # encoding and keeps the previously stored preference, which
                # would silently drop callback_query updates (button taps).
                "allowed_updates": json.dumps(["message", "callback_query"]),
            }
            if offset:
                params["offset"] = int(offset)
            try:
                resp = await self.http.get(f"{self.base}/getUpdates", params=params)
                if resp.status_code != 200:
                    logger.warning(
                        "getUpdates -> %s %s", resp.status_code, resp.text[:200]
                    )
                    await asyncio.sleep(3)
                    continue
                updates = resp.json().get("result", [])
            except Exception:  # noqa: BLE001 - network blip; retry
                logger.exception("getUpdates failed")
                await asyncio.sleep(5)
                continue
            for u in updates:
                await self.redis.set(_OFFSET_KEY, u["update_id"] + 1)
                # Handle concurrently so a slow handler (LLM chat, LinkedIn
                # resolve) doesn't block button taps from other users. Keep a
                # reference: bare fire-and-forget tasks can be GC'd mid-run.
                task = asyncio.create_task(self._safe_handle(u))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

    async def _safe_handle(self, update: dict) -> None:
        try:
            if "callback_query" in update:
                await self.on_callback(update["callback_query"])
            elif "message" in update:
                await self.on_message(update["message"])
        except Exception:  # noqa: BLE001 - one bad update must not kill the loop
            logger.exception("update handling failed: %s", update.get("update_id"))

    # --- helpers ------------------------------------------------------------

    async def _user_for_chat(self, session, chat_id: str) -> AppUser | None:
        bank = (
            await session.execute(
                select(AnswerBank).where(
                    AnswerBank.notifications["telegram_chat_id"].astext
                    == str(chat_id)
                )
            )
        ).scalar_one_or_none()
        if bank is None:
            return None
        return await session.get(AppUser, bank.user_id)

    async def _owned_app(self, session, user: AppUser, app_id: str) -> Application | None:
        try:
            aid = uuid.UUID(app_id)
        except ValueError:
            return None
        app = await session.get(Application, aid)
        if app is None or app.user_id != user.id:
            return None
        return app

    # --- messages -----------------------------------------------------------

    async def on_message(self, msg: dict) -> None:
        chat_id = str((msg.get("chat") or {}).get("id") or "")
        text = (msg.get("text") or "").strip()
        if not chat_id or not text:
            return
        logger.info("message from chat %s: %.60s", chat_id, text)
        async with SessionLocal() as session:
            user = await self._user_for_chat(session, chat_id)
            if user is None:
                await self.send(
                    chat_id,
                    f"Hi! I don't know this chat yet. Your chat id is {chat_id} — "
                    "paste it into job-finder → Settings → Telegram chat ID, then "
                    "message me again.",
                )
                return
            cmd = text.split("@")[0].lower() if text.startswith("/") else None
            if cmd in ("/start", "/help"):
                await self.send(chat_id, _HELP)
            elif cmd == "/status":
                await self.cmd_status(session, user, chat_id)
            elif cmd == "/jobs":
                await self.cmd_jobs(session, user, chat_id)
            elif cmd == "/discover":
                if not user.is_admin:
                    await self.send(chat_id, "Only the admin can trigger discovery.")
                    return
                from app.tasks.discovery import run_discovery

                run_discovery.delay()
                await self.send(
                    chat_id,
                    "🔎 Discovery queued — new strong matches will land here.",
                )
            elif cmd:
                await self.send(chat_id, "Unknown command — try /help.")
            else:
                await self.chat_llm(session, user, chat_id, text)

    async def cmd_status(self, session, user: AppUser, chat_id: str) -> None:
        rows = (
            await session.execute(
                select(Application.status, func.count())
                .where(Application.user_id == user.id)
                .group_by(Application.status)
            )
        ).all()
        counts = {s.value: n for s, n in rows}
        order = [s.value for s in ApplicationStatus]
        lines = [
            f"{label}: {counts[label]}" for label in order if counts.get(label)
        ]
        await self.send(
            chat_id,
            "📊 Your pipeline\n" + ("\n".join(lines) if lines else "Nothing tracked yet."),
        )

    async def cmd_jobs(self, session, user: AppUser, chat_id: str, limit: int = 5) -> None:
        """Top-ranked matches that haven't been applied to / skipped yet, each as
        its own message with action buttons."""
        rows = (
            await session.execute(
                select(JobMatch, Job)
                .join(Job, Job.id == JobMatch.job_id)
                .where(JobMatch.user_id == user.id)
                .order_by(JobMatch.relevance_score.desc())
                .limit(40)
            )
        ).all()
        if not rows:
            await self.send(
                chat_id,
                "No matches yet — discovery may not have run, or your profile "
                "is empty. Check the dashboard.",
            )
            return
        apps = {
            a.job_id: a
            for a in (
                await session.execute(
                    select(Application).where(Application.user_id == user.id)
                )
            ).scalars()
        }
        sent = 0
        for match, job in rows:
            if sent >= limit:
                break
            existing = apps.get(job.id)
            if existing and existing.status != ApplicationStatus.discovered:
                continue  # already acted on (docs made / applied / closed)
            if existing is None:
                existing = Application(
                    user_id=user.id,
                    job_id=job.id,
                    status=ApplicationStatus.discovered,
                )
                session.add(existing)
                await session.flush()
                session.add(
                    ApplicationEvent(
                        application_id=existing.id,
                        type="created",
                        payload={"via": "telegram_jobs"},
                    )
                )
                await session.commit()
            await self.send(
                chat_id,
                format_job_html(job, match.relevance_score),
                parse_mode="HTML",
                reply_markup=job_buttons(
                    str(existing.id), linkedin="linkedin" in (job.source or "")
                ),
            )
            sent += 1
        if sent == 0:
            await self.send(
                chat_id,
                "You've already acted on all your current top matches — nice. "
                "New ones will arrive after the next discovery run.",
            )

    async def chat_llm(self, session, user: AppUser, chat_id: str, text: str) -> None:
        """Free-text questions: answer from a compact snapshot of the user's data."""
        from app.services import llm

        rows = (
            await session.execute(
                select(JobMatch, Job)
                .join(Job, Job.id == JobMatch.job_id)
                .where(JobMatch.user_id == user.id)
                .order_by(JobMatch.relevance_score.desc())
                .limit(10)
            )
        ).all()
        apps = (
            await session.execute(
                select(Application)
                .where(Application.user_id == user.id)
                .order_by(Application.updated_at.desc())
                .limit(15)
            )
        ).scalars().all()
        bank = (
            await session.execute(
                select(AnswerBank).where(AnswerBank.user_id == user.id)
            )
        ).scalar_one_or_none()
        ctx = {
            "user": user.display_name or user.email,
            "field": bank.field if bank else None,
            "top_matches": [
                {
                    "title": j.title,
                    "company": j.company,
                    "location": j.location,
                    "score": round(m.relevance_score, 2),
                    "url": j.url,
                }
                for m, j in rows
            ],
            "recent_applications": [
                {
                    "title": a.job.title,
                    "company": a.job.company,
                    "status": a.status.value,
                    "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
                }
                for a in apps
            ],
        }
        answer = await llm.complete_text(
            system=(
                "You are job-finder's Telegram assistant for a Saudi job seeker. "
                "Answer briefly and concretely from the provided data only. "
                "Actions you can point them to: /jobs lists top matches with "
                "buttons to generate a tailored CV / cover letter (delivered "
                "here as PDFs) and to mark a job applied; the web dashboard has "
                "the full history. Never invent jobs or statuses."
            ),
            prompt=f"DATA:\n{json.dumps(ctx, ensure_ascii=False)}\n\nUSER: {text}",
        )
        await self.send(
            chat_id,
            answer or "I couldn't process that right now — try /jobs or /status.",
        )

    # --- callbacks ----------------------------------------------------------

    async def on_callback(self, cb: dict) -> None:
        cb_id = cb.get("id")
        data = cb.get("data") or ""
        msg = cb.get("message") or {}
        chat_id = str((msg.get("chat") or {}).get("id") or "")
        action, _, app_id = data.partition(":")
        logger.info("callback %r from chat %s", data, chat_id)

        async def ack(text: str | None = None) -> None:
            payload: dict = {"callback_query_id": cb_id}
            if text:
                payload["text"] = text
            await self.api("answerCallbackQuery", **payload)

        if not chat_id or not action or not app_id:
            await ack()
            return

        async with SessionLocal() as session:
            user = await self._user_for_chat(session, chat_id)
            if user is None:
                await ack("This chat isn't linked to a job-finder account.")
                return
            app = await self._owned_app(session, user, app_id)
            if app is None:
                await ack("That job is no longer tracked.")
                return
            job = await session.get(Job, app.job_id)

            if action in ("cv", "cl", "both"):
                from app.tasks.tailor import tailor_application

                make_cv = action in ("cv", "both")
                make_letter = action in ("cl", "both")
                tailor_application.delay(str(app.id), make_cv, make_letter)
                await ack("Generating — your PDFs will arrive here shortly ⏳")

            elif action == "applied":
                app.status = ApplicationStatus.submitted
                if app.submitted_at is None:
                    app.submitted_at = datetime.now(timezone.utc)
                session.add(
                    ApplicationEvent(
                        application_id=app.id,
                        type="submitted",
                        payload={"via": "telegram"},
                    )
                )
                await session.commit()
                await ack("Marked as submitted ✅")
                await self.send(
                    chat_id,
                    f"📨 Tracked as submitted: {job.title}"
                    + (f" at {job.company}" if job.company else "")
                    + ". Good luck! I'll keep it on your board.",
                )

            elif action == "skip":
                await session.delete(app)
                await session.commit()
                await ack("Skipped 🙈")

            elif action == "link":
                await ack("Resolving the employer's apply link…")
                from app.services.linkedin_resolve import resolve_apply_target

                url, kind, note = await resolve_apply_target(session, user.id, job)
                await session.commit()  # persist the cached apply_url
                if url and kind in ("direct", "offsite"):
                    await self.send(chat_id, f"🔗 Direct apply link:\n{url}")
                else:
                    await self.send(chat_id, note or "Couldn't resolve an apply link.")

            else:
                await ack()


async def _main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not settings.telegram_bot_token:
        # Stay alive but idle so compose doesn't crash-loop when unconfigured.
        logger.warning("TELEGRAM_BOT_TOKEN not set — bot idle")
        while True:
            await asyncio.sleep(3600)
    await Bot().run()


if __name__ == "__main__":
    asyncio.run(_main())
