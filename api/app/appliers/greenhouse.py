"""Greenhouse applier: reveal the hosted application form, then heuristic-fill."""
from __future__ import annotations

from typing import Any

from app.appliers.base import PrefillResult
from app.appliers.generic import GenericApplier


class GreenhouseApplier(GenericApplier):
    name = "greenhouse"

    async def prefill(
        self,
        page: Any,
        values: dict[str, str],
        *,
        credentials: dict[str, str] | None = None,
        save_draft: bool = False,
    ) -> PrefillResult:
        # Some boards hide the form behind an "Apply" button; reveal it if present.
        for sel in (
            'a:has-text("Apply")',
            'button:has-text("Apply")',
            "#apply_button",
        ):
            try:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    await page.wait_for_timeout(800)
                    break
            except Exception:  # noqa: BLE001
                pass
        return await super().prefill(page, values)
