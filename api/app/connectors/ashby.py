"""Ashby public job board API (api.ashbyhq.com/posting-api/job-board/<org>)."""
from __future__ import annotations

from typing import Any

import httpx

from app.connectors.base import Connector, strip_html

API = "https://api.ashbyhq.com/posting-api/job-board/{org}"


class AshbyConnector(Connector):
    name = "ashby"

    async def fetch(self, query: str | None, filters: dict[str, Any]) -> list[dict]:
        org = (filters.get("org") or query or "").strip()
        if not org:
            return []
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(API.format(org=org))
            resp.raise_for_status()
            data = resp.json()
        jobs: list[dict] = []
        for j in data.get("jobs", []):
            jobs.append(
                {
                    "source": self.name,
                    "external_id": f"{org}:{j.get('id')}",
                    "title": j.get("title", ""),
                    "company": filters.get("company") or org,
                    "location": j.get("location"),
                    "url": j.get("jobUrl") or j.get("applyUrl", ""),
                    "description": j.get("descriptionPlain")
                    or strip_html(j.get("descriptionHtml")),
                    "posted_at": None,
                    "raw": {"employmentType": j.get("employmentType")},
                }
            )
        return jobs
