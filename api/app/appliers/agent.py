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
(This is a public application form — no login/account is required.)

Fill the form using ONLY this candidate data — never invent anything:
{candidate}

If a Resume/CV file upload field exists, upload the candidate's resume using the
upload-file action with the provided file path.

Leave BLANK (do not guess) any field you cannot truthfully answer from the data —
especially expected/current SALARY, "why do you want to work here", cover letter,
and demographic/voluntary self-identification questions.

HARD RULE: Do NOT click "Submit", "Submit Application", or any final submit
button. Stop once the visible form is filled and the resume (if any) is attached.

When you stop, report two lists: the fields you FILLED, and the fields you LEFT
BLANK with the reason.
"""


async def run_agent_prefill(
    *,
    job_url: str,
    candidate: dict,
    cv_path: str | None,
    shot_path: str | None = None,
    max_steps: int = 40,
) -> dict:
    """Drive an LLM browser agent to fill `job_url`'s form. Never submits.

    Returns {"summary": str, "final_url": str, "screenshot_path": str|None,
    "error": str|None}. Soft-fails (returns an error string) so the caller can
    fall back to the deterministic result.
    """
    if not settings.openai_api_key:
        return {"error": "no OpenAI key configured for the agent applier"}
    try:
        from browser_use import Agent
        from browser_use.browser.profile import BrowserProfile
        from browser_use.llm import ChatOpenAI
    except Exception as exc:  # noqa: BLE001
        return {"error": f"browser-use not installed: {exc}"}

    task = _TASK_TEMPLATE.format(
        url=job_url, candidate=json.dumps(candidate, ensure_ascii=False)
    )
    files = [cv_path] if cv_path and Path(cv_path).exists() else []
    agent = Agent(
        task=task,
        llm=ChatOpenAI(model=settings.agent_applier_model),
        browser_profile=BrowserProfile(headless=True),
        available_file_paths=files,
        use_vision=True,
    )
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
    return {
        "summary": summary,
        "final_url": final_url,
        "screenshot_path": saved_shot,
        "error": None,
    }
