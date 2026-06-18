"""Lever public postings API (api.lever.co/v0/postings/<company>)."""
from __future__ import annotations

from typing import Any

import httpx

from app.connectors.base import Connector

API = "https://api.lever.co/v0/postings/{company}?mode=json"


class LeverConnector(Connector):
    name = "lever"

    async def fetch(self, query: str | None, filters: dict[str, Any]) -> list[dict]:
        company = (filters.get("company") or query or "").strip()
        if not company:
            return []
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(API.format(company=company))
            resp.raise_for_status()
            postings = resp.json()
        jobs: list[dict] = []
        for p in postings:
            cats = p.get("categories") or {}
            jobs.append(
                {
                    "source": self.name,
                    "external_id": f"{company}:{p['id']}",
                    "title": p.get("text", ""),
                    "company": filters.get("company_name") or company,
                    "location": cats.get("location"),
                    "url": p.get("hostedUrl", ""),
                    "description": p.get("descriptionPlain") or p.get("description"),
                    "posted_at": None,
                    "raw": {"team": cats.get("team"), "commitment": cats.get("commitment")},
                }
            )
        return jobs
