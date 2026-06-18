"""Per-user relevance: hard filters + cosine similarity.

Pure/stateless so it's unit-testable. Discovery wires it to the DB: it applies a
user's saved-search filters to each job, then scores survivors by cosine
similarity between the user's profile embedding and the job embedding.
"""
from __future__ import annotations

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
