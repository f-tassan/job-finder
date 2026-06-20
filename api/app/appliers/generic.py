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

# Legacy marker that older pre-fills appended to LLM-derived values. We no longer
# write it (AI-suggested fields are tracked in a separate list), but we still
# strip it from any stored value so it can never be typed into a form.
_AI_NOTE = " — AI-suggested, verify"


def _strip_ai_note(v: str) -> str:
    """Drop a legacy trailing AI-suggested marker so an old stored value isn't
    typed verbatim into the form."""
    return v[: -len(_AI_NOTE)] if v.endswith(_AI_NOTE) else v


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


def _clean_label(*candidates: str) -> str:
    """A human-readable field name for display: the first non-empty candidate
    (label text > aria-label > placeholder > name), whitespace-collapsed, with the
    required-marker '*' dropped. Falls back to a prettified field name."""
    for cand in candidates:
        c = " ".join((cand or "").replace("*", " ").split()).strip(" :")
        if c:
            return c[:80]
    return "field"


async def _label_blob(root: Any, el: Any) -> tuple[str, str]:
    """Return (blob, label): `blob` is the raw concatenation used for matching;
    `label` is a clean display name shown to the user / used as a result key."""
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
    # Fallback for custom question widgets without a `label[for]` (e.g. Lever's
    # `cards[uuid][field0]` inputs): use the enclosing question block's text so
    # the field gets a human label instead of its raw machine name.
    if not label_text:
        try:
            anc = await el.evaluate(
                "e => { const q = e.closest("
                "'.application-question, fieldset, [data-qa=application-question]');"
                " if (!q) return '';"
                " const l = q.querySelector('.text, .application-label, legend, label');"
                " return l ? l.innerText : ''; }"
            )
            # Real question text is mixed-case/has spaces; ignore a bare tag name
            # (the unit-test fake returns e.g. "INPUT" from evaluate()).
            if anc and anc.strip() and not anc.strip().isupper():
                label_text = anc.strip()
        except Exception:  # noqa: BLE001
            pass
    blob = " ".join([name, el_id, placeholder, aria, auto, label_text]).strip()
    label = _clean_label(label_text, aria, placeholder, name.replace("_", " "))
    return blob, label


async def _react_combo_meta(root: Any, combo: Any) -> tuple[str, str]:
    """(blob, label) for a react-select combobox input. react-select gives its
    inner input an id like `react-select-<base>-input`; the visible <label> is
    `label[for="<base>"]` (Greenhouse sets <base> to the question id)."""
    cid = (await combo.get_attribute("id")) or ""
    base = cid
    if base.startswith("react-select-"):
        base = base[len("react-select-") :]
    if base.endswith("-input"):
        base = base[: -len("-input")]
    label_text = ""
    for sel in (f'label[for="{base}"]', f"#{base}-label"):
        if not base:
            break
        try:
            le = await root.query_selector(sel)
            if le:
                label_text = (await le.inner_text()) or ""
                break
        except Exception:  # noqa: BLE001
            pass
    aria = (await combo.get_attribute("aria-label")) or ""
    blob = " ".join([base, aria, label_text]).strip()
    label = _clean_label(label_text, aria, base.replace("_", " "))
    return blob, label


async def _fill_react_select(root: Any, combo: Any, value: str) -> str | None:
    """Drive a react-select combobox like a human: open it, type to filter, and
    click the best-matching option (so its hidden required input is committed —
    just setting a value the way native <select> filling does won't stick).

    Returns the chosen option text, or None if nothing matched (menu left closed).
    """
    try:
        await combo.click()
        try:
            await combo.fill(value)
        except Exception:  # noqa: BLE001 - some inputs need keystrokes
            await combo.press_sequentially(value, delay=15)
        await root.wait_for_timeout(400)
        pairs: list[tuple[str, Any]] = []
        for o in await root.query_selector_all('[role="option"]'):
            try:
                t = ((await o.inner_text()) or "").strip()
                if t:
                    pairs.append((t, o))
            except Exception:  # noqa: BLE001
                continue
        if not pairs:
            await combo.press("Escape")
            return None
        low = value.strip().lower()
        chosen = next((o for t, o in pairs if t.lower() == low), None) or next(
            (o for t, o in pairs if low and low in t.lower()), None
        )
        chosen_text: str | None = None
        if chosen is None:
            match = difflib.get_close_matches(value, [t for t, _ in pairs], n=1, cutoff=0.6)
            if match:
                chosen = next(o for t, o in pairs if t == match[0])
                chosen_text = match[0]
        else:
            chosen_text = next(t for t, o in pairs if o is chosen)
        if chosen is None:
            await combo.press("Escape")
            return None
        await chosen.click()
        await root.wait_for_timeout(150)
        return chosen_text
    except Exception:  # noqa: BLE001
        logger.debug("react-select fill skipped", exc_info=True)
        return None


class GenericApplier(Applier):
    name = "generic"

    async def _sweep(
        self,
        root: Any,
        values: dict[str, str],
        already_filled: set[str] | None = None,
        profile: dict | None = None,
        overrides: dict[str, str] | None = None,
    ) -> PrefillResult:
        """Fill mappable text fields and dropdowns under `root` (a Page or Frame).

        `already_filled` holds answer-bank keys a platform adapter already placed
        via a precise selector; we don't fill them again, and we don't re-flag a
        value-less heuristic match for them as missing.

        `profile` is the full answer bank. When given (and an LLM is configured),
        unknown required text fields and unmatched dropdowns are answered strictly
        from it — empty when not grounded — and flagged AI-suggested for the human
        to verify (CLAUDE.md: never invent; sensitive fields stay blank).

        `overrides` maps a field's display label to a human-entered value; it wins
        over every heuristic (including the sensitive-blank rule) so values the
        user completed at review — salary, "why this company" — actually land.
        """
        already_filled = already_filled or set()
        overrides = overrides or {}
        filled: dict[str, str] = {}
        missing: list[str] = []
        # Labels the LLM derived from the answer bank: values are stored clean in
        # `filled`; this list flags them "verify" for the human (never submitted
        # with any marker baked into the value).
        ai_suggested: list[str] = []
        # Unknown required fields the heuristics couldn't map, deferred to the LLM.
        # Each entry: {"id", "label", "options"?, "_el"|"_combo"}.
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
                # Skip react-select's internal inputs (the search box + the
                # hidden required mirror) — comboboxes are handled separately, and
                # typing into the filter box doesn't actually pick an option.
                el_id = (await el.get_attribute("id")) or ""
                el_name = (await el.get_attribute("name")) or ""
                if (
                    el_id.startswith("react-select-")
                    or (await el.get_attribute("role")) == "combobox"
                    or (await el.get_attribute("aria-hidden")) == "true"
                ):
                    continue
                # Never fill a honeypot — it's an invisible bot-trap; filling it
                # flags the submission as a bot (Oracle ORC ships one).
                if "honey" in f"{el_id} {el_name}".lower() or "honey" in (
                    (await el.get_attribute("aria-label")) or ""
                ).lower():
                    continue
                blob, label = await _label_blob(root, el)
                required = (
                    (await el.get_attribute("required")) is not None
                    or (await el.get_attribute("aria-required")) == "true"
                    or "*" in blob
                )

                # Human-entered review value wins over everything (even sensitive).
                ov = _strip_ai_note(overrides.get(label, "")).strip()
                if ov:
                    await el.fill(ov)
                    filled[label] = ov
                    continue

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
                blob, label = await _label_blob(root, el)
                required = (
                    (await el.get_attribute("required")) is not None
                    or (await el.get_attribute("aria-required")) == "true"
                    or "*" in blob
                )
                ov = _strip_ai_note(overrides.get(label, "")).strip()
                if ov:
                    chosen = await _select_closest(el, ov)
                    if chosen is not None:
                        filled[label] = chosen
                    else:
                        missing.append(label)
                    continue
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

        # --- react-select comboboxes (modern Greenhouse has no native <select>) -
        try:
            combos = await root.query_selector_all(
                'input[role="combobox"], input[id^="react-select-"]'
            )
        except Exception:  # noqa: BLE001
            combos = []
        for combo in combos:
            try:
                if not await combo.is_visible():
                    continue
                blob, label = await _react_combo_meta(root, combo)
                required = (
                    "*" in blob
                    or (await combo.get_attribute("aria-required")) == "true"
                    or (await combo.get_attribute("required")) is not None
                )
                ov = _strip_ai_note(overrides.get(label, "")).strip()
                if ov:
                    chosen = await _fill_react_select(root, combo, ov)
                    if chosen is not None:
                        filled[label] = chosen
                    else:
                        missing.append(label)
                    continue
                if is_sensitive(blob):
                    missing.append(f"{label} (left blank — sensitive)")
                    continue
                key = match_field(blob)
                if key in already_filled:
                    continue
                if key and values.get(key):
                    chosen = await _fill_react_select(root, combo, values[key])
                    if chosen is not None:
                        filled[label] = chosen
                    elif required:
                        missing.append(label)
                elif required:
                    if profile:
                        unanswered.append({"label": label, "_combo": combo})
                    else:
                        missing.append(label)
            except Exception:  # noqa: BLE001
                logger.debug("combobox prefill skipped", exc_info=True)

        # --- LLM fallback for the unknown required fields --------------------
        if profile and unanswered:
            await self._llm_fill(
                root, profile, unanswered, filled, missing, ai_suggested
            )

        return PrefillResult(
            filled=filled, missing=missing, ai_suggested=ai_suggested
        )

    async def _llm_fill(
        self,
        root: Any,
        profile: dict,
        unanswered: list[dict[str, Any]],
        filled: dict[str, str],
        missing: list[str],
        ai_suggested: list[str],
    ) -> None:
        """Answer unknown required fields from the answer bank via the LLM.

        Grounded answers are typed/selected (text inputs, native <select>, and
        react-select comboboxes), stored clean in `filled`, and their labels added
        to `ai_suggested` so the UI flags them "verify"; fields the LLM can't
        ground (empty answer) stay in `missing` for the human.
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
            label = f["label"]
            if not ans:
                missing.append(label)
                continue
            try:
                if f.get("_combo") is not None:
                    chosen = await _fill_react_select(root, f["_combo"], ans)
                    if chosen is None:
                        missing.append(label)
                        continue
                    filled[label] = chosen
                elif f.get("options"):
                    chosen = await _select_closest(f["_el"], ans)
                    if chosen is None:
                        missing.append(label)
                        continue
                    filled[label] = chosen
                else:
                    await f["_el"].fill(ans)
                    filled[label] = ans
                ai_suggested.append(label)
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
        overrides: dict[str, str] | None = None,
    ) -> PrefillResult:
        # Static forms have no account/draft concept; credentials are ignored.
        return await self._sweep(page, values, profile=profile, overrides=overrides)

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

    async def submit_verification_code(self, page: Any, code: str) -> bool:
        """Type an emailed one-time code into the verification field(s) and click
        submit again. Handles both N single-char boxes (Greenhouse renders
        #security-input-0..N, maxlength=1) and a single OTP input.

        Only EMPTY fields are touched — the application form is still on the page
        at this step, so we must never overwrite the already-filled name/email/
        phone. Returns True if the code was entered and submit re-clicked."""
        code = (code or "").strip()
        if not code:
            return False

        async def _empty_visible(el: Any) -> bool:
            try:
                return await el.is_visible() and not (await el.get_attribute("value"))
            except Exception:  # noqa: BLE001
                return False

        try:
            # Per-character boxes: empty, visible, single-char inputs.
            boxes = [
                el
                for el in await page.query_selector_all('input[maxlength="1"]')
                if await _empty_visible(el)
            ]
            if boxes:
                for el, ch in zip(boxes, code):  # one char per box, in order
                    await el.fill(ch)
                    await page.wait_for_timeout(40)
            else:
                # Single OTP field — try specific code selectors, empty only.
                single = None
                for sel in (
                    'input[autocomplete="one-time-code"]',
                    'input[name*="code" i]',
                    'input[id*="code" i]',
                    'input[id*="security" i]',
                    'input[inputmode="numeric"]',
                ):
                    el = await page.query_selector(sel)
                    if el and await _empty_visible(el):
                        single = el
                        break
                if single is None:
                    return False
                await single.fill(code)
            await page.wait_for_timeout(600)
            await self.submit(page)
            await page.wait_for_timeout(3000)
            return True
        except Exception:  # noqa: BLE001
            logger.debug("verification code entry failed", exc_info=True)
            return False
