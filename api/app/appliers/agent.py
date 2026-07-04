"""LLM browser-agent applier (browser-use) — opt-in, self-healing fallback.

Unlike the deterministic appliers (which match fields by CSS/label heuristics),
this drives an LLM agent that *reads* the page and fills the form like a human
would. It is resilient to DOM changes and unknown portals, but costs many LLM
calls per form, so it is OFF by default (`settings.agent_applier_enabled`) and
intended only as a fallback when the heuristic appliers leave a form mostly empty.

It owns its OWN browser session (browser-use manages the browser), so it does not
use the Playwright `page` the prefill task passes to the other appliers — instead
the task calls `run_agent_prefill(...)` directly.

HARD RULES enforced in the task prompt (CLAUDE.md):
- Never invent data — fill only from the candidate's answer bank.
- Leave salary / "why this company" / cover-letter / unknown fields blank.
- NEVER click a final submit button. The human submits.
"""
from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

_TASK_TEMPLATE = """\
You are pre-filling a job application form for a candidate on this page: {url}

Fill the form using ONLY this candidate data — never invent anything:
{candidate}

If a Resume/CV file upload field exists, upload the candidate's resume using the
upload-file action with the provided file path.

Fill EVERY field the candidate data supports — INCLUDING gender, marital status, date
of birth, and nationality when those values appear in the data above (these are often
in a "Diversity" / "Personal Information" section; fill them from the data, do not skip
them). Leave blank only voluntary self-identification questions you have no data for (e.g.
ethnicity, disability, veteran/military status). Never invent a value you were not
given. For open-ended MOTIVATION questions ("why do you want
to work here / join us / this role", short cover-letter prompts), write a genuine
2-3 sentence answer grounded ONLY in the candidate's real background (their field,
skills, experience) and the role/company on the page — never invent facts,
employers, or metrics.

HARD RULE: Do NOT click "Submit", "Submit Application", or any final submit
button. Stop once the visible form is filled and the resume (if any) is attached.
{credentials_clause}
When you stop, report two lists: the fields you FILLED, and the fields you LEFT
BLANK with the reason.
"""

# Submit variant: used ONLY by the explicit, user-triggered auto-submit task for
# standalone ATS the deterministic appliers can't handle. Per CLAUDE.md this is
# allowed for standalone ATS on the user's confirmation (never LinkedIn/Bayt —
# the caller guarantees the URL isn't one of those).
_SUBMIT_TEMPLATE = """\
You are completing and SUBMITTING a job application for a candidate on this page:
{url}
(The candidate has explicitly authorized submitting this application.)

FIRST, make sure the application form is actually open:
- If the page looks empty or is still loading, wait a few seconds and RELOAD it
  once (these ATS pages are slow single-page apps).
- If the page says the job is closed, filled, expired, or "no longer available", or
  shows "job not found" / no application form and no Apply button, STOP: report that
  the posting is CLOSED and that you did NOT submit. Do not invent a submission.
- If the form isn't visible yet but there is an "Apply", "Apply now", or "Apply
  for this job" button, click it to open the application form.

Fill the form using ONLY this candidate data — never invent anything:
{candidate}

If a Resume/CV upload field exists, upload the résumé with the upload-file action
and the provided file path.

Fill EVERY field the candidate data supports — INCLUDING gender, marital status, date
of birth, and nationality when those values appear in the data above (these are often
in a "Diversity" / "Personal Information" section; fill them from the data, do not skip
them). Leave blank only voluntary self-identification questions you have no data for (e.g.
ethnicity, disability, veteran/military status). Never invent a value you were not
given. For open-ended MOTIVATION questions ("why do you want
to work here / join us / this role", short cover-letter prompts), write a genuine
2-3 sentence answer grounded ONLY in the candidate's real background (field, skills,
experience) and the role/company on the page — never invent facts. If a REQUIRED
field has no value in the candidate data (e.g. salary), request it from the applicant
using ask_applicant_for_info (see below); only if that's unavailable or unanswered,
leave it blank and report it.

After the form is filled and the résumé attached, click the final "Submit" /
"Submit Application" button. Then look for a real confirmation (e.g. "thank you for
applying", "application received/submitted", "we have received your application").
{credentials_clause}{otp_clause}
When you stop, report: whether you actually clicked submit, whether a real
confirmation page appeared (answer CONFIRMED only if the portal explicitly
acknowledged receipt; otherwise NOT_CONFIRMED — on its own line), the fields you
FILLED, and any REQUIRED fields you had to leave blank.
"""

# What we tell the agent when the user has stored a (shared) portal login and the
# form is gated behind sign-in / account creation. Only injected when creds exist.
_CREDS_CLAUSE = """\
If the form is behind a sign-in or "create account / register" wall, you MAY
authenticate to reach it, using ONLY these credentials (never any others):
  email / username: {username}
  password: {password}
Sign in if an account exists; if the site instead offers to create/register an
account, register with the SAME credentials (set and confirm the password, fill name
from the candidate data). If it then asks for an emailed verification code, use the
get_email_verification_code tool (see below) to obtain it and continue.
"""

# Injected only when a Telegram OTP relay is available for this user. Tells the agent
# to fetch an emailed verification code from the applicant (via Telegram) instead of
# giving up on it. Kept on its OWN line block so the report instruction stays separate.
_OTP_CLAUSE = """
VERIFICATION CODES: if the page asks for a one-time code / OTP that was emailed to the
applicant (to submit, or to verify a new account), call the get_email_verification_code
tool — it asks the applicant for the code and returns it. Then type the returned code
into the code field(s) and continue. Only call it when a code is genuinely required; if
the tool reports no code was received, STOP and report that verification is pending.
MISSING REQUIRED INFO: if a REQUIRED field has no value in the candidate data — for
example expected salary, or any other required detail — call ask_applicant_for_info,
passing every missing field's label in a SINGLE call (one per line). It asks the
applicant and returns their answers; fill them in and continue. Ask only for fields that
are genuinely required AND genuinely missing from the data — never for values you were
already given.
"""

# Phrases that POSITIVELY indicate the portal accepted the application. "confirmed"
# alone is deliberately NOT here — the agent writes "CONFIRMED: the job is expired",
# which must not read as a submission. A real success carries one of these phrases.
_CONFIRM_HINTS = (
    "thank you for applying",
    "thank you for your application",
    "application received",
    "application has been received",
    "application submitted",
    "successfully submitted",
    "we have received your application",
    "your application was submitted",
    "thanks for applying",
    "submitted your application",
    "application complete",
)

# The posting is gone / no form / nothing was sent — a hard veto on any positive
# reading, and the signal that routes the app to a "posting closed" outcome.
_CLOSED_HINTS = (
    "no longer available",
    "job post is no longer",
    "has been filled",
    "already been filled",
    "already filled",
    "position is filled",
    "no longer accepting",
    "not accepting applications",
    "job not found",
    "posting is closed",
    "posting has closed",
    "expired or removed",
    "no application form",
    "form is not available",
    "no form present",
    "job is closed",
)

# Explicit non-submission markers — a veto even if a positive phrase also appears.
_NEGATIVE_HINTS = (
    "not_confirmed",
    "not confirmed",
    "not submitted",
    "was not submitted",
    "could not submit",
    "couldn't submit",
    "could not be performed",
    "unable to submit",
    "did not submit",
    "submit action: not",
    "submit clicked: no",
    "stopped before submission",
    "submission could not proceed",
)


def _build_llm():
    """Pick the LLM by which provider key is actually configured. If the chosen
    model id matches an available key, use it; otherwise fall back to whichever
    key exists with that provider's default model (so the agent works whether the
    deployment has an Anthropic or an OpenAI key). Returns (llm, error)."""
    model = settings.agent_applier_model
    is_gpt = model.lower().startswith(("gpt", "o1", "o3", "o4"))
    has_anthropic = bool(settings.anthropic_api_key)
    has_openai = bool(settings.openai_api_key)

    # Configured model's own provider has a key → use it as-is.
    if not is_gpt and has_anthropic:
        from browser_use.llm import ChatAnthropic

        return ChatAnthropic(model=model), None
    if is_gpt and has_openai:
        from browser_use.llm import ChatOpenAI

        return ChatOpenAI(model=model), None

    # Configured model's provider key is missing — fall back to whatever IS set.
    if has_anthropic:
        from browser_use.llm import ChatAnthropic

        return ChatAnthropic(model="claude-sonnet-5"), None
    if has_openai:
        from browser_use.llm import ChatOpenAI

        return ChatOpenAI(model="gpt-4.1"), None
    return None, "no Anthropic/OpenAI key configured for the agent applier"


def _build_otp_tools(chat_id: str, job_title: str, wait_seconds: int):
    """A browser-use Tools registry exposing `get_email_verification_code`: it asks the
    applicant (over Telegram) for the emailed OTP and returns it to the agent, so a
    verified portal / account-creation step can complete mid-run without the browser
    session being lost. Returns None if browser-use's Tools/ActionResult aren't
    importable (the agent then just runs without the tool)."""
    try:
        from browser_use import ActionResult, Tools
    except Exception:  # noqa: BLE001
        return None

    tools = Tools()

    @tools.action(
        "Get the email verification / one-time code (OTP) from the applicant. Call this "
        "only when the page asks for a code that was emailed to the applicant. Returns "
        "the code to type into the verification field."
    )
    async def get_email_verification_code() -> ActionResult:  # noqa: D401
        import time as _t

        from app.services.notify import send_telegram, wait_for_telegram_code

        ask_ts = int(_t.time())
        mins = max(1, wait_seconds // 60)
        await send_telegram(
            chat_id,
            f"🔐 {job_title or 'Your application'}: reply here with the verification "
            f"code emailed to you to continue applying (within {mins} min).",
        )
        code = await wait_for_telegram_code(chat_id, ask_ts, wait_seconds)
        if not code:
            return ActionResult(
                extracted_content=(
                    "NO_CODE: the applicant did not reply with a code in time. Stop and "
                    "report that email verification is still pending."
                ),
                include_in_memory=True,
            )
        return ActionResult(
            extracted_content=f"The verification code is {code}. Enter it and continue.",
            long_term_memory=f"Email verification code from applicant: {code}",
            include_in_memory=True,
        )

    @tools.action(
        "Ask the applicant (over Telegram) for REQUIRED information missing from the "
        "candidate data — e.g. expected salary or any required field you have no value "
        "for. Pass `fields` as the field labels you need, one per line or separated by "
        "semicolons (batch ALL missing fields into ONE call). Returns the applicant's "
        "answers to fill in."
    )
    async def ask_applicant_for_info(fields: str) -> ActionResult:  # noqa: D401
        import re as _re
        import time as _t

        from app.services.notify import send_telegram, wait_for_telegram_reply

        labels = [x.strip() for x in _re.split(r"[\n;]+", fields or "") if x.strip()]
        if not labels:
            return ActionResult(
                extracted_content="No fields were specified to ask for.",
                include_in_memory=True,
            )
        labels = labels[:12]
        numbered = "\n".join(f"{i}. {lbl}" for i, lbl in enumerate(labels, 1))
        ask_ts = int(_t.time())
        mins = max(1, wait_seconds // 60)
        await send_telegram(
            chat_id,
            f"📝 {job_title or 'Your application'} needs a few details to finish "
            f"applying. Reply in ONE message, each answer on its own line, IN THIS "
            f"ORDER (within {mins} min):\n\n{numbered}",
        )
        reply = await wait_for_telegram_reply(chat_id, ask_ts, wait_seconds)
        if not reply:
            return ActionResult(
                extracted_content=(
                    "NO_REPLY: the applicant did not send the details in time. Stop and "
                    "report which required fields are still missing: " + "; ".join(labels)
                ),
                include_in_memory=True,
            )
        return ActionResult(
            extracted_content=(
                "You asked the applicant for these fields (in order):\n"
                f"{numbered}\n\nThe applicant replied:\n{reply}\n\n"
                "Map each answer to its field (same order; they may include labels) and "
                "fill them into the form, then continue."
            ),
            long_term_memory=f"Applicant-provided details: {reply}",
            include_in_memory=True,
        )

    return tools


async def run_agent_prefill(
    *,
    job_url: str,
    candidate: dict,
    cv_path: str | None,
    shot_path: str | None = None,
    max_steps: int = 40,
    do_submit: bool = False,
    credentials: dict | None = None,
    chat_id: str | None = None,
    job_title: str = "",
    otp_wait_seconds: int = 180,
) -> dict:
    """Drive an LLM browser agent to fill `job_url`'s form. Submits only when
    `do_submit` is True (explicit auto-submit path); otherwise never submits.

    `credentials` (optional {username, password}) let the agent sign in or register
    when the form is gated behind a login wall — used only when the user has stored
    a portal login.

    Returns {"summary", "final_url", "screenshot_path", "submitted", "closed",
    "error"}. `closed` means the posting was gone (expired/filled/not found) so
    nothing was or could be submitted. Soft-fails (returns an error) so the caller
    can fall back.
    """
    try:
        from browser_use import Agent
        from browser_use.browser.profile import BrowserProfile
    except Exception as exc:  # noqa: BLE001
        return {"error": f"browser-use not installed: {exc}"}

    llm, err = _build_llm()
    if err:
        return {"error": err}

    creds_clause = ""
    if credentials and credentials.get("username") and credentials.get("password"):
        creds_clause = _CREDS_CLAUSE.format(
            username=credentials["username"], password=credentials["password"]
        )
    # OTP relay: when submitting and the user has Telegram set up, give the agent a
    # tool to fetch an emailed verification code from them mid-run.
    otp_clause = ""
    otp_tools = None
    if do_submit and chat_id and settings.telegram_bot_token:
        otp_tools = _build_otp_tools(chat_id, job_title, otp_wait_seconds)
        if otp_tools is not None:
            otp_clause = _OTP_CLAUSE
    template = _SUBMIT_TEMPLATE if do_submit else _TASK_TEMPLATE
    task = template.format(
        url=job_url,
        candidate=json.dumps(candidate, ensure_ascii=False),
        credentials_clause=creds_clause,
        otp_clause=otp_clause,
    )
    files = [cv_path] if cv_path and Path(cv_path).exists() else []

    # Polite, human-paced access to this host before the agent starts driving it.
    try:
        from app.services.throttle import LAUNCH_ARGS, pace_host

        await pace_host(job_url)
        profile = BrowserProfile(headless=True, args=LAUNCH_ARGS)
    except Exception:  # noqa: BLE001 - some browser-use versions reject `args`
        profile = BrowserProfile(headless=True)

    agent_kwargs = dict(
        task=task,
        llm=llm,
        browser_profile=profile,
        available_file_paths=files,
        use_vision=True,
    )
    if otp_tools is not None:
        agent_kwargs["tools"] = otp_tools
    agent = Agent(**agent_kwargs)
    try:
        history = await agent.run(max_steps=max_steps)
    except Exception as exc:  # noqa: BLE001
        logger.exception("agent applier run failed")
        return {"error": str(exc)[:300]}

    # browser-use resets its browser session at the end of run(), so we can't
    # screenshot it afterwards; grab the last per-step screenshot from history.
    saved_shot = None
    if shot_path:
        try:
            Path(shot_path).parent.mkdir(parents=True, exist_ok=True)
            paths = [p for p in (history.screenshot_paths() or []) if p]
            if paths and Path(paths[-1]).exists():
                Path(shot_path).write_bytes(Path(paths[-1]).read_bytes())
                saved_shot = shot_path
            else:
                shots = [s for s in (history.screenshots() or []) if s]
                if shots:  # base64-encoded frames
                    Path(shot_path).write_bytes(base64.b64decode(shots[-1]))
                    saved_shot = shot_path
        except Exception:  # noqa: BLE001
            logger.debug("agent screenshot capture failed", exc_info=True)

    final_url = ""
    try:
        urls = [u for u in (history.urls() or []) if u]
        final_url = urls[-1] if urls else ""
    except Exception:  # noqa: BLE001
        pass
    summary = ""
    try:
        summary = history.final_result() or ""
    except Exception:  # noqa: BLE001
        pass
    # Conservative confirmation: only when submitting AND the agent's report shows
    # an explicit CONFIRMED / confirmation phrase (and not a NOT_CONFIRMED line).
    low = (summary or "").lower()
    closed = any(h in low for h in _CLOSED_HINTS)
    negative = any(h in low for h in _NEGATIVE_HINTS)
    # Only a genuine confirmation phrase counts — and never when the posting was
    # closed or the agent said it didn't submit. This is what stops "CONFIRMED: the
    # job is expired" from being misread as a successful submission.
    submitted = bool(
        do_submit
        and not closed
        and not negative
        and any(h in low for h in _CONFIRM_HINTS)
    )
    return {
        "summary": summary,
        "final_url": final_url,
        "screenshot_path": saved_shot,
        "submitted": submitted,
        "closed": closed and not submitted,
        "error": None,
    }
