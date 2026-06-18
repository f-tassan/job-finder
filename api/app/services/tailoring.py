"""Tailoring orchestration: build a tailored CV structure + cover letter for an
application, constrained to the user's answer bank + parsed CV.

Uses the LLM (Sonnet) when an API key is configured; otherwise falls back to a
deterministic assembly from the same data so the feature works without a key
(just less polished). Also computes a keyword-coverage % vs the job text.
"""
from __future__ import annotations

import re

from app.services import llm

_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z+#.]{2,}")
_STOP = {
    "the", "and", "for", "with", "you", "our", "are", "will", "your", "have",
    "this", "that", "from", "all", "any", "can", "who", "their", "they", "job",
    "role", "team", "work", "working", "experience", "years", "ability", "strong",
    "including", "across", "within", "while", "what", "how", "into", "must",
    "should", "would", "about", "more", "than", "such", "via", "etc", "per",
    "we", "us", "is", "to", "in", "of", "on", "as", "at", "an", "or", "be",
}


def _keywords(text: str, limit: int = 40) -> list[str]:
    seen: list[str] = []
    for w in _WORD_RE.findall((text or "").lower()):
        if w in _STOP or w in seen:
            continue
        seen.append(w)
        if len(seen) >= limit:
            break
    return seen


def keyword_coverage(job_text: str, cv_text: str) -> float:
    kws = _keywords(job_text)
    if not kws:
        return 0.0
    hay = (cv_text or "").lower()
    hit = sum(1 for k in kws if k in hay)
    return round(hit / len(kws), 4)


def _cv_to_text(cv: dict, cover_letter: str) -> str:
    parts = [cv.get("summary", ""), " ".join(cv.get("skills", []))]
    for e in cv.get("experience", []):
        parts.append(f"{e.get('title','')} {e.get('company','')}")
        parts.extend(e.get("bullets", []))
    for ed in cv.get("education", []):
        parts.append(f"{ed.get('degree','')} {ed.get('institution','')}")
    parts.extend(cv.get("certifications", []))
    parts.append(cover_letter)
    return "\n".join(p for p in parts if p)


def _deterministic(applicant: dict, job: dict) -> dict:
    """Assemble a CV + cover letter from the applicant data, no LLM."""
    name = applicant.get("full_name_en") or applicant.get("name") or "Candidate"
    fields = applicant.get("fields") or ([applicant["field"]] if applicant.get("field") else [])
    summary = applicant.get("summary") or (
        f"{', '.join(fields)} professional." if fields else ""
    )
    experience = []
    for e in applicant.get("experience", []) or []:
        bullets = []
        if e.get("summary"):
            bullets = [e["summary"]]
        experience.append(
            {
                "title": e.get("title") or "",
                "company": e.get("company") or "",
                "start": e.get("start"),
                "end": e.get("end"),
                "bullets": bullets,
            }
        )
    company = job.get("company") or "your organization"
    title = job.get("title") or "the role"
    cover_letter = (
        f"Dear Hiring Team,\n\n"
        f"I am writing to express my interest in the {title} position at {company}. "
        f"{summary} I believe my background aligns well with what your team is "
        f"looking for.\n\n"
        f"I would welcome the opportunity to discuss how my experience can "
        f"contribute to {company}.\n\nالسلام عليكم — thank you for your "
        f"consideration.\n\nالسلام عليكم,\n{name}"
    )
    return {
        "summary": summary,
        "skills": applicant.get("skills") or [],
        "experience": experience,
        "education": applicant.get("education") or [],
        "certifications": applicant.get("certifications") or [],
        "cover_letter": cover_letter,
    }


def build_applicant(field: str | None, data: dict, cv_parsed: dict | None) -> dict:
    """Merge answer-bank data with the parsed CV into one applicant fact sheet."""
    applicant = dict(data or {})
    if field and "field" not in applicant:
        applicant["field"] = field
    if cv_parsed:
        for key in ("summary", "skills", "experience", "education", "certifications"):
            if not applicant.get(key) and cv_parsed.get(key):
                applicant[key] = cv_parsed[key]
        if not applicant.get("full_name_en") and cv_parsed.get("full_name_en"):
            applicant["full_name_en"] = cv_parsed["full_name_en"]
    return applicant


async def tailor(applicant: dict, job: dict) -> dict:
    """Return {cv, cover_letter, keyword_coverage, used_llm}."""
    result = await llm.tailor_with_llm(applicant, job)
    used_llm = result is not None
    if not result:
        result = _deterministic(applicant, job)
    cover_letter = result.pop("cover_letter", "")
    cv = result
    job_text = f"{job.get('title','')} {job.get('description','')}"
    coverage = keyword_coverage(job_text, _cv_to_text(cv, cover_letter))
    return {
        "cv": cv,
        "cover_letter": cover_letter,
        "keyword_coverage": coverage,
        "used_llm": used_llm,
    }
