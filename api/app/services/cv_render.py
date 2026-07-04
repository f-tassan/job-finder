"""Render a tailored CV / cover letter to a professional, ATS-safe PDF
(WeasyPrint).

ATS rules (CLAUDE.md §8): single column, no tables/text-boxes/headers-footers/
images, standard section headings, real selectable text. The design goal is a
clean one-page document that looks carefully written by a human: centered name
header, thin rules, uppercase section headings, dates right-aligned on the role
line, tight but readable spacing.

Page budget: the CV must be 1 page (2 absolute max). After rendering we count
pages (pypdf) and, if it spilled past one page, re-render once with the compact
style (smaller type/margins) before accepting the result.

WeasyPrint is imported lazily so images without the native libs (browser-worker)
can still import this module.
"""
from __future__ import annotations

import html
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Noto Sans (fonts-noto-core, in the api image) is cleaner than DejaVu; DejaVu
# stays as the fallback since it's guaranteed present.
_BASE_CSS = """
@page { size: A4; margin: %(page_margin)s; }
* { color: #1a1a1a; font-family: 'Noto Sans', 'DejaVu Sans', Arial, sans-serif; }
body { font-size: %(body_size)s; line-height: %(line_height)s; }
.name { font-size: %(name_size)s; font-weight: 700; text-align: center;
        letter-spacing: 1px; margin: 0; text-transform: uppercase; }
.contact { text-align: center; font-size: %(small_size)s; color: #3d3d3d;
           margin: 3px 0 0; }
.rule { border-bottom: 1.1pt solid #2b2b2b; margin: 7px 0 2px; }
h2 { font-size: %(h2_size)s; text-transform: uppercase; letter-spacing: 1.6px;
     color: #2b2b2b; border-bottom: 0.6pt solid #9a9a9a; padding-bottom: 2px;
     margin: %(h2_margin)s; }
p { margin: 3px 0; }
.role-line { margin: %(role_margin)s; }
.role { font-weight: 700; }
.co { color: #333; }
.dates { float: right; color: #555; font-size: %(small_size)s; }
ul { margin: 2px 0 5px 14px; padding: 0; }
li { margin-bottom: %(li_margin)s; }
.inline { margin: 2px 0; }
"""

_NORMAL = {
    "page_margin": "1.5cm 1.7cm",
    "body_size": "10pt",
    "line_height": "1.4",
    "name_size": "18pt",
    "small_size": "9pt",
    "h2_size": "10pt",
    "h2_margin": "12px 0 5px",
    "role_margin": "7px 0 1px",
    "li_margin": "2px",
}

# Compact variant used only when the normal style spills past one page.
_COMPACT = {
    "page_margin": "1.1cm 1.4cm",
    "body_size": "9.2pt",
    "line_height": "1.3",
    "name_size": "15.5pt",
    "small_size": "8.4pt",
    "h2_size": "9.2pt",
    "h2_margin": "8px 0 4px",
    "role_margin": "5px 0 1px",
    "li_margin": "1px",
}


def _css(compact: bool) -> str:
    return _BASE_CSS % (_COMPACT if compact else _NORMAL)


def _esc(s) -> str:
    return html.escape(str(s)) if s is not None else ""


def _header(contact: dict) -> list[str]:
    name = _esc(contact.get("full_name_en") or contact.get("name") or "Candidate")
    bits = [
        contact.get("email"),
        contact.get("phone"),
        contact.get("city"),
        contact.get("linkedin"),
    ]
    contact_line = "  ·  ".join(_esc(b) for b in bits if b)
    parts = [f'<p class="name">{name}</p>']
    if contact_line:
        parts.append(f'<div class="contact">{contact_line}</div>')
    parts.append('<div class="rule"></div>')
    return parts


def _wrap(body: str, compact: bool) -> str:
    return (
        f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<style>{_css(compact)}</style></head><body>{body}</body></html>"
    )


def build_html(cv: dict, contact: dict, *, compact: bool = False) -> str:
    parts = _header(contact)

    if cv.get("summary"):
        parts.append("<h2>Professional Summary</h2>")
        parts.append(f"<p>{_esc(cv['summary'])}</p>")

    if cv.get("skills"):
        parts.append("<h2>Core Skills</h2>")
        parts.append(
            f'<p class="inline">{_esc("  ·  ".join(str(s) for s in cv["skills"]))}</p>'
        )

    if cv.get("experience"):
        parts.append("<h2>Professional Experience</h2>")
        for e in cv["experience"]:
            dates = " – ".join(_esc(d) for d in (e.get("start"), e.get("end")) if d)
            line = f'<span class="role">{_esc(e.get("title"))}</span>'
            if e.get("company"):
                line += f'<span class="co"> — {_esc(e["company"])}</span>'
            if dates:
                line = f'<span class="dates">{dates}</span>' + line
            parts.append(f'<p class="role-line">{line}</p>')
            bullets = [b for b in (e.get("bullets") or []) if b]
            if bullets:
                parts.append(
                    "<ul>" + "".join(f"<li>{_esc(b)}</li>" for b in bullets) + "</ul>"
                )

    if cv.get("education"):
        parts.append("<h2>Education</h2>")
        for ed in cv["education"]:
            main = ", ".join(
                _esc(x) for x in (ed.get("degree"), ed.get("institution")) if x
            )
            if ed.get("year"):
                main += f' <span class="co">({_esc(ed["year"])})</span>'
            if main:
                parts.append(f"<p>{main}</p>")

    if cv.get("certifications"):
        parts.append("<h2>Certifications</h2>")
        parts.append(
            f'<p class="inline">'
            f'{_esc("  ·  ".join(str(c) for c in cv["certifications"]))}</p>'
        )

    return _wrap("".join(parts), compact)


def _page_count(path: str) -> int:
    try:
        from pypdf import PdfReader

        return len(PdfReader(path).pages)
    except Exception:  # noqa: BLE001 - counting is best-effort
        logger.exception("page count failed for %s", path)
        return 1


def render_cv_pdf(cv: dict, contact: dict, out_path: str) -> str:
    """Render the CV to a PDF at out_path and return the path. Targets one page:
    if the normal style spills over, re-render once in the compact style."""
    from weasyprint import HTML  # lazy: needs native libs

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    HTML(string=build_html(cv, contact)).write_pdf(out_path)
    if _page_count(out_path) > 1:
        HTML(string=build_html(cv, contact, compact=True)).write_pdf(out_path)
        logger.info(
            "CV spilled past 1 page; compact render -> %s page(s)",
            _page_count(out_path),
        )
    return out_path


def build_letter_html(letter_text: str, contact: dict) -> str:
    """The cover letter shares the CV's header so the pair looks like one
    application package; the body is the letter's paragraphs."""
    parts = _header(contact)
    for para in (letter_text or "").split("\n\n"):
        para = para.strip()
        if para:
            parts.append(
                f'<p style="margin:10px 0;">{_esc(para).replace(chr(10), "<br>")}</p>'
            )
    return _wrap("".join(parts), False)


def render_letter_pdf(letter_text: str, contact: dict, out_path: str) -> str:
    """Render the cover letter to a PDF at out_path and return the path."""
    from weasyprint import HTML  # lazy: needs native libs

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    HTML(string=build_letter_html(letter_text, contact)).write_pdf(out_path)
    return out_path
