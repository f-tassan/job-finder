"""Connector ABC and registry.

A connector turns a saved search (query + filters) into a list of *normalized
job dicts* with keys: source, external_id, title, company, location, url,
description, posted_at (optional), raw. New sources are drop-in: implement the
ABC and register it in `get_connector`.
"""
from __future__ import annotations

import html
import re
from abc import ABC, abstractmethod
from typing import Any

_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str | None) -> str | None:
    if not text:
        return text
    # Strip tags first, then decode HTML entities (&amp; -> &, &#x27; -> ', …) so
    # scraped titles/descriptions read naturally instead of showing raw entities.
    return re.sub(r"[ \t]+", " ", html.unescape(_TAG_RE.sub(" ", text))).strip()


def clean_field(text: str | None) -> str | None:
    """Normalize a short normalized-job field (title/company/location): decode
    HTML entities and collapse whitespace. Use for connectors whose source is a
    JSON API (no tags to strip) so e.g. `R&amp;D Engineer` becomes `R&D Engineer`."""
    if not text:
        return text
    return re.sub(r"\s+", " ", html.unescape(text)).strip() or None


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
        company,
        company_site,
        email_alerts,
        gov_portals,
        greenhouse,
        lever,
        linkedin,
        oracle,
    )

    mapping: dict[str, type[Connector]] = {
        "greenhouse": greenhouse.GreenhouseConnector,
        "lever": lever.LeverConnector,
        "ashby": ashby.AshbyConnector,
        "linkedin": linkedin.LinkedInConnector,
        "bayt": bayt.BaytConnector,
        "company": company.CompanyConnector,
        "company_site": company_site.CompanySiteConnector,
        "gov_portals": gov_portals.GovPortalsConnector,
        "email_alerts": email_alerts.EmailAlertsConnector,
        "oracle": oracle.OracleConnector,
    }
    cls = mapping.get(platform)
    return cls() if cls else None
