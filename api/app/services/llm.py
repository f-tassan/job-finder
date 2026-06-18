"""Anthropic client + tailoring prompt (Sonnet).

Produces a structured, ATS-friendly CV + cover letter, *strictly constrained to
the facts provided* (answer bank + parsed CV). The system instruction forbids
inventing qualifications (CLAUDE.md hard rule). Returns None if no API key so
callers can fall back to a deterministic assembly.
"""
from __future__ import annotations

import json
import logging

from app.config import settings

logger = logging.getLogger(__name__)

TAILOR_MODEL = "claude-sonnet-4-6"

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

_SYSTEM = (
    "You are an expert CV writer for the Saudi Arabian job market. You tailor an "
    "applicant's existing CV to a specific job. ABSOLUTE RULE: use ONLY facts "
    "present in the applicant data provided — never invent employers, titles, "
    "dates, degrees, skills, or metrics. You may rephrase, reorder, and emphasize "
    "to match the job, and mirror the job's exact skill/keyword terms ONLY where "
    "they are genuinely true of the applicant. Keep it ATS-safe: plain text, "
    "standard sections, concise bullet points starting with strong verbs."
)


async def tailor_with_llm(applicant: dict, job: dict) -> dict | None:
    if not settings.anthropic_api_key:
        return None
    from anthropic import AsyncAnthropic

    prompt = (
        "APPLICANT DATA (the only facts you may use):\n"
        f"{json.dumps(applicant, ensure_ascii=False)[:12000]}\n\n"
        "TARGET JOB:\n"
        f"{json.dumps(job, ensure_ascii=False)[:8000]}\n\n"
        "Produce a tailored CV (summary, skills, experience with bullets, "
        "education, certifications) and a short, natural cover letter (3 short "
        "paragraphs) addressed to the hiring team. Do not fabricate anything."
    )
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        resp = await client.messages.create(
            model=TAILOR_MODEL,
            max_tokens=4096,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": TAILOR_SCHEMA}},
        )
        text = next((b.text for b in resp.content if b.type == "text"), None)
        return json.loads(text) if text else None
    except Exception:  # noqa: BLE001 - fall back to deterministic assembly
        logger.exception("LLM tailoring failed; falling back")
        return None
    finally:
        await client.close()
