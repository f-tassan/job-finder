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

# Anthropic models (pinned per CLAUDE.md §1).
_ANTHROPIC_PARSE = "claude-haiku-4-5-20251001"
_ANTHROPIC_TAILOR = "claude-sonnet-4-6"

TAILOR_SYSTEM = (
    "You are an expert CV writer for the Saudi Arabian job market. You tailor an "
    "applicant's existing CV to a specific job. ABSOLUTE RULE: use ONLY facts "
    "present in the applicant data provided — never invent employers, titles, "
    "dates, degrees, skills, or metrics. You may rephrase, reorder, and emphasize "
    "to match the job, and mirror the job's exact skill/keyword terms ONLY where "
    "they are genuinely true of the applicant. Keep it ATS-safe: plain text, "
    "standard sections, concise bullet points starting with strong verbs."
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


_FIELD_ANSWER_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "answers": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "answer": {"type": "string"},
                },
                "required": ["id", "answer"],
            },
        }
    },
    "required": ["answers"],
}

_FIELD_ANSWER_SYSTEM = (
    "You fill job-application form fields for a candidate using ONLY the facts in "
    "the provided answer bank. ABSOLUTE RULES:\n"
    "- Never invent or assume qualifications, employers, titles, dates, numbers, or "
    "experience that are not present in the answer-bank data.\n"
    "- If a field's answer is not directly supported by the data, return an empty "
    "string for that field.\n"
    "- Never answer salary/compensation questions or subjective 'why this "
    "company/role/motivation' questions — return an empty string for those.\n"
    "- When a field lists options, return EXACTLY one of the given option strings, "
    "or an empty string if none genuinely fits.\n"
    "- Keep answers concise and strictly factual."
)


async def answer_form_fields(
    profile: dict, fields: list[dict]
) -> dict[str, str]:
    """Answer unknown application-form fields strictly from the answer bank.

    `fields` is a list of {"id", "label", "options"?(list[str])}. Returns
    {id: answer}; an empty/whitespace answer means "not grounded — leave blank".
    Returns {} if no LLM is configured or on error (caller leaves fields blank).
    Used for pre-fill review only; the human verifies every value before submit.
    """
    if not fields or not available():
        return {}
    prompt = (
        "ANSWER BANK (the only facts you may use):\n"
        f"{json.dumps(profile, ensure_ascii=False)[:10000]}\n\n"
        "FORM FIELDS to answer (each has an id, a label, and optionally a closed "
        "set of options):\n"
        f"{json.dumps(fields, ensure_ascii=False)[:6000]}\n\n"
        "Return an answer for every field id. Use an empty string whenever the "
        "answer bank does not directly support an answer."
    )
    res = await complete_json(
        system=_FIELD_ANSWER_SYSTEM,
        prompt=prompt,
        schema=_FIELD_ANSWER_SCHEMA,
        kind="parse",
    )
    if not res:
        return {}
    out: dict[str, str] = {}
    for a in res.get("answers", []):
        try:
            ans = str(a.get("answer", "")).strip()
            if ans:
                out[str(a["id"])] = ans
        except (KeyError, TypeError, ValueError):
            continue
    return out


async def tailor_with_llm(applicant: dict, job: dict) -> dict | None:
    """Tailored CV + cover letter, constrained to applicant facts. None if no key."""
    prompt = (
        "APPLICANT DATA (the only facts you may use):\n"
        f"{json.dumps(applicant, ensure_ascii=False)[:12000]}\n\n"
        "TARGET JOB:\n"
        f"{json.dumps(job, ensure_ascii=False)[:8000]}\n\n"
        "Produce a tailored CV (summary, skills, experience with bullets, "
        "education, certifications) and a short, natural cover letter (3 short "
        "paragraphs) addressed to the hiring team. Do not fabricate anything."
    )
    return await complete_json(
        system=TAILOR_SYSTEM, prompt=prompt, schema=TAILOR_SCHEMA, kind="tailor"
    )
