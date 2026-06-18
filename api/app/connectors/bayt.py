"""Bayt.com discovery (Gulf/KSA job board).

DISCOVERY ONLY and human-paced (realistic UA, few pages, jittered delays) — the
human applies/submits. Reads Bayt's public search results and extracts posting
links + titles; best-effort (returns what it parses, [] on failure).

query   -> keywords (e.g. "accountant")
filters -> country (default "saudi-arabia"), pages (default 1)
"""
from __future__ import annotations

import asyncio
import random
import re
from typing import Any
from urllib.parse import urljoin

import httpx

from app.connectors.base import Connector

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)
_BASE = "https://www.bayt.com"
# Bayt job detail links look like /en/<country>/jobs/<slug>-<id>/
_JOB_LINK_RE = re.compile(
    r'<a[^>]+href="(/[a-z]{2}/[^"]*/jobs/[^"]*-\d+/)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


class BaytConnector(Connector):
    name = "bayt"

    async def fetch(self, query: str | None, filters: dict[str, Any]) -> list[dict]:
        keywords = (query or filters.get("keywords") or "").strip()
        if not keywords:
            return []
        country = filters.get("country") or "saudi-arabia"
        pages = min(int(filters.get("pages", 1)), 3)

        jobs: list[dict] = []
        seen: set[str] = set()
        async with httpx.AsyncClient(
            timeout=20, headers={"User-Agent": _UA, "Accept": "text/html"},
            follow_redirects=True,
        ) as client:
            for page in range(1, pages + 1):
                url = f"{_BASE}/en/{country}/jobs/"
                params = {"q": keywords, "page": page}
                try:
                    resp = await client.get(url, params=params)
                    if resp.status_code != 200:
                        break
                    html = resp.text
                except Exception:  # noqa: BLE001
                    break
                found = self._parse(html, country, seen)
                jobs.extend(found)
                if not found:
                    break
                await asyncio.sleep(random.uniform(1.5, 3.5))  # human-paced
        return jobs

    def _parse(self, html: str, country: str, seen: set[str]) -> list[dict]:
        out: list[dict] = []
        for href, raw_text in _JOB_LINK_RE.findall(html):
            absolute = urljoin(_BASE, href)
            if absolute in seen:
                continue
            title = _WS_RE.sub(" ", _TAG_RE.sub(" ", raw_text)).strip()
            if not title or len(title) < 3:
                continue
            seen.add(absolute)
            out.append(
                {
                    "source": self.name,
                    "external_id": absolute,
                    "title": title[:300],
                    "company": None,
                    "location": country.replace("-", " ").title(),
                    "url": absolute,
                    "description": None,
                    "posted_at": None,
                    "raw": {"country": country},
                }
            )
        return out
