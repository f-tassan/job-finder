"""Saudi national portals (Jadarat / Qiwa / Taqat).

These portals have no documented public job API — access requires authenticated
sessions / scraping that's out of scope here. This connector is therefore a
drop-in placeholder that, when a saved search provides a JSON `feed_url` (e.g. an
exported/proxied feed), fetches and normalizes it; otherwise it returns nothing.
Real portal integration (likely via the Playwright browser-worker) lands later.
"""
from __future__ import annotations

from typing import Any

import httpx

from app.connectors.base import Connector, strip_html


class GovPortalsConnector(Connector):
    name = "gov_portals"

    async def fetch(self, query: str | None, filters: dict[str, Any]) -> list[dict]:
        feed_url = filters.get("feed_url")
        if not feed_url:
            return []
        portal = filters.get("portal") or "gov"
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(feed_url)
            resp.raise_for_status()
            items = resp.json()
        if isinstance(items, dict):
            items = items.get("jobs") or items.get("data") or []
        jobs: list[dict] = []
        for it in items:
            ext = str(it.get("id") or it.get("url") or it.get("title"))
            jobs.append(
                {
                    "source": self.name,
                    "external_id": f"{portal}:{ext}",
                    "title": it.get("title", ""),
                    "company": it.get("company") or it.get("employer"),
                    "location": it.get("location") or it.get("city"),
                    "url": it.get("url", ""),
                    "description": strip_html(it.get("description")),
                    "posted_at": None,
                    "raw": {"portal": portal},
                }
            )
        return jobs
