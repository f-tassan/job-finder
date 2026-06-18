"""LinkedIn discovery via the public guest jobs endpoint.

DISCOVERY ONLY. Per CLAUDE.md's hard rules, nothing here applies or submits to
LinkedIn — it only reads public job cards to surface postings. Access is paced
(small delays, few pages, realistic UA) to stay low-velocity and resilient to
rate limits; failures degrade to whatever was fetched.

This is the broadest source (searches across companies). To make matching
meaningful we also fetch each posting's full description from the public
jobPosting endpoint (bounded + paced).

query   -> keywords, comma-separated for multiple (e.g. "data engineer, ml engineer")
filters -> location (default "Saudi Arabia"), pages (default 3),
           fetch_descriptions (default true), max_descriptions (default 40)
"""
from __future__ import annotations

import asyncio
import random
import re
from typing import Any

import httpx

from app.connectors.base import Connector, strip_html

GUEST_API = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
POSTING_API = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

_CARD_RE = re.compile(r"<li>.*?</li>", re.DOTALL)
_LINK_RE = re.compile(r'href="(https://[^"?]*?/jobs/view/[^"?]+)')
_TITLE_RE = re.compile(r'base-search-card__title">(.*?)</h3>', re.DOTALL)
_COMPANY_RE = re.compile(r'base-search-card__subtitle">.*?>(.*?)</a>', re.DOTALL)
_LOC_RE = re.compile(r'job-search-card__location">(.*?)</span>', re.DOTALL)
_ID_RE = re.compile(r"-(\d+)(?:\?|$)")
_DESC_RE = re.compile(
    r'show-more-less-html__markup[^"]*">(.*?)</div>', re.DOTALL
)


class LinkedInConnector(Connector):
    name = "linkedin"

    async def fetch(self, query: str | None, filters: dict[str, Any]) -> list[dict]:
        raw = (query or filters.get("keywords") or "").strip()
        if not raw:
            return []
        keyword_list = [k.strip() for k in raw.split(",") if k.strip()] or [raw]
        location = filters.get("location") or "Saudi Arabia"
        pages = min(int(filters.get("pages", 3)), 5)
        fetch_desc = filters.get("fetch_descriptions", True)
        max_desc = min(int(filters.get("max_descriptions", 40)), 80)

        jobs: list[dict] = []
        seen: set[str] = set()
        async with httpx.AsyncClient(
            timeout=20, headers={"User-Agent": _UA, "Accept": "text/html"}
        ) as client:
            for keywords in keyword_list:
                for page in range(pages):
                    params = {
                        "keywords": keywords,
                        "location": location,
                        "start": page * 25,
                    }
                    try:
                        resp = await client.get(GUEST_API, params=params)
                        if resp.status_code != 200:
                            break
                        found = self._parse(resp.text, seen)
                    except Exception:  # noqa: BLE001
                        break
                    jobs.extend(found)
                    if not found:
                        break
                    await asyncio.sleep(random.uniform(1.2, 2.8))  # human-paced

            # Enrich with real descriptions so relevance has substance.
            if fetch_desc:
                for job in jobs[:max_desc]:
                    job_id = job["raw"].get("job_id")
                    if not job_id:
                        continue
                    try:
                        r = await client.get(POSTING_API.format(job_id=job_id))
                        if r.status_code == 200:
                            m = _DESC_RE.search(r.text)
                            if m:
                                job["description"] = strip_html(m.group(1))
                    except Exception:  # noqa: BLE001
                        pass
                    await asyncio.sleep(random.uniform(0.4, 1.1))
        return jobs

    def _parse(self, html: str, seen: set[str]) -> list[dict]:
        out: list[dict] = []
        for card in _CARD_RE.findall(html):
            link = _LINK_RE.search(card)
            if not link:
                continue
            url = link.group(1)
            if url in seen:
                continue
            seen.add(url)
            title = _TITLE_RE.search(card)
            company = _COMPANY_RE.search(card)
            loc = _LOC_RE.search(card)
            ext = _ID_RE.search(url)
            job_id = ext.group(1) if ext else None
            out.append(
                {
                    "source": self.name,
                    "external_id": f"linkedin:{job_id or url}",
                    "title": strip_html(title.group(1)) if title else "",
                    "company": strip_html(company.group(1)) if company else None,
                    "location": strip_html(loc.group(1)) if loc else None,
                    "url": url,
                    "description": None,
                    "posted_at": None,
                    "raw": {"via": "guest-api", "job_id": job_id},
                }
            )
        return out
