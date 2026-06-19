"""Oracle applier — covers both Oracle products candidates actually hit:

* **Oracle Recruiting Cloud / Candidate Experience** (`*.oraclecloud.com/hcmUI/
  CandidateExperience/...`): a modern SPA whose fields carry ARIA labels and
  predictable ids (`input-...`, `firstName`, `lastName`, `email`, `phoneNumber`).
* **Taleo** (`*.taleo.net/careersection/...`): the legacy product, which loads
  the application flow inside an iframe and uses long generated ids/names — the
  reliable hooks there are the rendered labels, so we lean on the generic label
  sweep after revealing the form.

Both require sign-in / account creation before submission, so we flag that as a
manual step and never type a password.
"""
from __future__ import annotations

from app.appliers.enterprise import EnterpriseApplier, SelectorMap


class OracleApplier(EnterpriseApplier):
    name = "oracle"

    launch_selectors = (
        # Oracle Recruiting Cloud
        'button[data-bind*="apply"]',
        'button:has-text("Apply")',
        'a:has-text("Apply")',
        'button:has-text("Apply Now")',
        # Taleo
        'a:has-text("Apply Online")',
        'a#requisitionDescriptionInterface\\.ID1559\\.row1',
        'a:has-text("Apply to job")',
    )

    # Taleo wraps the flow in a careersection iframe; ORC is inline.
    frame_hints = ("careersection", "taleo")

    field_selectors: SelectorMap = [
        (
            "first_name",
            (
                'input[name="firstName"]',
                'input#firstName',
                'input[aria-label*="First Name" i]',
                'input[name*="firstName"]',
            ),
        ),
        (
            "last_name",
            (
                'input[name="lastName"]',
                'input#lastName',
                'input[aria-label*="Last Name" i]',
                'input[name*="lastName"]',
            ),
        ),
        (
            "email",
            (
                'input[name="email"]',
                'input#email',
                'input[type="email"]',
                'input[aria-label*="Email" i]',
            ),
        ),
        (
            "phone",
            (
                'input[name="phoneNumber"]',
                'input[aria-label*="Phone" i]',
                'input[name*="phone" i]',
            ),
        ),
        (
            "city",
            (
                'input[name="city"]',
                'input[aria-label*="City" i]',
                'input[name*="city" i]',
            ),
        ),
    ]

    auth_markers = (
        "create account",
        "sign in",
        "you must sign in",
        "create a new account",
    )
