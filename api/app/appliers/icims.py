"""iCIMS applier (`*.icims.com`).

iCIMS hosts the application inside an iframe and gates it behind a candidate
account: opening a job with `mode=apply` redirects to `/login` ("returning user"
sign-in or "new user" registration). We never create an account or type a
password blind — so we reveal the form, resolve the iCIMS iframe, sign in with
the user's OWN stored iCIMS credentials if they saved any (EnterpriseApplier),
and otherwise flag the login wall as a manual step. Field names on the form are
plain (`firstname`, `lastname`, `email`, `phone`); the generic sweep handles the
long tail. Never submits.
"""
from __future__ import annotations

from app.appliers.enterprise import EnterpriseApplier, SelectorMap


class ICIMSApplier(EnterpriseApplier):
    name = "icims"

    launch_selectors = (
        'a:has-text("Apply for this job online")',
        'button:has-text("Apply for this job online")',
        'a:has-text("Apply Now")',
        'button:has-text("Apply Now")',
        'a:has-text("I\'m interested")',
        'button:has-text("I\'m interested")',
        'a:has-text("Apply")',
        'button:has-text("Apply")',
    )

    # The apply form (and the login wall) live inside the iCIMS content iframe.
    frame_hints = ("icims", "icims_content_iframe")

    # iCIMS redirects to /login and shows a "returning user" sign-in. Treat those
    # as the auth wall so we route the user to add an iCIMS account.
    auth_markers = (
        "returning user",
        "new user",
        "create a profile",
        "sign in to apply",
        "/login",
        "iframe_login",
    )

    field_selectors: SelectorMap = [
        ("first_name", ('input[name="firstname"]', 'input#firstname',
                         'input[name*="first" i]')),
        ("last_name", ('input[name="lastname"]', 'input#lastname',
                       'input[name*="last" i]')),
        ("email", ('input[name="email"]', 'input#email', 'input[type="email"]',
                   'input[name*="email" i]')),
        ("phone", ('input[name="phone"]', 'input#phone',
                   'input[name*="phone" i]', 'input[type="tel"]')),
    ]
