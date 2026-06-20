"""One-off: seed Faisal's PIF company searches with the corrected careers URLs.

Idempotent: upserts a `company` saved_search per company (by name), and disables
the superseded "PIF Companies" company_site / LinkedIn searches. Run inside the
api container:  python -m scripts.seed_companies
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.db import SessionLocal
from app.models import AppUser, SavedSearch

USER_EMAIL = "faisal.f.i.t@gmail.com"

# name -> (careers_urls, run_linkedin)
COMPANIES: dict[str, tuple[list[str], bool]] = {
    "NEOM": (["https://careers.neom.com/careers"], True),
    "Red Sea Global": (
        ["https://careers.theredsea.sa/go/Job-Opportunities/7716923/"],
        True,
    ),
    "ROSHN": (
        ["https://fa-epph-saasfaprod1.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1"],
        True,
    ),
    "Qiddiya": (["https://apply.workable.com/qiddiya-investment-company-1/"], True),
    "NHC": (
        ["https://eghj.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_2001"],
        True,
    ),
    "SEVEN": (["https://careers.seven.sa"], True),
    "Saudi Aramco": (
        [
            "https://careers.aramco.com/saudi/search/?createNewAlert=false&q=experienced&locationsearch=",
            "https://careers.aramco.com/saudi/search/?createNewAlert=false&q=graduate&locationsearch=",
        ],
        True,
    ),
    "SABIC": (
        ["https://jobs.sabic.com/search/?searchby=location&createNewAlert=false&q=&locationsearch="],
        True,
    ),
    "Ma'aden": (["https://careers.maaden.com/gb/en/search-results?m=3"], True),
    "ACWA Power": (
        ["https://careers.acwapower.com/search/?createNewAlert=false&q=&locationsearch=&optionsFacetsDD_department="],
        True,
    ),
    "Saudi Electricity Company": (
        [
            "https://jobs.se.com.sa/go/Experienced-Employee/7764123/",
            "https://jobs.se.com.sa/go/Fresh-Graduates/7764023/",
        ],
        True,
    ),
    "Tarshid": (
        ["https://ekqz.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/jobs"],
        True,
    ),
    "SAMI": (
        ["https://sami.jobs.hr.cloud.sap/search/?createNewAlert=false&q=&searchResultView=LIST"],
        True,
    ),
    "Lucid Motors": (["https://lucidmotors.com/careers/search"], True),
    "Ceer": (["https://jobs.ceermotors.com/go/Job-Search/7778723/"], True),
    "stc": (["https://careers.stc.com.sa/go/Experienced/7737023/"], True),
    "NUPCO": (
        ["https://www.nupco.com/NupcoJobPortal/user/login?destination=node/add/curriculum-vitae-cv"],
        True,
    ),
    "Lifera": (["https://lifera.com.sa/careers/"], True),
    "SALIC": (
        ["https://hen.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/SALIC-Job-Portal/jobs?mode=location"],
        True,
    ),
}


async def main() -> None:
    async with SessionLocal() as session:
        user = (
            await session.execute(select(AppUser).where(AppUser.email == USER_EMAIL))
        ).scalar_one_or_none()
        if user is None:
            print(f"user {USER_EMAIL} not found")
            return

        existing = {
            s.name: s
            for s in (
                await session.execute(
                    select(SavedSearch).where(SavedSearch.user_id == user.id)
                )
            )
            .scalars()
            .all()
        }

        # Disable the superseded combined PIF searches.
        for name in ("PIF Companies", "PIF Companies (LinkedIn)"):
            s = existing.get(name)
            if s is not None:
                s.enabled = False

        added = updated = 0
        for name, (urls, run_li) in COMPANIES.items():
            filters = {
                "careers_urls": urls,
                "company": name,
                "location": "Saudi Arabia",
                "linkedin": run_li,
            }
            s = existing.get(name)
            if s is None:
                session.add(
                    SavedSearch(
                        user_id=user.id,
                        name=name,
                        platform="company",
                        query=None,
                        filters=filters,
                        enabled=True,
                    )
                )
                added += 1
            else:
                s.platform = "company"
                s.filters = filters
                s.enabled = True
                updated += 1

        await session.commit()
        print(f"companies: +{added} new, {updated} updated; old PIF searches disabled")


if __name__ == "__main__":
    asyncio.run(main())
