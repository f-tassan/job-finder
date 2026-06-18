"""Generic company-website / careers-page connector.

Fetches a careers page URL and extracts anchor links that look like individual
job postings (by URL pattern or anchor text). Best-effort — company sites have
no standard API — but works well for static careers pages and embedded ATS
widgets (Greenhouse/Lever/Ashby/Workday links).

query/filters.url -> the careers page URL
filters.company   -> optional company name override
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.connectors.base import Connector

_UA = "Mozilla/5.0 (compatible; job-finder/1.0; +discovery)"
_ANCHOR_RE = re.compile(r'<a\b[^>]*href="([^"#]+)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

# URL substrings that typically denote an individual posting.
_JOB_HINTS = (
    "/job/",
    "/jobs/",
    "/careers/",
    "/career/",
    "/position",
    "/vacancy",
    "/vacancies/",
    "/opening",
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "myworkdayjobs.com",
    "/viewjob",
)


class CompanySiteConnector(Connector):
    name = "company_site"

    async def fetch(self, query: str | None, filters: dict[str, Any]) -> list[dict]:
        url = (filters.get("url") or query or "").strip()
        if not url:
            return []
        if not url.startswith("http"):
            url = "https://" + url
        company = filters.get("company") or urlparse(url).netloc

        async with httpx.AsyncClient(
            timeout=25, headers={"User-Agent": _UA}, follow_redirects=True
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text

        jobs: list[dict] = []
        seen: set[str] = set()
        for href, raw_text in _ANCHOR_RE.findall(html):
            low = href.lower()
            if not any(h in low for h in _JOB_HINTS):
                continue
            absolute = urljoin(url, href)
            if absolute in seen:
                continue
            title = _WS_RE.sub(" ", _TAG_RE.sub(" ", raw_text)).strip()
            if not title or len(title) < 3 or len(title) > 160:
                continue
            seen.add(absolute)
            jobs.append(
                {
                    "source": self.name,
                    "external_id": absolute[:500],
                    "title": title,
                    "company": company,
                    "location": None,
                    "url": absolute,
                    "description": None,
                    "posted_at": None,
                    "raw": {"careers_url": url},
                }
            )
        return jobs
