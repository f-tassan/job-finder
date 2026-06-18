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
    (("city", "location", "where are you", "current location"), "city"),
    (("nationality",), "nationality"),
    (("national id", "national-id", "id number"), "national_id"),
]

# Substrings that mark a field we intentionally leave blank for the human.
SENSITIVE = (
    "salary",
    "compensation",
    "expected pay",
    "current pay",
    "why ",
    "cover letter",
    "cover_letter",
    "motivation",
    "sponsor",
    "visa",
    "notice period",
)


def candidate_values(data: dict) -> dict[str, str]:
    """Flatten the answer bank into form-fillable values (no sensitive fields)."""
    name = (data.get("full_name_en") or data.get("name") or "").strip()
    first = last = ""
    if name:
        parts = name.split()
        first = parts[0]
        last = " ".join(parts[1:]) if len(parts) > 1 else ""
    values = {
        "first_name": first,
        "last_name": last,
        "full_name": name,
        "email": data.get("email"),
        "phone": data.get("phone"),
        "linkedin": data.get("linkedin"),
        "city": data.get("city"),
        "nationality": data.get("nationality"),
        "national_id": data.get("national_id"),
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
    async def prefill(self, page: Any, values: dict[str, str]) -> PrefillResult:
        raise NotImplementedError


def get_applier(source: str | None, url: str | None) -> "Applier":
    from app.appliers import generic, greenhouse, lever

    u = (url or "").lower()
    s = (source or "").lower()
    if s == "greenhouse" or "greenhouse.io" in u:
        return greenhouse.GreenhouseApplier()
    if s == "lever" or "lever.co" in u:
        return lever.LeverApplier()
    return generic.GenericApplier()
