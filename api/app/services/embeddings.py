"""Local sentence-transformers embeddings (all-MiniLM-L6-v2, 384-dim).

The model import is lazy and cached so that images without the `ml` extra (e.g.
the browser-worker) can still import this module for task registration without
pulling in torch. Only code that actually calls `embed()` needs the model.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DIM = 384


@lru_cache(maxsize=1)
def _model() -> Any:
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME)


def embed(text: str) -> list[float]:
    """Return a normalized 384-dim embedding for `text`."""
    vec = _model().encode(text or "", normalize_embeddings=True)
    return vec.tolist()


def job_text(
    title: str,
    company: str | None,
    location: str | None,
    description: str | None,
) -> str:
    parts = [title]
    if company:
        parts.append(company)
    if location:
        parts.append(location)
    if description:
        parts.append(description)
    return "\n".join(parts)[:8000]


def profile_text(field: str | None, data: dict) -> str:
    """Build the text that represents a user's profile for relevance matching."""
    import json

    parts: list[str] = []
    if field:
        parts.append(f"Field: {field}")
    for key in (
        "summary",
        "years_of_experience",
        "skills",
        "education",
        "certifications",
        "experience",
    ):
        val = data.get(key)
        if not val:
            continue
        if isinstance(val, (list, dict)):
            parts.append(f"{key}: {json.dumps(val, ensure_ascii=False)[:2000]}")
        else:
            parts.append(f"{key}: {val}")
    return "\n".join(parts)[:8000] or (field or "")
