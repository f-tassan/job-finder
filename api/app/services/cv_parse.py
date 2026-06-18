"""Parse an uploaded CV into a structured master profile.

Uses Claude Haiku (cheap, high-volume) with structured JSON output. The parsed
result only *seeds* the answer bank — the user confirms/edits it, so this never
needs to be perfect, and it degrades gracefully: if there's no API key or the
call/extraction fails, we return None and the user fills the form manually.

Never invents data (CLAUDE.md hard rule): the prompt extracts only what's present.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from anthropic import AsyncAnthropic

from app.config import settings

logger = logging.getLogger(__name__)

# Cheap/high-volume model for CV parsing (pinned per CLAUDE.md §1).
PARSE_MODEL = "claude-haiku-4-5-20251001"

# Structured-output schema. Mirrors the Saudi-national answer bank (CLAUDE.md §6):
# National ID, no Iqama/visa fields. All optional — extract only what's present.
CV_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "full_name_en": {"type": ["string", "null"]},
        "full_name_ar": {"type": ["string", "null"]},
        "email": {"type": ["string", "null"]},
        "phone": {"type": ["string", "null"]},
        "city": {"type": ["string", "null"]},
        "linkedin": {"type": ["string", "null"]},
        "years_of_experience": {"type": ["number", "null"]},
        "summary": {"type": ["string", "null"]},
        "skills": {"type": "array", "items": {"type": "string"}},
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
        "experience": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "title": {"type": ["string", "null"]},
                    "company": {"type": ["string", "null"]},
                    "start": {"type": ["string", "null"]},
                    "end": {"type": ["string", "null"]},
                    "summary": {"type": ["string", "null"]},
                },
                "required": ["title", "company", "start", "end", "summary"],
            },
        },
    },
    "required": [
        "full_name_en",
        "full_name_ar",
        "email",
        "phone",
        "city",
        "linkedin",
        "years_of_experience",
        "summary",
        "skills",
        "education",
        "certifications",
        "experience",
    ],
}

_PROMPT = (
    "Extract a structured profile from the following CV text. Only use information "
    "actually present in the text — never invent, infer beyond what is written, or "
    "guess. Leave any field null/empty if it is not in the CV.\n\n--- CV TEXT ---\n"
)


def extract_text(file_path: str, filename: str | None) -> str:
    """Best-effort plain-text extraction from a PDF / DOCX / text CV."""
    path = Path(file_path)
    suffix = (Path(filename).suffix if filename else path.suffix).lower()
    try:
        if suffix == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(file_path)
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        if suffix in (".docx", ".doc"):
            import docx

            doc = docx.Document(file_path)
            return "\n".join(p.text for p in doc.paragraphs)
        return path.read_text(errors="ignore")
    except Exception:  # noqa: BLE001 - extraction is best-effort
        logger.exception("CV text extraction failed for %s", filename)
        return ""


async def parse_cv(file_path: str, filename: str | None) -> dict | None:
    """Return a structured profile dict, or None if parsing is unavailable."""
    if not settings.anthropic_api_key:
        return None

    text = extract_text(file_path, filename).strip()
    if not text:
        return None
    text = text[:60_000]  # keep well within context / cost bounds

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        resp = await client.messages.create(
            model=PARSE_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": _PROMPT + text}],
            output_config={"format": {"type": "json_schema", "schema": CV_SCHEMA}},
        )
        out = next((b.text for b in resp.content if b.type == "text"), None)
        return json.loads(out) if out else None
    except Exception:  # noqa: BLE001 - never block the upload on parse failure
        logger.exception("CV parsing via Claude failed")
        return None
    finally:
        await client.close()
