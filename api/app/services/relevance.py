"""Per-user relevance: hard filters + cosine similarity.

Pure/stateless so it's unit-testable. Discovery wires it to the DB: it applies a
user's saved-search filters to each job, then scores survivors by cosine
similarity between the user's profile embedding and the job embedding.
"""
from __future__ import annotations

import re
from typing import Iterable

import numpy as np

# KSA-relevant location tokens (CLAUDE.md §5). "remote" is always allowed.
KSA_TOKENS = (
    "saudi",
    "ksa",
    "riyadh",
    "jeddah",
    "dammam",
    "khobar",
    "neom",
    "mecca",
    "makkah",
    "medina",
    "madinah",
    "remote",
)


# KSA-specific tokens (no bare "remote" — "Remote, US" must NOT pass).
_KSA_STRICT = tuple(t for t in KSA_TOKENS if t != "remote")


def is_ksa(location: str | None, description: str | None = None) -> bool:
    """True only if the posting is in Saudi Arabia (or explicitly remote-KSA).

    Conservative: empty/unknown location does NOT pass, and a bare "Remote" with a
    non-KSA country (e.g. "Remote, US") does NOT pass — we prefer precision when the
    user asks to limit to Saudi Arabia.
    """
    text = " ".join(filter(None, [location, description])).lower()
    if not text.strip():
        return False
    if any(t in text for t in _KSA_STRICT):
        return True
    # Allow "remote" only when not tied to another country (e.g. just "Remote").
    return text.strip() in {"remote", "remote/anywhere", "anywhere", "worldwide"}


# Obviously-foreign location signals. Used to drop null-location company_site
# postings (PIF's global portfolio companies list mostly non-KSA roles) whose
# title carries a city/state/country, e.g. "… Austin, TX" or "… Singapore".
_FOREIGN_TOKENS = (
    # countries / regions
    "united states", "usa", "u.s.", "canada", "mexico", "brazil", "argentina",
    "united kingdom", "england", "scotland", "ireland", "france", "germany",
    "spain", "italy", "netherlands", "switzerland", "sweden", "norway", "poland",
    "china", "japan", "korea", "singapore", "india", "pakistan", "bangladesh",
    "indonesia", "malaysia", "thailand", "vietnam", "philippines", "australia",
    "new zealand", "south africa", "nigeria", "kenya", "turkey", "egypt",
    # major non-KSA cities
    "london", "paris", "berlin", "munich", "amsterdam", "zurich", "dublin",
    "new york", "san francisco", "los angeles", "austin", "seattle", "boston",
    "chicago", "houston", "dallas", "atlanta", "denver", "plantation",
    "princeton", "toronto", "vancouver", "shanghai", "beijing", "shenzhen",
    "hong kong", "tokyo", "seoul", "mumbai", "bangalore", "bengaluru", "delhi",
    "hyderabad", "sydney", "melbourne", "dubai", "abu dhabi",
)
# US state abbreviations — matched only as standalone tokens to avoid false hits.
_FOREIGN_ABBR = (
    "tx", "fl", "ny", "ca", "wa", "ma", "il", "ga", "co", "nj", "pa", "az",
    "nc", "va", "oh", "mi", "or", "nv", "ut", "mn", "uk", "us",
)
_ABBR_RE = re.compile(r"\b(" + "|".join(_FOREIGN_ABBR) + r")\b", re.IGNORECASE)


def mentions_non_ksa(text: str | None) -> bool:
    """True if the text clearly names a non-KSA location.

    Conservative: only fires on an explicit foreign city/state/country so that
    null-location KSA jobs (which usually name no place) are kept.
    """
    if not text:
        return False
    low = text.lower()
    if any(t in low for t in _FOREIGN_TOKENS):
        return True
    return bool(_ABBR_RE.search(low))


def cosine_similarity(a: Iterable[float], b: Iterable[float]) -> float:
    va, vb = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


def passes_hard_filters(
    *,
    title: str,
    location: str | None,
    description: str | None,
    filters: dict,
) -> bool:
    text = " ".join(filter(None, [title, location, description])).lower()
    loc = (location or "").lower()

    locations = [s.lower() for s in (filters.get("locations") or [])]
    if locations:
        if not any(t in loc or t in text for t in locations):
            return False

    include = [s.lower() for s in (filters.get("include_keywords") or [])]
    if include and not any(k in text for k in include):
        return False

    exclude = [s.lower() for s in (filters.get("exclude_keywords") or [])]
    if exclude and any(k in text for k in exclude):
        return False

    seniority = (filters.get("seniority") or "").lower().strip()
    if seniority and seniority not in text:
        return False

    return True
