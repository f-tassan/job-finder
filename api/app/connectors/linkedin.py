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

Company mode (for surfacing a specific employer's postings):
filters.companies -> list of brand keywords (e.g. ["Maaden", "NEOM", "tarshid"]).
           Each is searched separately and only job cards whose employer subtitle
           actually matches the brand are kept (LinkedIn keyword search alone is
           too loose to trust as a company filter). Set company_match=false to
           keep everything a brand search returns.
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from typing import Any

import httpx

from app.config import settings
from app.connectors.base import Connector, strip_html

logger = logging.getLogger(__name__)

# Rotate a small pool of realistic desktop UAs to look less automated.
_UA_POOL = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like "
    "Gecko) Chrome/125.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 "
    "Firefox/126.0",
]


def _make_client(proxy: str | None) -> httpx.AsyncClient:
    kw: dict[str, Any] = {"timeout": 20, "follow_redirects": True}
    if proxy:
        try:
            return httpx.AsyncClient(proxy=proxy, **kw)        # httpx >= 0.28
        except TypeError:
            return httpx.AsyncClient(proxies=proxy, **kw)      # httpx < 0.28
    return httpx.AsyncClient(**kw)


class _Pacer:
    """Low-velocity HTTP for LinkedIn: rotates proxies + UAs, enforces a delay
    between every request, backs off on 429/999/403, and caps total requests so
    one run can't hammer LinkedIn into blocking us."""

    def __init__(self) -> None:
        self.proxies: list[str | None] = [
            p.strip() for p in (settings.linkedin_proxies or "").split(",") if p.strip()
        ] or [None]
        self._clients: dict[str | None, httpx.AsyncClient] = {}
        self._pi = 0
        self.count = 0
        self.blocked = False
        self._last = 0.0

    def _client(self, proxy: str | None) -> httpx.AsyncClient:
        if proxy not in self._clients:
            self._clients[proxy] = _make_client(proxy)
        return self._clients[proxy]

    async def get(self, url: str, params: dict | None = None) -> httpx.Response | None:
        if self.blocked or self.count >= settings.linkedin_max_requests:
            return None
        for attempt in range(settings.linkedin_max_retries + 1):
            # pace: never fire two requests closer than the configured window
            wait = random.uniform(settings.linkedin_min_delay, settings.linkedin_max_delay)
            gap = time.monotonic() - self._last
            if gap < wait:
                await asyncio.sleep(wait - gap)
            proxy = self.proxies[self._pi % len(self.proxies)]
            headers = {"User-Agent": random.choice(_UA_POOL), "Accept": "text/html",
                       "Accept-Language": "en-US,en;q=0.9"}
            try:
                resp = await self._client(proxy).get(url, params=params, headers=headers)
                self.count += 1
                self._last = time.monotonic()
            except Exception:  # noqa: BLE001 - network/proxy error -> rotate + retry
                self._pi += 1
                await asyncio.sleep(random.uniform(2, 5))
                continue
            if resp.status_code == 200:
                return resp
            if resp.status_code in (429, 999, 403):  # rate-limited / blocked
                self._pi += 1  # rotate proxy
                backoff = settings.linkedin_backoff_base * (attempt + 1) + random.uniform(0, 5)
                logger.warning("LinkedIn %s on %s; backing off %.0fs (attempt %d)",
                               resp.status_code, url.split("/")[-1], backoff, attempt + 1)
                await asyncio.sleep(backoff)
                continue
            return resp  # other non-200: let caller decide (usually stop)
        # exhausted retries on this request — if no proxies to rotate, stop early
        if len(self.proxies) == 1:
            self.blocked = True
        return None

    async def aclose(self) -> None:
        for c in self._clients.values():
            try:
                await c.aclose()
            except Exception:  # noqa: BLE001
                pass


def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _company_matches(brand: str, company_name: str | None) -> bool:
    """True if a job card's employer subtitle plausibly is this brand."""
    b, cn = _norm(brand), _norm(company_name)
    if not b or not cn:
        return False
    return b in cn or cn in b

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
        # Company mode: a list of either brand strings or
        # {"q": keyword, "match": [tokens], "name": display}.
        companies = filters.get("companies") or []
        company_match = filters.get("company_match", True)
        location = filters.get("location") or "Saudi Arabia"
        pages = min(int(filters.get("pages", 3)), 5)
        fetch_desc = filters.get("fetch_descriptions", True)
        max_desc = min(int(filters.get("max_descriptions", 40)), 80)

        searches: list[tuple[str, list[str], str | None]] = []  # (query, match, display)
        if companies:
            for c in companies:
                if isinstance(c, str):
                    if c.strip():
                        searches.append((c.strip(), [c.strip()], None))
                elif isinstance(c, dict) and (c.get("q") or "").strip():
                    q = c["q"].strip()
                    searches.append((q, c.get("match") or [q], c.get("name")))
        else:
            raw = (query or filters.get("keywords") or "").strip()
            if not raw:
                return []
            for k in (raw.split(",") if "," in raw else [raw]):
                if k.strip():
                    searches.append((k.strip(), [], None))

        jobs: list[dict] = []
        seen: set[str] = set()
        pacer = _Pacer()
        try:
            for keywords, match_tokens, display in searches:
                if pacer.blocked:
                    break
                for page in range(pages):
                    params = {
                        "keywords": keywords,
                        "location": location,
                        "start": page * 25,
                    }
                    resp = await pacer.get(GUEST_API, params=params)
                    if resp is None or resp.status_code != 200:
                        break
                    found = self._parse(resp.text, seen)
                    raw_count = len(found)
                    # In company mode, keep only cards whose employer matches; relabel
                    # to the canonical display name when provided.
                    if companies and company_match and match_tokens:
                        kept = []
                        for j in found:
                            if any(_company_matches(t, j.get("company")) for t in match_tokens):
                                if display:
                                    j["company"] = display
                                kept.append(j)
                        found = kept
                    jobs.extend(found)
                    if not raw_count:  # no more results on this page -> next brand
                        break

            # Enrich with real descriptions so relevance has substance.
            if fetch_desc:
                for job in jobs[:max_desc]:
                    job_id = job["raw"].get("job_id")
                    if not job_id:
                        continue
                    r = await pacer.get(POSTING_API.format(job_id=job_id))
                    if r is not None and r.status_code == 200:
                        m = _DESC_RE.search(r.text)
                        if m:
                            job["description"] = strip_html(m.group(1))
        finally:
            await pacer.aclose()
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

            def _clean(m):
                if not m:
                    return None
                return re.sub(r"\s+", " ", strip_html(m.group(1))).strip() or None

            title_s = _clean(title)
            company_s = _clean(company)
            # Degraded/throttled HTML yields cards with no real title or a company
            # that's actually the location — skip those rather than store junk.
            if not title_s or len(title_s) > 160:
                continue
            out.append(
                {
                    "source": self.name,
                    "external_id": f"linkedin:{job_id or url}",
                    "title": title_s,
                    "company": company_s,
                    "location": _clean(loc),
                    "url": url,
                    "description": None,
                    "posted_at": None,
                    "raw": {"via": "guest-api", "job_id": job_id},
                }
            )
        return out
