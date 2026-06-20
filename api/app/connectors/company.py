"""Company connector: one saved search == one employer, discovered two ways.

A "company" search holds the employer's name plus its careers-page URL(s). For
each company we both:
  1. scrape its careers portal (delegates to the company_site connector, which
     renders JS portals like Workday/Oracle/SuccessFactors in the browser-worker), and
  2. search LinkedIn in company-mode for that employer's postings in KSA.

Results from both are merged and de-duplicated by URL. This is what powers the
companies list on the Searches page; the credentials page derives its login rows
from the same company searches.

filters.careers_urls -> list of careers-page URLs (preferred)
filters.careers_url  -> a single careers-page URL (also accepts query)
name (search.name)   -> employer display name, used as the LinkedIn brand
filters.linkedin     -> set false to skip the LinkedIn leg (careers only)
filters.location     -> LinkedIn location (default "Saudi Arabia")
"""
from __future__ import annotations

from typing import Any

from app.connectors.base import Connector


class CompanyConnector(Connector):
    name = "company"

    async def fetch(self, query: str | None, filters: dict[str, Any]) -> list[dict]:
        from app.connectors import company_site, linkedin

        urls = list(filters.get("careers_urls") or [])
        single = (filters.get("careers_url") or query or "").strip()
        if single and single not in urls:
            urls.append(single)
        urls = [u.strip() for u in urls if u and u.strip()]

        name = (filters.get("company") or filters.get("name") or "").strip()

        jobs: list[dict] = []

        # 1) Careers portal(s) — reuse the JS-rendering company_site connector.
        if urls:
            site_filters = {
                "urls": urls,
                "render": filters.get("render", True),
                "company": name or None,
            }
            try:
                jobs.extend(
                    await company_site.CompanySiteConnector().fetch(None, site_filters)
                )
            except Exception:  # noqa: BLE001 - one leg failing shouldn't sink the other
                pass

        # 2) LinkedIn, company-mode (only postings whose employer matches `name`).
        if name and filters.get("linkedin", True):
            li_filters = {
                "companies": [name],
                "location": filters.get("location") or "Saudi Arabia",
                "pages": filters.get("pages", 2),
            }
            try:
                jobs.extend(await linkedin.LinkedInConnector().fetch(None, li_filters))
            except Exception:  # noqa: BLE001
                pass

        # Dedupe by URL, keeping the first (careers) hit.
        seen: set[str] = set()
        out: list[dict] = []
        for j in jobs:
            u = j.get("url")
            if not u or u in seen:
                continue
            seen.add(u)
            out.append(j)
        return out
