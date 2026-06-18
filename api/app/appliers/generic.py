"""Generic heuristic applier: match form fields by label/name/placeholder.

Works on most static application forms. Fills text/email/tel/url inputs and
textareas whose label maps to a known answer-bank value; leaves sensitive and
unknown-but-required fields blank and reports them as missing.
"""
from __future__ import annotations

import logging
from typing import Any

from app.appliers.base import Applier, PrefillResult, is_sensitive, match_field

logger = logging.getLogger(__name__)

_FILLABLE_TYPES = {"text", "email", "tel", "url", "search", ""}


async def _label_blob(page: Any, el: Any) -> str:
    name = (await el.get_attribute("name")) or ""
    el_id = (await el.get_attribute("id")) or ""
    placeholder = (await el.get_attribute("placeholder")) or ""
    aria = (await el.get_attribute("aria-label")) or ""
    label_text = ""
    if el_id:
        try:
            lbl = await page.query_selector(f'label[for="{el_id}"]')
            if lbl:
                label_text = (await lbl.inner_text()) or ""
        except Exception:  # noqa: BLE001
            pass
    return " ".join([name, el_id, placeholder, aria, label_text]).strip()


class GenericApplier(Applier):
    name = "generic"

    async def prefill(self, page: Any, values: dict[str, str]) -> PrefillResult:
        filled: dict[str, str] = {}
        missing: list[str] = []
        try:
            elements = await page.query_selector_all(
                "input:not([type=hidden]):not([type=submit]):not([type=button])"
                ":not([type=checkbox]):not([type=radio]):not([type=file]), textarea"
            )
        except Exception:  # noqa: BLE001
            return PrefillResult(filled=filled, missing=missing)

        for el in elements:
            try:
                if not await el.is_visible():
                    continue
                typ = (await el.get_attribute("type")) or ""
                tag = (await el.evaluate("e => e.tagName")).lower()
                if tag != "textarea" and typ not in _FILLABLE_TYPES:
                    continue
                blob = await _label_blob(page, el)
                label = blob[:80] or (await el.get_attribute("name")) or "field"
                required = (
                    (await el.get_attribute("required")) is not None
                    or (await el.get_attribute("aria-required")) == "true"
                    or "*" in blob
                )

                if is_sensitive(blob):
                    missing.append(f"{label} (left blank — sensitive)")
                    continue

                key = match_field(blob)
                if key and values.get(key):
                    await el.fill(values[key])
                    filled[label] = values[key]
                elif required:
                    missing.append(label)
            except Exception:  # noqa: BLE001 - one bad field shouldn't abort
                logger.debug("field prefill skipped", exc_info=True)
        return PrefillResult(filled=filled, missing=missing)
