"""Demo: browser-use agent auto-fills a real, no-login company application form.

Drives an LLM browser agent to (1) search a public ATS board, (2) pick a role
relevant to the candidate, (3) open its application form, (4) fill every field it
can ground in the candidate's answer-bank data, (5) upload the candidate's CV —
then STOP before the final Submit (CLAUDE.md: the human submits). Leaves
salary/"why"/cover-letter and anything not in the data blank.

Run inside the browser-worker container (has Playwright + chromium + OPENAI key):
    docker compose exec browser-worker python scripts/demo_agent_apply.py
"""
from __future__ import annotations

import asyncio
import json
import os

from browser_use import Agent
from browser_use.browser.profile import BrowserProfile
from browser_use.llm import ChatOpenAI

# --- Real candidate data, pulled from the app's answer bank (never invented) ---
CANDIDATE = {
    "first_name": "Faisal",
    "last_name": "Altassan",
    "full_name": "Faisal Altassan",
    "email": "faisal.f.i.t@gmail.com",
    "phone": "0594797373",
    "city": "Riyadh",
    "country": "Saudi Arabia",
    "nationality": "Saudi",
    "years_of_experience": "7",
    "education": "Bachelors",
    "notice_period": "2 months",
    "linkedin": "",  # not in answer bank -> leave blank
}

CV_PATH = (
    "/data/files/ab33b66a-f6dd-4309-9c91-f215910a3c63/cvs/"
    "fa2608ce-384b-43be-8a55-87142ac9b7a7.pdf"
)
BOARD_URL = "https://job-boards.greenhouse.io/gitlab"
SHOT_PATH = "/data/files/ab33b66a-f6dd-4309-9c91-f215910a3c63/prefill/demo_agent.png"

TASK = f"""
You are pre-filling a job application for a candidate. Work on this public job
board (no login/account needed): {BOARD_URL}

STEPS:
1. Use the board's search to find an open SOFTWARE ENGINEERING or AI ENGINEERING
   role (e.g. "Backend Engineer", "AI Engineer"). Pick ONE that fits a candidate
   with 7 years of software experience.
2. Open that job and click "Apply" to reach the application form.
3. Fill the form using ONLY this candidate data (do not invent anything):
   {json.dumps(CANDIDATE, ensure_ascii=False)}
4. Upload the candidate's resume into the Resume/CV file field. The resume file is
   available to you; use the upload-file action with the provided file path.
5. For any field you cannot truthfully answer from the candidate data — especially
   expected/current SALARY, "why do you want to work here", cover letter, or
   demographic/voluntary questions — LEAVE IT BLANK.

HARD RULE: Do NOT click "Submit", "Submit Application", or any final submit
button. Stop once the form is filled and the resume is attached.

When you stop, report: the exact job title and URL you chose, the list of fields
you filled, and the list of fields you left blank and why.
"""


async def main() -> None:
    os.makedirs(os.path.dirname(SHOT_PATH), exist_ok=True)
    llm = ChatOpenAI(model="gpt-4.1")
    profile = BrowserProfile(headless=True)
    agent = Agent(
        task=TASK,
        llm=llm,
        browser_profile=profile,
        available_file_paths=[CV_PATH],
        use_vision=True,
    )
    history = await agent.run(max_steps=40)

    # Capture proof of the filled-but-unsubmitted form. browser-use resets its
    # session after run(), so use the last per-step screenshot from history.
    try:
        paths = [p for p in (history.screenshot_paths() or []) if p]
        if paths and os.path.exists(paths[-1]):
            with open(paths[-1], "rb") as src, open(SHOT_PATH, "wb") as dst:
                dst.write(src.read())
            print(f"\n[screenshot] saved -> {SHOT_PATH}")
        else:
            print("\n[screenshot] no per-step screenshot found")
    except Exception as exc:  # noqa: BLE001
        print(f"[screenshot] failed: {exc}")

    print("\n===== FINAL URL =====")
    try:
        urls = [u for u in (history.urls() or []) if u]
        print(urls[-1] if urls else "")
    except Exception:  # noqa: BLE001
        pass
    print("\n===== AGENT RESULT =====")
    try:
        print(history.final_result())
    except Exception:  # noqa: BLE001
        print(history)


if __name__ == "__main__":
    asyncio.run(main())
