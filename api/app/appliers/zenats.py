"""ZenATS applier (`*.zenats.com` public job pages).

ZenATS renders the public posting with the application form already in the DOM
but hidden behind an "Apply" button — the generic sweep skips it because the
inputs aren't visible. So we click "Apply" to reveal the form, then hand off to
the generic label sweep (no login required for public_job pages). Never submits.
"""
from __future__ import annotations

from typing import Any

from app.appliers.base import PrefillResult
from app.appliers.generic import GenericApplier


class ZenAtsApplier(GenericApplier):
    name = "zenats"

    # Reveal buttons, broad first. ZenATS serves EN/FR/AR depending on the tenant.
    _reveal_selectors = (
        'a:has-text("Apply")',
        'button:has-text("Apply")',
        'a:has-text("Postuler")',
        'button:has-text("Postuler")',
        'a:has-text("قدم")',
        'button:has-text("قدم")',
        '[href*="apply"]',
    )

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
        for sel in self._reveal_selectors:
            try:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    await page.wait_for_timeout(1000)
                    break
            except Exception:  # noqa: BLE001
                pass
        # Let the revealed form paint before sweeping.
        await page.wait_for_timeout(600)
        return await super().prefill(
            page, values, profile=profile, overrides=overrides
        )
