"""Greenhouse public job board JSON API.

filters/query supply the board token (the company slug in
boards.greenhouse.io/<token>). No auth required.
"""
from __future__ import annotations

from typing import Any

import httpx

from app.connectors.base import Connector, strip_html

API = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"


class GreenhouseConnector(Connector):
    name = "greenhouse"

    async def fetch(self, query: str | None, filters: dict[str, Any]) -> list[dict]:
        board = (filters.get("board") or query or "").strip()
        if not board:
            return []
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(API.format(board=board))
            resp.raise_for_status()
            data = resp.json()
        jobs: list[dict] = []
        for j in data.get("jobs", []):
            loc = (j.get("location") or {}).get("name")
            jobs.append(
                {
                    "source": self.name,
                    "external_id": f"{board}:{j['id']}",
                    "title": j.get("title", ""),
                    "company": filters.get("company") or board,
                    "location": loc,
                    "url": j.get("absolute_url", ""),
                    "description": strip_html(j.get("content")),
                    "posted_at": None,
                    "raw": {"board": board},
                }
            )
        return jobs
