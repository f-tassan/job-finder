"""Workday applier (`*.myworkdayjobs.com`, `*.workday.com`).

Workday is a wizard: the posting shows an **Apply** button, which offers
**Autofill with Resume** / **Apply Manually** / **Use My Last Application**. We
take *Apply Manually*, which lands on a Create-Account / Sign-In screen, and only
then the multi-page **My Information** form. We never create the account or type
a password — that's flagged for the human — but every field Workday exposes is
addressable by a stable, tenant-independent `data-automation-id`, which is what
we key off of here.
"""
from __future__ import annotations

from app.appliers.enterprise import EnterpriseApplier, SelectorMap


class WorkdayApplier(EnterpriseApplier):
    name = "workday"

    launch_selectors = (
        '[data-automation-id="apply"]',
        'a[data-automation-id="adventureButton"]',
        'button[data-automation-id="adventureButton"]',
        '[data-automation-id="applyManually"]',
        'a:has-text("Apply Manually")',
        'button:has-text("Apply Manually")',
    )

    # Workday data-automation-ids are stable across tenants; match by substring.
    field_selectors: SelectorMap = [
        (
            "first_name",
            (
                '[data-automation-id="legalNameSection_firstName"]',
                'input[data-automation-id*="firstName"]',
                'input[data-automation-id*="givenName"]',
            ),
        ),
        (
            "last_name",
            (
                '[data-automation-id="legalNameSection_lastName"]',
                'input[data-automation-id*="lastName"]',
                'input[data-automation-id*="familyName"]',
            ),
        ),
        (
            "email",
            (
                'input[data-automation-id="email"]',
                'input[data-automation-id*="email"]',
            ),
        ),
        (
            "phone",
            (
                'input[data-automation-id="phone-number"]',
                'input[data-automation-id*="phoneNumber"]',
                'input[data-automation-id*="phone-number"]',
            ),
        ),
        (
            "city",
            (
                'input[data-automation-id="addressSection_city"]',
                'input[data-automation-id*="city"]',
            ),
        ),
    ]

    # Workday gates the form behind account creation; "verifyPassword" is the
    # tell-tale of the create-account screen.
    auth_markers = ("create account", "verifypassword", "sign in to apply")

    # Sign in with the user's own Workday account (per-tenant). Workday exposes
    # stable data-automation-ids for the auth screen and the save-draft button.
    signin_link_selectors = (
        '[data-automation-id="signInLink"]',
        'button:has-text("Sign In")',
        'a:has-text("Sign In")',
    )
    username_selectors = (
        'input[data-automation-id="email"]',
        'input[data-automation-id="userName"]',
        'input[type="email"]',
    )
    password_selectors = (
        'input[data-automation-id="password"]',
        'input[type="password"]',
    )
    submit_login_selectors = (
        '[data-automation-id="signInSubmitButton"]',
        'button[data-automation-id="click_filter"]',
        'button:has-text("Sign In")',
    )
    save_draft_selectors = (
        '[data-automation-id="saveForLaterButton"]',
        'button:has-text("Save for Later")',
        'button:has-text("Save")',
    )
