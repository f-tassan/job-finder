"""Connector ABC and registry.

A connector turns a saved search (query + filters) into a list of *normalized
job dicts* with keys: source, external_id, title, company, location, url,
description, posted_at (optional), raw. New sources are drop-in: implement the
ABC and register it in `get_connector`.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any

_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str | None) -> str | None:
    if not text:
        return text
    return re.sub(r"[ \t]+", " ", _TAG_RE.sub(" ", text)).strip()


class Connector(ABC):
    name: str

    @abstractmethod
    async def fetch(self, query: str | None, filters: dict[str, Any]) -> list[dict]:
        """Return normalized job dicts for this saved search."""
        raise NotImplementedError


def get_connector(platform: str) -> Connector | None:
    from app.connectors import (
        ashby,
        bayt,
        company_site,
        email_alerts,
        gov_portals,
        greenhouse,
        lever,
        linkedin,
    )

    mapping: dict[str, type[Connector]] = {
        "greenhouse": greenhouse.GreenhouseConnector,
        "lever": lever.LeverConnector,
        "ashby": ashby.AshbyConnector,
        "linkedin": linkedin.LinkedInConnector,
        "bayt": bayt.BaytConnector,
        "company_site": company_site.CompanySiteConnector,
        "gov_portals": gov_portals.GovPortalsConnector,
        "email_alerts": email_alerts.EmailAlertsConnector,
    }
    cls = mapping.get(platform)
    return cls() if cls else None
