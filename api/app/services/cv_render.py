"""Render a tailored CV structure to an ATS-safe PDF (WeasyPrint).

ATS rules (CLAUDE.md §8): single column, no tables/text-boxes/headers-footers/
images, standard section headings (Experience, Education, Skills), real
selectable text. WeasyPrint is imported lazily so images without the native
libs (browser-worker) can still import this module.
"""
from __future__ import annotations

import html
from pathlib import Path

_CSS = """
@page { size: A4; margin: 1.6cm 1.8cm; }
* { font-family: 'DejaVu Sans', Arial, sans-serif; color: #111; }
body { font-size: 10.5pt; line-height: 1.35; }
h1 { font-size: 18pt; margin: 0 0 2px 0; }
.contact { font-size: 9.5pt; color: #333; margin-bottom: 10px; }
h2 { font-size: 11.5pt; text-transform: uppercase; letter-spacing: .5px;
     border-bottom: 1px solid #888; padding-bottom: 2px; margin: 14px 0 6px; }
.role { font-weight: bold; }
.muted { color: #444; }
ul { margin: 4px 0 8px 18px; padding: 0; }
li { margin-bottom: 2px; }
.skills { margin: 0; }
p { margin: 4px 0; }
"""


def _esc(s) -> str:
    return html.escape(str(s)) if s is not None else ""


def build_html(cv: dict, contact: dict) -> str:
    name = _esc(contact.get("full_name_en") or contact.get("name") or "Candidate")
    bits = [
        contact.get("email"),
        contact.get("phone"),
        contact.get("city"),
        contact.get("linkedin"),
    ]
    contact_line = " · ".join(_esc(b) for b in bits if b)

    parts: list[str] = [f"<h1>{name}</h1>"]
    if contact_line:
        parts.append(f'<div class="contact">{contact_line}</div>')

    if cv.get("summary"):
        parts.append("<h2>Summary</h2>")
        parts.append(f"<p>{_esc(cv['summary'])}</p>")

    if cv.get("skills"):
        parts.append("<h2>Skills</h2>")
        parts.append(f'<p class="skills">{_esc(", ".join(cv["skills"]))}</p>')

    if cv.get("experience"):
        parts.append("<h2>Experience</h2>")
        for e in cv["experience"]:
            dates = " – ".join(_esc(d) for d in (e.get("start"), e.get("end")) if d)
            head = f'<span class="role">{_esc(e.get("title"))}</span>'
            if e.get("company"):
                head += f' <span class="muted">— {_esc(e["company"])}</span>'
            if dates:
                head += f' <span class="muted">({dates})</span>'
            parts.append(f"<p>{head}</p>")
            bullets = [b for b in (e.get("bullets") or []) if b]
            if bullets:
                parts.append("<ul>" + "".join(f"<li>{_esc(b)}</li>" for b in bullets) + "</ul>")

    if cv.get("education"):
        parts.append("<h2>Education</h2>")
        for ed in cv["education"]:
            line = ", ".join(
                _esc(x) for x in (ed.get("degree"), ed.get("institution"), ed.get("year")) if x
            )
            if line:
                parts.append(f"<p>{line}</p>")

    if cv.get("certifications"):
        parts.append("<h2>Certifications</h2>")
        parts.append(
            "<ul>" + "".join(f"<li>{_esc(c)}</li>" for c in cv["certifications"]) + "</ul>"
        )

    return (
        f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<style>{_CSS}</style></head><body>{''.join(parts)}</body></html>"
    )


def render_cv_pdf(cv: dict, contact: dict, out_path: str) -> str:
    """Render the CV to a PDF at out_path and return the path."""
    from weasyprint import HTML  # lazy: needs native libs

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    HTML(string=build_html(cv, contact)).write_pdf(out_path)
    return out_path
