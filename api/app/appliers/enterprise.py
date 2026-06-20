"""Shared machinery for the big enterprise ATS adapters (Workday, SAP
SuccessFactors, Oracle Recruiting / Taleo).

These platforms are JS single-page apps that hide the application form behind a
chain of buttons ("Apply" → "Apply Manually"), often render it inside an iframe,
and gate it behind a create-account / sign-in wall. None of them let us submit
on the user's behalf (CLAUDE.md hard rule) and none should auto-create an
account or type a password. So every adapter here does the same shape of work:

  1. Reveal the form (click through the launch buttons).
  2. Resolve the form root (the Page, or the careersection iframe Frame).
  3. Detect a login / create-account wall and, if present, surface it as a
     *manual* missing step instead of trying to break through it.
  4. Fill the fields it can map precisely, then hand off to the generic label
     sweep for the long tail.

Playwright is never imported here — adapters receive a `page` and only touch the
duck-typed `Page`/`Frame`/`ElementHandle` surface, so non-browser images can
import this module.
"""
from __future__ import annotations

import logging
from typing import Any

from app.appliers.base import PrefillResult
from app.appliers.generic import GenericApplier

logger = logging.getLogger(__name__)

# Field key -> CSS selectors that locate it on enterprise forms, broad first.
# `data-automation-id*=` matches Workday's stable tenant-independent ids.
SelectorMap = list[tuple[str, tuple[str, ...]]]


def merge_results(*results: PrefillResult) -> PrefillResult:
    filled: dict[str, str] = {}
    missing: list[str] = []
    for r in results:
        filled.update(r.get("filled", {}))
        for m in r.get("missing", []):
            if m not in missing:
                missing.append(m)
    return PrefillResult(filled=filled, missing=missing)


class EnterpriseApplier(GenericApplier):
    """Base for Workday/SuccessFactors/Oracle: reveal → resolve root → guard →
    precise fill → generic sweep. Subclasses set the platform specifics."""

    # Buttons to click (in order, best-effort) to expose the real form.
    launch_selectors: tuple[str, ...] = ()
    # Precise selectors per answer-bank key, tried in order.
    field_selectors: SelectorMap = []
    # Substrings in the page text/URL that mean "you must log in / create an
    # account before the form" — we never type a password, so flag it.
    auth_markers: tuple[str, ...] = ()
    # iframe url/name hints; if any matches, the form lives in that frame.
    frame_hints: tuple[str, ...] = ()

    # --- sign-in (uses the user's OWN stored account; never creates one) ---
    # Link/tab to switch from "create account" to the sign-in form.
    signin_link_selectors: tuple[str, ...] = (
        'a:has-text("Sign In")',
        'button:has-text("Sign In")',
        'a:has-text("Log In")',
        'button:has-text("Log In")',
    )
    username_selectors: tuple[str, ...] = (
        'input[type="email"]',
        'input[name="username"]',
        'input[name="user"]',
        'input[id*="user" i]',
    )
    password_selectors: tuple[str, ...] = ('input[type="password"]',)
    submit_login_selectors: tuple[str, ...] = (
        'button[type="submit"]',
        'button:has-text("Sign In")',
        'button:has-text("Log In")',
    )
    # Save-a-draft buttons (NOT submit). Order: most explicit first.
    save_draft_selectors: tuple[str, ...] = (
        'button:has-text("Save and continue later")',
        'a:has-text("Save and continue later")',
        'button:has-text("Save Draft")',
        'button:has-text("Save for Later")',
        'button:has-text("Save")',
    )

    async def _click_first(
        self,
        page: Any,
        selectors: tuple[str, ...],
        *,
        settle_ms: int = 1200,
    ) -> str | None:
        """Click the first visible, enabled match; return its selector or None."""
        for sel in selectors:
            try:
                el = await page.query_selector(sel)
                if not el or not await el.is_visible():
                    continue
                if (await el.get_attribute("disabled")) is not None:
                    continue
                await el.click()
                await page.wait_for_timeout(settle_ms)
                return sel
            except Exception:  # noqa: BLE001
                logger.debug("launch click failed: %s", sel, exc_info=True)
        return None

    async def _fill_first(
        self, root: Any, selectors: tuple[str, ...], value: str
    ) -> bool:
        for sel in selectors:
            try:
                el = await root.query_selector(sel)
                if not el or not await el.is_visible():
                    continue
                await el.fill(value)
                return True
            except Exception:  # noqa: BLE001
                logger.debug("fill_first failed: %s", sel, exc_info=True)
        return False

    async def reveal(self, page: Any) -> None:
        """Walk the launch-button chain to expose the form. Buttons may appear in
        sequence (Apply, then Apply Manually), so try each up to twice."""
        for _ in range(2):
            clicked = await self._click_first(page, self.launch_selectors)
            if not clicked:
                break

    async def form_root(self, page: Any) -> Any:
        """Return the Frame that holds the form, or the page if it's inline."""
        if not self.frame_hints:
            return page
        try:
            for frame in page.frames:
                ident = f"{getattr(frame, 'url', '')} {getattr(frame, 'name', '')}"
                if any(h in ident.lower() for h in self.frame_hints):
                    return frame
        except Exception:  # noqa: BLE001
            logger.debug("frame resolution failed", exc_info=True)
        return page

    async def auth_wall(self, page: Any, root: Any) -> str | None:
        """If the form is gated behind sign-in / create-account, return a human
        instruction string (so the user does it in their own browser). We fill an
        email if there's an obvious field but never a password."""
        try:
            has_pw = await root.query_selector(
                'input[type="password"], [data-automation-id="password"]'
            )
        except Exception:  # noqa: BLE001
            has_pw = None
        text_marker = False
        if self.auth_markers:
            try:
                body = (await page.content()) or ""
                low = body.lower()
                text_marker = any(m in low for m in self.auth_markers)
            except Exception:  # noqa: BLE001
                text_marker = False
        if has_pw or text_marker:
            return (
                "Sign in / create an account on the employer site to reach the "
                "application form (do this in your own browser — passwords are "
                "never auto-filled)."
            )
        return None

    async def fill_known(
        self, root: Any, values: dict[str, str]
    ) -> tuple[PrefillResult, set[str]]:
        """Fill fields via the platform's precise selectors. Returns the result
        plus the set of answer-bank keys that were filled (so the generic sweep
        can skip them)."""
        filled: dict[str, str] = {}
        done: set[str] = set()
        for key, selectors in self.field_selectors:
            val = values.get(key)
            if not val or key in done:
                continue
            for sel in selectors:
                try:
                    el = await root.query_selector(sel)
                    if not el or not await el.is_visible():
                        continue
                    if (await el.get_attribute("value")):
                        done.add(key)
                        break
                    await el.fill(val)
                    label = (await el.get_attribute("data-automation-id")) or (
                        await el.get_attribute("name")
                    ) or sel
                    filled[label] = val
                    done.add(key)
                    break
                except Exception:  # noqa: BLE001
                    logger.debug("known-field fill failed: %s", sel, exc_info=True)
        return PrefillResult(filled=filled, missing=[]), done

    async def login(self, root: Any, page: Any, creds: dict[str, str]) -> bool:
        """Sign in with the user's own stored account. Returns True if both
        fields were filled and the sign-in button clicked. Never registers."""
        user = (creds or {}).get("username")
        pw = (creds or {}).get("password")
        if not user or not pw:
            return False
        # Some screens default to "Create Account"; flip to the sign-in form.
        await self._click_first(page, self.signin_link_selectors, settle_ms=600)
        ok_user = await self._fill_first(root, self.username_selectors, user)
        ok_pw = await self._fill_first(root, self.password_selectors, pw)
        if not (ok_user and ok_pw):
            return False
        clicked = await self._click_first(root, self.submit_login_selectors)
        if not clicked:
            clicked = await self._click_first(page, self.submit_login_selectors)
        await page.wait_for_timeout(1500)
        return bool(clicked)

    async def save_draft(self, root: Any, page: Any) -> bool:
        """Click a Save-as-draft button (never Submit). Returns True if one was
        clicked — the draft then persists on the employer portal under the
        user's account for them to review and submit."""
        clicked = await self._click_first(root, self.save_draft_selectors)
        if not clicked:
            clicked = await self._click_first(page, self.save_draft_selectors)
        if clicked:
            await page.wait_for_timeout(1500)
        return bool(clicked)

    async def prefill(
        self,
        page: Any,
        values: dict[str, str],
        *,
        credentials: dict[str, str] | None = None,
        save_draft: bool = False,
    ) -> PrefillResult:
        try:
            await self.reveal(page)
        except Exception:  # noqa: BLE001
            logger.debug("reveal failed", exc_info=True)

        root = await self.form_root(page)

        logged_in = False
        if credentials:
            try:
                logged_in = await self.login(root, page, credentials)
            except Exception:  # noqa: BLE001
                logger.debug("login failed", exc_info=True)
            # Login usually navigates to the form; re-resolve the root.
            root = await self.form_root(page)

        wall = await self.auth_wall(page, root)

        known, done = await self.fill_known(root, values)
        sweep = await self._sweep(root, values, already_filled=done)
        result = merge_results(known, sweep)

        draft_saved = False
        if save_draft and credentials and logged_in and not wall:
            try:
                draft_saved = await self.save_draft(root, page)
            except Exception:  # noqa: BLE001
                logger.debug("save_draft failed", exc_info=True)

        if wall:
            result["missing"].insert(0, wall)
        result["logged_in"] = logged_in
        result["draft_saved"] = draft_saved
        # A wall that's still standing means we couldn't reach the form: either no
        # credential was stored, or the stored one failed to sign in.
        result["needs_credentials"] = bool(wall)
        return result
