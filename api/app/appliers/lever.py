"""Lever applier: navigate to the /apply form, then heuristic-fill."""
from __future__ import annotations

from typing import Any

from app.appliers.base import PrefillResult
from app.appliers.generic import GenericApplier


class LeverApplier(GenericApplier):
    name = "lever"

    async def prefill(
        self,
        page: Any,
        values: dict[str, str],
        *,
        credentials: dict[str, str] | None = None,
        save_draft: bool = False,
        profile: dict | None = None,
    ) -> PrefillResult:
        # Lever postings link to a dedicated /apply page with the form.
        try:
            url = page.url
            if "/apply" not in url:
                await page.goto(
                    url.rstrip("/") + "/apply",
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
                await page.wait_for_timeout(500)
        except Exception:  # noqa: BLE001
            pass
        return await super().prefill(page, values, profile=profile)
