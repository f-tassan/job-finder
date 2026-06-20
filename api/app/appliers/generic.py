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

import difflib
import logging
from typing import Any

from app.appliers.base import Applier, PrefillResult, is_sensitive, match_field

logger = logging.getLogger(__name__)

_FILLABLE_TYPES = {"text", "email", "tel", "url", "search", ""}

# Marker appended to answers the LLM derived from the answer bank, so the human
# reviewer knows to verify them before submitting (CLAUDE.md review-queue rule).
_AI_NOTE = " — AI-suggested, verify"


async def _select_closest(el: Any, value: str) -> str | None:
    """Pick the <option> whose text best matches `value` and select it.

    Returns the chosen option text, or None if nothing matched closely. Uses
    fuzzy string distance so "Saudi" matches "Saudi Arabia", "Saudi Arabian", etc.
    """
    try:
        options = await el.query_selector_all("option")
    except Exception:  # noqa: BLE001
        return None
    texts: list[str] = []
    for o in options:
        try:
            t = ((await o.inner_text()) or "").strip()
            # Skip placeholder rows like "Select…" / "" / "-".
            if t and t.lower() not in {"select", "select…", "select...", "-", "--"}:
                texts.append(t)
        except Exception:  # noqa: BLE001
            continue
    if not texts:
        return None
    low = value.strip().lower()
    # Prefer an exact / substring hit before falling back to fuzzy ratio.
    chosen = next(
        (t for t in texts if t.lower() == low),
        next((t for t in texts if low and low in t.lower()), None),
    )
    if chosen is None:
        match = difflib.get_close_matches(value, texts, n=1, cutoff=0.6)
        chosen = match[0] if match else None
    if chosen is None:
        return None
    try:
        await el.select_option(label=chosen)
        return chosen
    except Exception:  # noqa: BLE001
        return None

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
        profile: dict | None = None,
    ) -> PrefillResult:
        """Fill mappable text fields and dropdowns under `root` (a Page or Frame).

        `already_filled` holds answer-bank keys a platform adapter already placed
        via a precise selector; we don't fill them again, and we don't re-flag a
        value-less heuristic match for them as missing.

        `profile` is the full answer bank. When given (and an LLM is configured),
        unknown required text fields and unmatched dropdowns are answered strictly
        from it — empty when not grounded — and flagged AI-suggested for the human
        to verify (CLAUDE.md: never invent; sensitive fields stay blank).
        """
        already_filled = already_filled or set()
        filled: dict[str, str] = {}
        missing: list[str] = []
        # Unknown required fields the heuristics couldn't map, deferred to the LLM.
        # Each entry: {"id", "label", "options"?, "_el"}.
        unanswered: list[dict[str, Any]] = []
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
                    if profile:
                        unanswered.append({"label": label, "_el": el})
                    else:
                        missing.append(label)
            except Exception:  # noqa: BLE001 - one bad field shouldn't abort
                logger.debug("field prefill skipped", exc_info=True)

        # --- Dropdowns / <select> -------------------------------------------
        try:
            selects = await root.query_selector_all("select")
        except Exception:  # noqa: BLE001
            selects = []
        for el in selects:
            try:
                if not await el.is_visible():
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
                if key and values.get(key):
                    chosen = await _select_closest(el, values[key])
                    if chosen is not None:
                        filled[label] = chosen
                    elif required:
                        missing.append(label)
                elif required:
                    if profile:
                        opts = await el.query_selector_all("option")
                        choices = []
                        for o in opts:
                            t = ((await o.inner_text()) or "").strip()
                            if t:
                                choices.append(t)
                        unanswered.append(
                            {"label": label, "options": choices, "_el": el}
                        )
                    else:
                        missing.append(label)
            except Exception:  # noqa: BLE001
                logger.debug("select prefill skipped", exc_info=True)

        # --- LLM fallback for the unknown required fields --------------------
        if profile and unanswered:
            await self._llm_fill(profile, unanswered, filled, missing)

        return PrefillResult(filled=filled, missing=missing)

    async def _llm_fill(
        self,
        profile: dict,
        unanswered: list[dict[str, Any]],
        filled: dict[str, str],
        missing: list[str],
    ) -> None:
        """Answer unknown required fields from the answer bank via the LLM.

        Grounded answers are typed/selected and recorded as AI-suggested; fields
        the LLM can't ground (empty answer) stay in `missing` for the human.
        """
        from app.services import llm

        fields = [
            {
                "id": str(i),
                "label": f["label"],
                **({"options": f["options"]} if f.get("options") else {}),
            }
            for i, f in enumerate(unanswered)
        ]
        try:
            answers = await llm.answer_form_fields(profile, fields)
        except Exception:  # noqa: BLE001
            answers = {}
        for i, f in enumerate(unanswered):
            ans = answers.get(str(i), "").strip()
            el = f["_el"]
            label = f["label"]
            if not ans:
                missing.append(label)
                continue
            try:
                if f.get("options"):
                    chosen = await _select_closest(el, ans)
                    if chosen is None:
                        missing.append(label)
                        continue
                    filled[label] = chosen + _AI_NOTE
                else:
                    await el.fill(ans)
                    filled[label] = ans + _AI_NOTE
            except Exception:  # noqa: BLE001
                logger.debug("llm field fill skipped", exc_info=True)
                missing.append(label)

    async def prefill(
        self,
        page: Any,
        values: dict[str, str],
        *,
        credentials: dict[str, str] | None = None,
        save_draft: bool = False,
        profile: dict | None = None,
    ) -> PrefillResult:
        # Static forms have no account/draft concept; credentials are ignored.
        return await self._sweep(page, values, profile=profile)

    async def attach_cv(self, page: Any, cv_path: str) -> bool:
        """Attach the CV to the form's résumé file input. File inputs are usually
        hidden behind styled drag-drop zones, so we don't filter by visibility —
        set_input_files works on hidden inputs. Prefers a résumé-looking input,
        else the first file input."""
        try:
            inputs = await page.query_selector_all('input[type="file"]')
        except Exception:  # noqa: BLE001
            return False
        if not inputs:
            return False
        best = None
        for el in inputs:
            try:
                blob = " ".join(
                    [
                        (await el.get_attribute("name")) or "",
                        (await el.get_attribute("id")) or "",
                        (await el.get_attribute("aria-label")) or "",
                        (await el.get_attribute("accept")) or "",
                    ]
                ).lower()
                if any(h in blob for h in ("resume", "cv", "attachment")):
                    best = el
                    break
            except Exception:  # noqa: BLE001
                continue
        target = best or inputs[0]
        try:
            await target.set_input_files(cv_path)
            await page.wait_for_timeout(1500)
            return True
        except Exception:  # noqa: BLE001
            logger.debug("attach_cv failed", exc_info=True)
            return False

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
