"""Oracle Recruiting Cloud / Candidate Experience public job API.

Many large employers (e.g. Ma'aden and much of the Gulf market) post on Oracle
Recruiting, whose Candidate Experience site exposes a public REST API — so we can
discover jobs WITH their real apply URLs, instead of depending on a LinkedIn page
that hides the destination.

A saved search supplies the employer's site in `filters`:
  host         -> the ORC host, e.g. "fa-epod-saasfaprod1.fa.ocs.oraclecloud.com"
  site_number  -> the API site number (default "CX_1")
  site_code    -> the URL site code (default: site_number without its "_N", e.g. "CX")
  company      -> display name (default: the host)
  limit        -> max jobs to pull (default 200)
`query` (optional) is passed as the ORC keyword filter.

The apply URL we store is the Candidate Experience job page; the Oracle applier
drives it (Apply → email gate → form), and email verification rides the OTP relay.
"""
from __future__ import annotations

from typing import Any

import httpx

from app.connectors.base import Connector, strip_html

_REQS = (
    "https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
)
_DETAIL = (
    "https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
)
_JOB_URL = "https://{host}/hcmUI/CandidateExperience/en/sites/{code}/job/{id}"
_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)


class OracleConnector(Connector):
    name = "oracle"

    async def fetch(self, query: str | None, filters: dict[str, Any]) -> list[dict]:
        host = (filters.get("host") or "").strip().replace("https://", "").rstrip("/")
        if not host:
            return []
        site_number = (filters.get("site_number") or "CX_1").strip()
        site_code = (filters.get("site_code") or site_number.split("_")[0]).strip()
        company = filters.get("company") or host
        limit = min(int(filters.get("limit", 200)), 500)
        keyword = (query or filters.get("keyword") or "").strip()
        fetch_desc = filters.get("fetch_descriptions", True)
        max_desc = min(int(filters.get("max_descriptions", 60)), 200)

        jobs: list[dict] = []
        seen: set[str] = set()
        async with httpx.AsyncClient(
            timeout=25, headers={"User-Agent": _UA}
        ) as client:
            offset = 0
            page = min(limit, 100)
            while len(jobs) < limit:
                finder = (
                    f"findReqs;siteNumber={site_number},sortBy=POSTING_DATES_DESC,"
                    f"limit={page},offset={offset}"
                )
                if keyword:
                    finder += f",keyword={keyword}"
                try:
                    resp = await client.get(
                        _REQS.format(host=host),
                        params={
                            "onlyData": "true",
                            "expand": "requisitionList.secondaryLocations",
                            "finder": finder,
                        },
                    )
                    resp.raise_for_status()
                    items = resp.json().get("items") or []
                except Exception:  # noqa: BLE001 - one bad page shouldn't sink it
                    break
                reqs = items[0].get("requisitionList", []) if items else []
                if not reqs:
                    break
                for r in reqs:
                    rid = str(r.get("Id") or "").strip()
                    title = (r.get("Title") or "").strip()
                    if not rid or not title or rid in seen:
                        continue
                    seen.add(rid)
                    jobs.append(
                        {
                            "source": self.name,
                            "external_id": f"{host}:{rid}",
                            "title": title,
                            "company": company,
                            "location": r.get("PrimaryLocation"),
                            "url": _JOB_URL.format(host=host, code=site_code, id=rid),
                            "description": strip_html(r.get("ShortDescriptionStr")),
                            "posted_at": None,
                            "raw": {"host": host, "site_number": site_number, "req_id": rid},
                        }
                    )
                if len(reqs) < page:
                    break
                offset += page

            # The list omits the full text; enrich the first N with the real
            # description so relevance ranking has something to work with.
            if fetch_desc:
                for job in jobs[:max_desc]:
                    rid = job["raw"]["req_id"]
                    try:
                        rd = await client.get(
                            _DETAIL.format(host=host),
                            params={
                                "onlyData": "true",
                                "expand": "all",
                                "finder": f"ById;Id={rid},siteNumber={site_number}",
                            },
                        )
                        if rd.status_code != 200:
                            continue
                        det = (rd.json().get("items") or [{}])[0]
                        desc = det.get("ExternalDescriptionStr") or det.get(
                            "CorporateDescriptionStr"
                        )
                        if desc:
                            job["description"] = strip_html(desc)
                    except Exception:  # noqa: BLE001 - description is best-effort
                        continue
        return jobs[:limit]
