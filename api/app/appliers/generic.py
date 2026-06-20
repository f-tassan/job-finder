"""Generic heuristic applier: match form fields by label/name/placeholder.

Works on most static application forms. Fills text/email/tel/url inputs and
textareas whose label maps to a known answer-bank value; leaves sensitive and
unknown-but-required fields blank and reports them as missing.

The field sweep is factored into `_sweep(root, values)` so platform adapters can
run it against an iframe `Frame` (SuccessFactors / Taleo) instead of the top
`Page`. Both Playwright `Page` and `Frame` expose `query_selector*`, so the same
code works on either.
"""
from __future__ import annotations

import logging
from typing import Any

from app.appliers.base import Applier, PrefillResult, is_sensitive, match_field

logger = logging.getLogger(__name__)

_FILLABLE_TYPES = {"text", "email", "tel", "url", "search", ""}

# Final-submit buttons, most explicit first. Plain "Apply" is deliberately
# excluded — on many portals it only reveals the form, it doesn't submit.
_SUBMIT_SELECTORS = (
    "#submit_app",
    'button:has-text("Submit application")',
    'button:has-text("Submit Application")',
    'button:has-text("Submit your application")',
    'button[type="submit"]',
    'input[type="submit"]',
    'button:has-text("Submit")',
)


async def _label_blob(root: Any, el: Any) -> str:
    name = (await el.get_attribute("name")) or ""
    el_id = (await el.get_attribute("id")) or ""
    placeholder = (await el.get_attribute("placeholder")) or ""
    aria = (await el.get_attribute("aria-label")) or ""
    auto = (await el.get_attribute("data-automation-id")) or ""
    label_text = ""
    if el_id:
        try:
            lbl = await root.query_selector(f'label[for="{el_id}"]')
            if lbl:
                label_text = (await lbl.inner_text()) or ""
        except Exception:  # noqa: BLE001
            pass
    return " ".join([name, el_id, placeholder, aria, auto, label_text]).strip()


class GenericApplier(Applier):
    name = "generic"

    async def _sweep(
        self,
        root: Any,
        values: dict[str, str],
        already_filled: set[str] | None = None,
    ) -> PrefillResult:
        """Fill mappable text fields under `root` (a Page or Frame).

        `already_filled` holds answer-bank keys a platform adapter already placed
        via a precise selector; we don't fill them again, and we don't re-flag a
        value-less heuristic match for them as missing.
        """
        already_filled = already_filled or set()
        filled: dict[str, str] = {}
        missing: list[str] = []
        try:
            elements = await root.query_selector_all(
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
                blob = await _label_blob(root, el)
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
                if key in already_filled:
                    continue
                # Don't refill a field that already has a value (adapter or the
                # user's own browser session may have populated it).
                if key and values.get(key):
                    existing = await el.get_attribute("value")
                    if existing:
                        continue
                    await el.fill(values[key])
                    filled[label] = values[key]
                elif required:
                    missing.append(label)
            except Exception:  # noqa: BLE001 - one bad field shouldn't abort
                logger.debug("field prefill skipped", exc_info=True)
        return PrefillResult(filled=filled, missing=missing)

    async def prefill(
        self,
        page: Any,
        values: dict[str, str],
        *,
        credentials: dict[str, str] | None = None,
        save_draft: bool = False,
    ) -> PrefillResult:
        # Static forms have no account/draft concept; credentials are ignored.
        return await self._sweep(page, values)

    async def submit(self, page: Any) -> bool:
        """Click the form's final submit button. Returns True if one was clicked.
        Used ONLY by the explicit, user-confirmed auto-submit task — never by the
        normal prefill pipeline."""
        for sel in _SUBMIT_SELECTORS:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.click()
                    await page.wait_for_timeout(3000)
                    return True
            except Exception:  # noqa: BLE001
                logger.debug("submit click failed: %s", sel, exc_info=True)
        return False
