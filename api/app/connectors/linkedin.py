"""LinkedIn discovery via the public guest jobs endpoint.

DISCOVERY ONLY. Per CLAUDE.md's hard rules, nothing here applies or submits to
LinkedIn — it only reads public job cards to surface postings. Access is paced
(small delays, few pages, realistic UA) to stay low-velocity and resilient to
rate limits; failures degrade to whatever was fetched.

query   -> keywords (e.g. "backend engineer")
filters -> location (default "Saudi Arabia"), pages (default 2)
"""
from __future__ import annotations

import asyncio
import random
import re
from typing import Any

import httpx

from app.connectors.base import Connector, strip_html

GUEST_API = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
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


class LinkedInConnector(Connector):
    name = "linkedin"

    async def fetch(self, query: str | None, filters: dict[str, Any]) -> list[dict]:
        keywords = (query or filters.get("keywords") or "").strip()
        if not keywords:
            return []
        location = filters.get("location") or "Saudi Arabia"
        pages = min(int(filters.get("pages", 2)), 5)

        jobs: list[dict] = []
        seen: set[str] = set()
        async with httpx.AsyncClient(
            timeout=20, headers={"User-Agent": _UA, "Accept": "text/html"}
        ) as client:
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
                    html = resp.text
                except Exception:  # noqa: BLE001
                    break
                found = self._parse(html, seen)
                jobs.extend(found)
                if not found:
                    break
                # human-paced: jittered delay between pages
                await asyncio.sleep(random.uniform(1.5, 3.5))
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
            out.append(
                {
                    "source": self.name,
                    "external_id": f"linkedin:{ext.group(1) if ext else url}",
                    "title": strip_html(title.group(1)) if title else "",
                    "company": strip_html(company.group(1)) if company else None,
                    "location": strip_html(loc.group(1)) if loc else None,
                    "url": url,
                    "description": None,
                    "posted_at": None,
                    "raw": {"via": "guest-api"},
                }
            )
        return out
