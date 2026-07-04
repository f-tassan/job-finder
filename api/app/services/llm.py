"""Provider-agnostic LLM layer (OpenAI or Anthropic) for structured JSON.

Used by CV parsing and tailoring. Picks the provider from settings
(`llm_provider` + which API key is present). Both paths request strict JSON
matching a schema; on any error / no provider, callers fall back to deterministic
behavior. The tailoring system prompt forbids inventing qualifications
(CLAUDE.md hard rule).
"""
from __future__ import annotations

import json
import logging

from app.config import settings

logger = logging.getLogger(__name__)

# Anthropic models — only used when LLM_PROVIDER=anthropic (pluggable fallback;
# this deployment runs on OpenAI). Sonnet 5 is the tailor model because it (unlike
# Sonnet 4.6) supports structured outputs, which every JSON-returning call needs.
_ANTHROPIC_PARSE = "claude-haiku-4-5-20251001"
_ANTHROPIC_TAILOR = "claude-sonnet-5"

TAILOR_SYSTEM = (
    "You are a senior professional CV writer for the Saudi Arabian job market. "
    "You rewrite an applicant's real CV so it is maximally compelling for ONE "
    "specific job — reading like a strong candidate wrote it carefully, never "
    "like a template or an AI.\n\n"
    "ABSOLUTE RULES:\n"
    "- Use ONLY facts present in the applicant data. Never invent employers, "
    "titles, dates, degrees, certifications, skills, or numbers.\n"
    "- SELECT, don't dump: keep only the content most relevant to the target "
    "job; compress or drop the rest. Reorder so the most relevant items come "
    "first.\n"
    "- Mirror the job's own terminology only where genuinely true of the "
    "applicant.\n\n"
    "THE CV MUST FIT ONE A4 PAGE. Hard limits that make that happen:\n"
    "- summary: 2–3 lines (max 45 words), positioning the candidate for THIS "
    "role specifically — not a generic self-description.\n"
    "- skills: 8–12, most job-relevant first.\n"
    "- experience: the 3–4 most relevant roles only. 2–4 bullets each, max ~20 "
    "words per bullet; older or less relevant roles get 1 bullet or none. Each "
    "bullet: strong verb, one concrete accomplishment or responsibility, "
    "metrics only when present in the data.\n"
    "- education: one line per degree. certifications: job-relevant only.\n\n"
    "STYLE: plain, specific, confident. Vary sentence openings. Forbidden: "
    "'responsible for', 'results-driven', 'dynamic', 'passionate', 'proven "
    "track record', 'leverage', and any buzzword filler. ATS-safe plain text "
    "with standard sections."
)

# Structured-output schema for the tailored CV + cover letter.
TAILOR_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "skills": {"type": "array", "items": {"type": "string"}},
        "experience": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "title": {"type": "string"},
                    "company": {"type": "string"},
                    "start": {"type": ["string", "null"]},
                    "end": {"type": ["string", "null"]},
                    "bullets": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "company", "start", "end", "bullets"],
            },
        },
        "education": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "degree": {"type": ["string", "null"]},
                    "institution": {"type": ["string", "null"]},
                    "year": {"type": ["string", "null"]},
                },
                "required": ["degree", "institution", "year"],
            },
        },
        "certifications": {"type": "array", "items": {"type": "string"}},
        "cover_letter": {"type": "string"},
    },
    "required": [
        "summary",
        "skills",
        "experience",
        "education",
        "certifications",
        "cover_letter",
    ],
}


def active_provider() -> str | None:
    """Resolve the active LLM provider, or None if no key is configured."""
    p = (settings.llm_provider or "auto").lower()
    has_openai = bool(settings.openai_api_key)
    has_anthropic = bool(settings.anthropic_api_key)
    if p == "openai":
        return "openai" if has_openai else None
    if p == "anthropic":
        return "anthropic" if has_anthropic else None
    # auto
    if has_openai:
        return "openai"
    if has_anthropic:
        return "anthropic"
    return None


def available() -> bool:
    return active_provider() is not None


def _model_for(provider: str, kind: str) -> str:
    if provider == "openai":
        return (
            settings.openai_tailor_model
            if kind == "tailor"
            else settings.openai_parse_model
        )
    return _ANTHROPIC_TAILOR if kind == "tailor" else _ANTHROPIC_PARSE


async def complete_json(
    *, system: str, prompt: str, schema: dict, kind: str
) -> dict | None:
    """Return a dict matching `schema`, or None if unavailable / on error.

    kind: "parse" (cheap model) or "tailor" (quality model).
    """
    provider = active_provider()
    if provider is None:
        return None
    model = _model_for(provider, kind)
    try:
        if provider == "openai":
            return await _openai_json(model, system, prompt, schema)
        return await _anthropic_json(model, system, prompt, schema)
    except Exception:  # noqa: BLE001 - never block the caller; fall back
        logger.exception("LLM (%s) structured call failed", provider)
        return None


async def complete_text(*, system: str, prompt: str, kind: str = "parse") -> str | None:
    """Plain-text completion on the cheap model (Telegram chat assistant).
    Returns None if no provider is configured or on error."""
    provider = active_provider()
    if provider is None:
        return None
    model = _model_for(provider, kind)
    try:
        if provider == "openai":
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=settings.openai_api_key)
            try:
                resp = await client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=700,
                )
                return resp.choices[0].message.content
            finally:
                await client.close()
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        try:
            resp = await client.messages.create(
                model=model,
                max_tokens=700,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            return next((b.text for b in resp.content if b.type == "text"), None)
        finally:
            await client.close()
    except Exception:  # noqa: BLE001 - never block the caller
        logger.exception("LLM (%s) text call failed", provider)
        return None


async def _openai_json(model, system, prompt, schema) -> dict | None:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "result", "schema": schema, "strict": True},
            },
        )
        content = resp.choices[0].message.content
        return json.loads(content) if content else None
    finally:
        await client.close()


async def _anthropic_json(model, system, prompt, schema) -> dict | None:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        resp = await client.messages.create(
            model=model,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        text = next((b.text for b in resp.content if b.type == "text"), None)
        return json.loads(text) if text else None
    finally:
        await client.close()


_RANK_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "scores": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "score": {"type": "number"},
                },
                "required": ["id", "score"],
            },
        }
    },
    "required": ["scores"],
}

_RANK_SYSTEM = (
    "You are a strict job-matching expert for the Saudi Arabian market. Given a "
    "candidate profile and a list of jobs, score each job 0..1 for genuine fit. "
    "Be discriminating, not generous:\n"
    "- Same profession/domain as the candidate is required for a high score. A "
    "different engineering discipline or unrelated field (e.g. a mechanical, "
    "civil, sales, or fire-safety role for a SOFTWARE engineer) must score LOW "
    "(<=0.2), even if the word 'engineer' appears.\n"
    "- Reward matching core skills, technologies, and seniority; penalize "
    "mismatched seniority or missing core requirements.\n"
    "- 0.8-1.0 excellent fit; 0.5-0.7 plausible; 0.2-0.4 weak; 0.0-0.1 irrelevant.\n"
    "Return a score for every job id provided."
)


async def rank_jobs(profile_text: str, jobs: list[dict]) -> dict[str, float] | None:
    """LLM relevance re-rank. Returns {job_id: score in [0,1]} or None."""
    if not jobs or not available():
        return None
    prompt = (
        f"CANDIDATE PROFILE:\n{profile_text[:6000]}\n\nJOBS (id, title, company, "
        f"location):\n{json.dumps(jobs, ensure_ascii=False)[:12000]}\n\n"
        "Score every job id for fit."
    )
    res = await complete_json(
        system=_RANK_SYSTEM, prompt=prompt, schema=_RANK_SCHEMA, kind="rank"
    )
    if not res:
        return None
    out: dict[str, float] = {}
    for s in res.get("scores", []):
        try:
            out[str(s["id"])] = max(0.0, min(1.0, float(s["score"])))
        except (KeyError, TypeError, ValueError):
            continue
    return out or None


_LETTER_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"cover_letter": {"type": "string"}},
    "required": ["cover_letter"],
}


async def tailor_with_llm(
    applicant: dict,
    job: dict,
    *,
    want_cv: bool = True,
    want_cover_letter: bool = True,
) -> dict | None:
    """Tailored CV and/or cover letter, constrained to applicant facts. None if
    no key. Whatever isn't wanted is dropped from both the prompt and the schema,
    so a letter-only request doesn't pay for CV tokens and vice versa."""
    if not (want_cv or want_cover_letter):
        return None
    cover_clause = (
        "a natural cover letter: 3 short paragraphs addressed to the hiring "
        "team, specific to this company and role, grounded in the applicant's "
        "real background, warm but professional, no clichés"
        if want_cover_letter
        else ""
    )
    cv_clause = (
        "a ONE-PAGE tailored CV (summary, skills, experience with bullets, "
        "education, certifications) respecting every hard limit"
        if want_cv
        else ""
    )
    ask = " and ".join(c for c in (cv_clause, cover_clause) if c)
    prompt = (
        "APPLICANT DATA (the only facts you may use):\n"
        f"{json.dumps(applicant, ensure_ascii=False)[:12000]}\n\n"
        "TARGET JOB:\n"
        f"{json.dumps(job, ensure_ascii=False)[:8000]}\n\n"
        f"Produce {ask}. Select and rewrite the applicant's real content to fit "
        "this role — do not fabricate anything, and do not exceed the limits."
    )
    if not want_cv:
        schema = _LETTER_SCHEMA
    elif not want_cover_letter:
        schema = {
            **TAILOR_SCHEMA,
            "properties": {
                k: v
                for k, v in TAILOR_SCHEMA["properties"].items()
                if k != "cover_letter"
            },
            "required": [r for r in TAILOR_SCHEMA["required"] if r != "cover_letter"],
        }
    else:
        schema = TAILOR_SCHEMA
    return await complete_json(
        system=TAILOR_SYSTEM, prompt=prompt, schema=schema, kind="tailor"
    )
