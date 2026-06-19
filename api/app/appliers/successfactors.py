"""SAP SuccessFactors applier (`*.successfactors.com/eu`, `*.sapsf.*`,
`jobs.sap.com`).

SuccessFactors comes in two shapes. The modern **Career Site Builder** renders
the apply form inline; the older **careersection** renders it inside an iframe.
Either way the candidate must sign in / register before the application form, and
fields are named with plain ids/names (`firstName`, `lastName`, `email`,
`cellPhone`). We resolve the iframe when present, flag the login wall, and fill
the rest by precise selector then label sweep.
"""
from __future__ import annotations

from app.appliers.enterprise import EnterpriseApplier, SelectorMap


class SuccessFactorsApplier(EnterpriseApplier):
    name = "successfactors"

    launch_selectors = (
        'button[data-tag="apply"]',
        'a[data-tag="apply"]',
        'button:has-text("Apply Now")',
        'a:has-text("Apply Now")',
        'button:has-text("Apply")',
        'a:has-text("Apply")',
        'button:has-text("Start")',
    )

    # Older careersection apply forms load inside an iframe.
    frame_hints = ("careersection", "successfactors", "sapsf", "applyiframe")

    field_selectors: SelectorMap = [
        (
            "first_name",
            (
                'input[name="firstName"]',
                'input#firstName',
                'input[name*="firstName"]',
            ),
        ),
        (
            "last_name",
            (
                'input[name="lastName"]',
                'input#lastName',
                'input[name*="lastName"]',
            ),
        ),
        (
            "email",
            (
                'input[name="email"]',
                'input#email',
                'input[type="email"]',
                'input[name*="email"]',
            ),
        ),
        (
            "phone",
            (
                'input[name="cellPhone"]',
                'input[name="phone"]',
                'input[name*="phone"]',
                'input[name*="Phone"]',
            ),
        ),
        (
            "city",
            (
                'input[name="city"]',
                'input[name*="city"]',
            ),
        ),
    ]

    auth_markers = (
        "create an account",
        "sign in to apply",
        "please sign in",
        "register to apply",
    )
