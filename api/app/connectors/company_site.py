"""Generic company-website / careers-page connector.

Fetches one or many careers-page URLs and extracts anchor links that look like
individual job postings (by URL pattern or anchor text). Best-effort — company
sites have no standard API — but works well for static careers pages and embedded
ATS widgets (Greenhouse/Lever/Ashby/Workday links).

filters.urls    -> list of careers-page URLs (preferred; for a long company list)
query/filters.url -> a single careers-page URL
filters.company -> optional company-name override (single-URL only)
"""
from __future__ import annotations

import asyncio
import random
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.connectors.base import Connector

_UA = "Mozilla/5.0 (compatible; job-finder/1.0; +discovery)"
_ANCHOR_RE = re.compile(
    r'<a\b[^>]*href="([^"#]+)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL
)
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
        # Accept a list (filters.urls) or a single URL (filters.url / query).
        raw_urls = filters.get("urls")
        if not raw_urls:
            single = (filters.get("url") or query or "").strip()
            raw_urls = [single] if single else []
        urls = [u.strip() for u in raw_urls if u and u.strip()]
        if not urls:
            return []

        jobs: list[dict] = []
        seen: set[str] = set()
        async with httpx.AsyncClient(
            timeout=25, headers={"User-Agent": _UA}, follow_redirects=True
        ) as client:
            for i, url in enumerate(urls):
                if not url.startswith("http"):
                    url = "https://" + url
                company = filters.get("company") if len(urls) == 1 else None
                company = company or urlparse(url).netloc
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    html = resp.text
                except Exception:  # noqa: BLE001 - skip a bad site, keep going
                    continue
                jobs.extend(self._extract(html, url, company, seen))
                if i < len(urls) - 1:
                    await asyncio.sleep(random.uniform(0.5, 1.5))  # be polite
        return jobs

    def _extract(self, html: str, base: str, company: str, seen: set[str]) -> list[dict]:
        out: list[dict] = []
        for href, raw_text in _ANCHOR_RE.findall(html):
            if not any(h in href.lower() for h in _JOB_HINTS):
                continue
            absolute = urljoin(base, href)
            if absolute in seen:
                continue
            title = _WS_RE.sub(" ", _TAG_RE.sub(" ", raw_text)).strip()
            if not title or len(title) < 3 or len(title) > 160:
                continue
            seen.add(absolute)
            out.append(
                {
                    "source": self.name,
                    "external_id": absolute[:500],
                    "title": title,
                    "company": company,
                    "location": None,
                    "url": absolute,
                    "description": None,
                    "posted_at": None,
                    "raw": {"careers_url": base},
                }
            )
        return out
