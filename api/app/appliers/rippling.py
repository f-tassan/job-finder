"""Rippling ATS applier (`ats.rippling.com/<org>/jobs/...`).

Rippling shows the posting first and hides the application form behind an "Apply
now" button; only after clicking it does the form (name/email/phone/résumé)
render. We click through, wait for the form, then hand off to the generic sweep.
No login required for these public job pages. Never submits.
"""
from __future__ import annotations

from typing import Any

from app.appliers.base import PrefillResult
from app.appliers.generic import GenericApplier


class RipplingApplier(GenericApplier):
    name = "rippling"

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
        for sel in (
            'button:has-text("Apply now")',
            'a:has-text("Apply now")',
            'button:has-text("Apply")',
            'a:has-text("Apply")',
        ):
            try:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    await page.wait_for_timeout(1200)
                    break
            except Exception:  # noqa: BLE001
                pass
        # The generic _wait_for_form (called inside super().prefill) waits for the
        # revealed inputs to paint before sweeping.
        return await super().prefill(
            page, values, profile=profile, overrides=overrides
        )
