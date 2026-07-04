"""Recruitee applier (`*.recruitee.com/o/...` public careers pages).

Recruitee renders the apply form inline with stable `candidate.*` field names
(`candidate.name`, `candidate.email`, `candidate.phone`, `candidate.cv` file
input), but it's a JS app that paints a few seconds after load — the generic
sweep used to run too early and find nothing. We wait for the form, fill the
known fields precisely, then sweep the rest. Recruitee shows a captcha before the
final submit, so auto-submit may need the human; pre-fill always works.
"""
from __future__ import annotations

from typing import Any

from app.appliers.base import PrefillResult
from app.appliers.generic import GenericApplier


class RecruiteeApplier(GenericApplier):
    name = "recruitee"

    _known = [
        ("full_name", 'input[name="candidate.name"]'),
        ("email", 'input[name="candidate.email"]'),
        ("phone", 'input[name="candidate.phone"]'),
    ]

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
        # Wait for the SPA form to paint (the email input is a reliable signal).
        try:
            await page.wait_for_selector(
                'input[name="candidate.email"]', timeout=12000, state="visible"
            )
        except Exception:  # noqa: BLE001 - fall through to the generic wait/sweep
            pass
        filled: dict[str, str] = {}
        for key, sel in self._known:
            val = values.get(key)
            if not val:
                continue
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill(val)
                    filled[key] = val
            except Exception:  # noqa: BLE001
                pass
        result = await super().prefill(
            page, values, profile=profile, overrides=overrides
        )
        # Merge precise fills into the swept result (sweep skips already-filled).
        for k, v in filled.items():
            result.setdefault("filled", {}).setdefault(k, v)
        return result
