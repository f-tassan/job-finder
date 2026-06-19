"""Browser-worker task: render careers pages with Playwright and extract job
links. Used by the company_site connector for JavaScript career portals
(Workday/Taleo/SuccessFactors/etc.) that a static fetch can't read.

For each careers URL it loads the page, waits for JS + scrolls, extracts
job-like links, and — if the page mostly links out to an external ATS — follows
one hop into that ATS and extracts there too. Returns normalized job dicts (same
shape as the connectors).

Runs on the `browser` queue. Playwright is imported lazily so the default worker
can import this module for task registration without needing it.
"""
from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import urljoin, urlparse

from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# Oracle Recruiting Cloud (ORC) candidate-experience site URL. Many KSA companies
# use ORC; its public JSON API returns ALL postings with real locations, which is
# far more reliable than scraping the JS-rendered page.
_ORC_CX_RE = re.compile(
    r"https?://([^/]+)/hcmUI/CandidateExperience/(\w+)/sites/(CX_[\w]+)", re.I
)

# Substrings marking an individual posting / job list.
_HINTS = (
    "/job/",
    "/jobs/",
    "/careers/",
    "/career/",
    "/position",
    "/vacanc",
    "/opening",
    "/viewjob",
    "requisition",
    "/jobdetail",
)
# Known ATS hosts to follow one hop into.
_ATS = (
    "myworkdayjobs.com",
    "myworkdaysite.com",
    "taleo.net",
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "smartrecruiters.com",
    "workable.com",
    "bamboohr.com",
    "successfactors",
    "oraclecloud.com",
    "icims.com",
)

_EXTRACT_JS = """
() => {
  const out = [];
  const push = (h, t) => { if (h) out.push({h, t: (t||'').trim().replace(/\\s+/g,' ').slice(0,160)}); };
  document.querySelectorAll('a[href]').forEach(a => push(a.href, a.innerText));
  // Workday renders titles in a non-anchor element sometimes
  document.querySelectorAll('[data-automation-id="jobTitle"]').forEach(e => {
    const a = e.closest('a') || e.querySelector('a');
    push(a ? a.href : (e.getAttribute && e.getAttribute('href')) || '', e.innerText);
  });
  return out;
}
"""


# Generic nav/landing link text that is NOT a job posting.
_STOP_TEXT = {
    "careers", "career", "jobs", "job", "apply", "apply now", "view all",
    "view all jobs", "all jobs", "view jobs", "search jobs", "browse jobs",
    "openings", "current openings", "open positions", "open roles", "vacancies",
    "vacancy", "job openings", "join us", "join our team", "opportunities",
    "explore careers", "careers faq", "faq", "life at nsg", "our people",
    "culture", "benefits", "meet the team", "why join us", "work with us",
    "join", "explore", "see all", "sitemap", "site map", "talent network",
    "join the talent network", "learning & development",
    "learning and development", "contact us", "read more", "learn more",
    "students", "graduates", "early talent", "early careers",
    "social recruitment", "intern recruitment", "campus recruitment",
    "banco de talentos", "talent pool", "talent community", "register",
    "sign in", "log in", "internships", "graduate program",
}
_STOP_SUBSTR = ("life at ", "why ", "meet the team", "faq", "our culture",
                "about us", "benefits", "explore ", "view all", "talent network",
                "sitemap", "learning & development", "learning and development",
                "careers at ", "talent community", "banco de talentos")
# Title endings that mark a section/landing link, not a posting
# (e.g. "WELL COMPLETIONS CAREERS", "Social Recruitment").
_STOP_SUFFIX = (" careers", " career", " recruitment", " openings", " vacancies")
# Listing-root paths that aren't a specific posting.
_LISTING_ROOTS = {"/careers", "/careers/", "/jobs", "/jobs/", "/career",
                  "/career/", "/en/careers", "/en/careers/", "/vacancies",
                  "/vacancies/", "/openings", "/openings/"}


def _is_job(href: str, text: str) -> bool:
    h = (href or "").lower()
    t = (text or "").strip().lower()
    if not any(k in h for k in _HINTS):
        return False
    if len(t) < 6 or t in _STOP_TEXT or any(s in t for s in _STOP_SUBSTR):
        return False
    if t.endswith(_STOP_SUFFIX):
        return False
    # Must be a SPECIFIC posting, not the careers/jobs landing page itself.
    from urllib.parse import urlparse

    path = urlparse(h).path.rstrip("/")
    if (path + "/") in _LISTING_ROOTS or path in _LISTING_ROOTS or not path:
        return False
    return True


def _ats_link(anchors: list[dict], base: str) -> str | None:
    for a in anchors:
        h = (a.get("h") or "").lower()
        if any(d in h for d in _ATS):
            return a["h"]
    # also common "view openings / current openings / apply" links
    for a in anchors:
        t = (a.get("t") or "").lower()
        if any(k in t for k in ("opening", "vacanc", "view jobs", "all jobs", "search jobs")):
            return urljoin(base, a["h"])
    return None


# Scoring hints for finding the real careers/jobs link from a homepage when the
# configured URL is wrong (404) or redirects to the homepage.
_CAREERS_KW = (
    ("careers", 6), ("career", 5), ("/jobs", 5), ("/job-", 4), ("vacanc", 4),
    ("recruit", 3), ("join-us", 3), ("join us", 3), ("join our", 3),
    ("work-with-us", 2), ("work with us", 2), ("work-at", 2), ("opportunit", 2),
    ("life-at", 1),
)
# Don't chase these off-site / non-careers destinations.
_CAREERS_SKIP = (
    "linkedin.com", "facebook.com", "twitter.com", "x.com", "instagram.com",
    "youtube.com", "mailto:", "tel:", "javascript:", ".pdf",
)


def _discover_careers_link(anchors: list[dict], root: str) -> str | None:
    """Pick the most careers-like link from a homepage's anchors."""
    best: str | None = None
    best_score = 0
    root_norm = root.rstrip("/")
    for a in anchors:
        href = (a.get("h") or "").strip()
        if not href:
            continue
        low_h = href.lower()
        text = (a.get("t") or "").strip().lower()
        if any(s in low_h for s in _CAREERS_SKIP):
            continue
        score = 0
        for kw, sc in _CAREERS_KW:
            if kw in low_h:
                score += sc
            if kw in text:
                score += sc
        if score <= best_score:
            continue
        absu = urljoin(root + "/", href.split("#")[0])
        if not urlparse(absu).scheme.startswith("http"):
            continue
        if absu.rstrip("/") == root_norm:  # the homepage itself
            continue
        best, best_score = absu, score
    return best


async def _load(page, url: str) -> int | None:
    """Navigate, wait for JS, scroll to trigger lazy lists. Returns HTTP status
    (or None on failure)."""
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception:  # noqa: BLE001
        return None
    await page.wait_for_timeout(2500)
    for _ in range(3):
        try:
            await page.mouse.wheel(0, 4000)
        except Exception:  # noqa: BLE001
            break
        await page.wait_for_timeout(700)
    return resp.status if resp else 200


async def _extract_from(page, url, seen, company) -> list[dict]:
    jobs: list[dict] = []
    try:
        anchors = await page.evaluate(_EXTRACT_JS)
    except Exception:  # noqa: BLE001
        return jobs
    for a in anchors:
        href = a.get("h") or ""
        text = a.get("t") or ""
        if not _is_job(href, text):
            continue
        absolute = urljoin(url, href.split("#")[0])
        if absolute in seen:
            continue
        if not text or len(text) < 3 or len(text) > 160:
            continue
        seen.add(absolute)
        jobs.append(
            {
                "source": "company_site",
                "external_id": absolute[:500],
                "title": text,
                "company": company,
                "location": None,
                "url": absolute,
                "description": None,
                "posted_at": None,
                "raw": {"careers_url": url, "rendered": True},
            }
        )
    return jobs


def _find_orc_cx(anchors: list[dict]) -> str | None:
    """Find an Oracle Recruiting Cloud candidate-experience URL among anchors."""
    for a in anchors:
        h = a.get("h") or ""
        if _ORC_CX_RE.search(h):
            return h
    return None


async def _fetch_orc(cx_url: str, company: str) -> list[dict]:
    """Fetch all postings from an ORC site via its public JSON API."""
    import httpx

    m = _ORC_CX_RE.search(cx_url)
    if not m:
        return []
    host, lang, site = m.group(1), m.group(2), m.group(3)
    api = (
        f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
        "?onlyData=true"
        "&expand=requisitionList.secondaryLocations,flexFieldsFacet.values"
        f"&finder=findReqs;siteNumber={site},"
        "facetsList=LOCATIONS;WORK_LOCATIONS;TITLES;CATEGORIES,"
        "limit=200,sortBy=POSTING_DATES_DESC"
    )
    try:
        async with httpx.AsyncClient(
            timeout=25, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        ) as client:
            r = await client.get(api)
        if r.status_code != 200:
            return []
        items = r.json().get("items", [])
        reqs = items[0].get("requisitionList", []) if items else []
    except Exception:  # noqa: BLE001
        return []
    out: list[dict] = []
    for j in reqs:
        jid, title = j.get("Id"), j.get("Title")
        if not jid or not title:
            continue
        out.append(
            {
                "source": "company_site",
                "external_id": f"orc:{host}:{jid}"[:500],
                "title": title.strip(),
                "company": company,
                "location": j.get("PrimaryLocation"),
                "url": (
                    f"https://{host}/hcmUI/CandidateExperience/{lang}/sites/"
                    f"{site}/job/{jid}"
                ),
                "description": (j.get("ShortDescriptionStr") or "")[:2000] or None,
                "posted_at": None,
                "raw": {"ats": "oracle_recruiting", "site": site},
            }
        )
    return out


async def _render(urls: list[str], cap: int) -> list[dict]:
    from playwright.async_api import async_playwright

    jobs: list[dict] = []
    seen: set[str] = set()
    urls = [u if u.startswith("http") else "https://" + u for u in urls][:cap]
    sem = asyncio.Semaphore(3)

    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        ctx = await browser.new_context(
            ignore_https_errors=True,  # some KSA sites have stale/mismatched certs
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like "
                "Gecko) Chrome/124.0 Safari/537.36"
            ),
        )

        async def _anchors(page) -> list[dict]:
            try:
                return await page.evaluate(_EXTRACT_JS)
            except Exception:  # noqa: BLE001
                return []

        async def one(url: str):
            company = urlparse(url).netloc
            page = await ctx.new_page()
            tried: set[str] = set()
            try:
                status = await _load(page, url)
                tried.add(url.rstrip("/"))
                found: list[dict] = []
                # A 404/redirect-home/login still renders a page; only extract when
                # the URL actually resolved to a real page.
                if status and status < 400:
                    anchors = await _anchors(page)
                    # ORC: if the page links to an Oracle Recruiting site, its JSON
                    # API gives every posting (with locations) — prefer it.
                    orc = _find_orc_cx(anchors)
                    if orc:
                        found = await _fetch_orc(orc, company)
                        if found:
                            return found
                    found = await _extract_from(page, page.url, seen, company)

                # Self-heal: the configured /careers path is often wrong. Load the
                # site root and follow its real Careers/Jobs link.
                if len(found) < 2:
                    parts = urlparse(url)
                    root = f"{parts.scheme}://{parts.netloc}"
                    if await _load(page, root) is not None:
                        anchors = await _anchors(page)
                        careers = _discover_careers_link(anchors, root)
                        if careers and careers.rstrip("/") not in tried:
                            tried.add(careers.rstrip("/"))
                            if await _load(page, careers) is not None:
                                anchors = await _anchors(page)
                                orc = _find_orc_cx(anchors)
                                if orc:
                                    found = await _fetch_orc(orc, company)
                                    if found:
                                        return found
                                found += await _extract_from(
                                    page, page.url, seen, company
                                )

                # Follow one hop into an embedded/linked ATS (Workday, Oracle
                # Cloud, Taleo, SuccessFactors, Greenhouse, …).
                if len(found) < 2:
                    anchors = await _anchors(page)
                    orc = _find_orc_cx(anchors)
                    if orc:
                        api_jobs = await _fetch_orc(orc, company)
                        if api_jobs:
                            return api_jobs
                    ats = _ats_link(anchors, page.url)
                    if ats and ats.rstrip("/") not in tried:
                        tried.add(ats.rstrip("/"))
                        if await _load(page, ats) is not None:
                            found += await _extract_from(page, page.url, seen, company)
                return found
            except Exception:  # noqa: BLE001
                return []
            finally:
                await page.close()

        async def guarded(u):
            async with sem:
                return await one(u)

        results = await asyncio.gather(*[guarded(u) for u in urls])
        # Cap per company so one large (often foreign) employer can't flood the
        # catalog; relevance ranking handles the rest.
        per_company_cap = 60
        counts: dict[str, int] = {}
        for r in results:
            for job in r:
                c = job.get("company") or ""
                if counts.get(c, 0) >= per_company_cap:
                    continue
                counts[c] = counts.get(c, 0) + 1
                jobs.append(job)
        await browser.close()
    return jobs


@celery_app.task(name="render.careers")
def render_careers(urls: list[str], cap: int = 80) -> list[dict]:
    return asyncio.run(_render(urls, cap))
