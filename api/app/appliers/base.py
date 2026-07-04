"""Applier ABC + registry.

An applier fills the *known* fields of an application form from the user's
answer bank and flags everything it left blank (unknown OR sensitive) as
`missing` for the human to complete at review. It never submits. Appliers
operate on a Playwright `page` passed in by the prefill task, so this module has
no Playwright import (keeps non-browser images able to import it).

Sensitive fields (salary, "why this company", cover-letter free text) are
deliberately left blank (CLAUDE.md hard rule) and surfaced as missing.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

# Map a normalized field "key blob" (label/name/placeholder) to an answer-bank
# value key. Order matters: more specific first.
FIELD_PATTERNS: list[tuple[tuple[str, ...], str]] = [
    (("first name", "firstname", "given name", "first_name"), "first_name"),
    (("last name", "lastname", "surname", "family name", "last_name"), "last_name"),
    (("full name", "fullname", "your name", "name"), "full_name"),
    (("email", "e-mail"), "email"),
    (("phone", "mobile", "tel", "contact number"), "phone"),
    (("linkedin",), "linkedin"),
    (("date of birth", "date-of-birth", "birth date", "birthdate", "dob"), "date_of_birth"),
    (("marital status", "marital"), "marital_status"),
    (("gender",), "gender"),
    (("years of experience", "years_of_experience", "total experience"), "years_of_experience"),
    (("national address",), "national_address"),
    # "city" AFTER national address so "National Address" doesn't grab it.
    (("city", "location", "where are you", "current location"), "city"),
    (("nationality",), "nationality"),
    (("national id", "national-id", "id number"), "national_id"),
    (("notice period", "notice_period", "notice-period"), "notice_period"),
    # After nationality/national-id so those win first; catches the standalone
    # "Country" field many ATS forms require (often a react-select).
    (("country",), "country"),
]

# Substrings that mark a field we ALWAYS leave blank for the human — pay and
# legal-status questions the user must own and that can't be drafted from facts.
# (Open-ended motivation / "why this company" / cover-letter fields are NOT here:
# the LLM drafts those from the answer bank and flags them "Check" for review.)
SENSITIVE = (
    "salary",
    "compensation",
    "expected pay",
    "current pay",
    "sponsor",
    "visa",
    "sponsorship",
)


def candidate_values(data: dict) -> dict[str, str]:
    """Flatten the answer bank into form-fillable values (no sensitive fields)."""
    name = (data.get("full_name_en") or data.get("name") or "").strip()
    first = last = ""
    if name:
        parts = name.split()
        first = parts[0]
        last = " ".join(parts[1:]) if len(parts) > 1 else ""
    # Country: use an explicit value if stored, else infer for Saudi nationals
    # (this app is for the Saudi market / Saudi nationals) so the required
    # "Country" field on ATS forms gets filled.
    country = (data.get("country") or "").strip()
    if not country and (data.get("nationality") or "").strip().lower().startswith(
        "saudi"
    ):
        country = "Saudi Arabia"
    values = {
        "first_name": first,
        "last_name": last,
        "full_name": name,
        "full_name_ar": data.get("full_name_ar"),
        "email": data.get("email"),
        "phone": data.get("phone"),
        "linkedin": data.get("linkedin"),
        "city": data.get("city"),
        "national_address": data.get("national_address"),
        "nationality": data.get("nationality"),
        "national_id": data.get("national_id"),
        "date_of_birth": data.get("date_of_birth"),
        "gender": data.get("gender"),
        "marital_status": data.get("marital_status"),
        "education": data.get("education"),
        "years_of_experience": data.get("years_of_experience"),
        "notice_period": data.get("notice_period"),
        "country": country,
    }
    return {k: str(v) for k, v in values.items() if v}


def match_field(blob: str) -> str | None:
    blob = blob.lower()
    for needles, key in FIELD_PATTERNS:
        if any(n in blob for n in needles):
            return key
    return None


def is_sensitive(blob: str) -> bool:
    blob = blob.lower()
    return any(s in blob for s in SENSITIVE)


class PrefillResult(dict):
    """{'filled': {label: value}, 'missing': [label, ...]}"""


class Applier(ABC):
    name: str

    @abstractmethod
    async def prefill(
        self,
        page: Any,
        values: dict[str, str],
        *,
        credentials: dict[str, str] | None = None,
        save_draft: bool = False,
        profile: dict | None = None,
        overrides: dict[str, str] | None = None,
    ) -> PrefillResult:
        """Fill the form. If `credentials` (the user's own portal login) are
        given and `save_draft` is set, an enterprise applier may sign in and save
        a draft — never submit. Other appliers ignore both.

        `profile` is the full answer bank; appliers that support it use an LLM to
        answer unknown required fields strictly from it (never inventing), leaving
        sensitive/ungrounded fields blank for the human.

        `overrides` maps a field's display label to a value the human entered at
        review (e.g. salary, "why this company"). It takes precedence over every
        heuristic and is the only way the sensitive fields get filled — used by
        the explicit auto-submit so review-then-one-click actually completes."""
        raise NotImplementedError


def get_applier(source: str | None, url: str | None) -> "Applier":
    from app.appliers import (
        generic,
        greenhouse,
        icims,
        lever,
        oracle,
        recruitee,
        rippling,
        successfactors,
        workday,
        zenats,
    )

    u = (url or "").lower()
    s = (source or "").lower()
    if s == "greenhouse" or "greenhouse.io" in u:
        return greenhouse.GreenhouseApplier()
    if s == "lever" or "lever.co" in u:
        return lever.LeverApplier()
    if s == "zenats" or "zenats.com" in u:
        return zenats.ZenAtsApplier()
    if s == "icims" or "icims.com" in u:
        return icims.ICIMSApplier()
    if s == "rippling" or "rippling.com" in u:
        return rippling.RipplingApplier()
    if s == "recruitee" or "recruitee.com" in u:
        return recruitee.RecruiteeApplier()
    if s == "workday" or "myworkdayjobs.com" in u or ".workday.com" in u:
        return workday.WorkdayApplier()
    if (
        s == "successfactors"
        or "successfactors." in u
        or "sapsf." in u
        or "jobs.sap.com" in u
    ):
        return successfactors.SuccessFactorsApplier()
    if (
        s == "oracle"
        or "taleo.net" in u
        or "/hcmui/candidateexperience" in u
        or "oraclecloud.com" in u
    ):
        return oracle.OracleApplier()
    return generic.GenericApplier()
