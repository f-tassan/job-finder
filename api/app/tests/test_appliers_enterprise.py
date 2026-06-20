"""Field-mapping tests for the enterprise ATS appliers (Workday / SAP
SuccessFactors / Oracle).

No real browser: a tiny duck-typed fake stands in for Playwright's Page / Frame /
ElementHandle. Selectors are matched by exact string against a registry the test
sets up, which is enough to exercise routing, precise-selector fills, iframe
resolution, auth-wall flagging and sensitive-field handling.
"""
from __future__ import annotations

import asyncio

import pytest

from app.appliers.base import candidate_values, get_applier
from app.appliers.oracle import OracleApplier
from app.appliers.successfactors import SuccessFactorsApplier
from app.appliers.workday import WorkdayApplier
from app.services.ats_url import tenant_key

ALL_INPUTS = (
    "input:not([type=hidden]):not([type=submit]):not([type=button])"
    ":not([type=checkbox]):not([type=radio]):not([type=file]), textarea"
)

ANSWER_BANK = {
    "full_name_en": "Faisal Al Saud",
    "email": "faisal@example.com",
    "phone": "+966500000000",
    "city": "Riyadh",
    "nationality": "Saudi",
    "linkedin": "https://linkedin.com/in/faisal",
}


class FakeEl:
    def __init__(self, attrs=None, *, tag="input", visible=True, value=""):
        self.attrs = dict(attrs or {})
        self.tag = tag
        self.visible = visible
        self.value = value
        self.clicked = False

    async def is_visible(self):
        return self.visible

    async def get_attribute(self, name):
        if name == "value":
            return self.value or None
        return self.attrs.get(name)

    async def evaluate(self, _script):
        return self.tag.upper()

    async def fill(self, value):
        self.value = value

    async def inner_text(self):
        return self.attrs.get("_text", "")

    async def click(self):
        self.clicked = True


class FakeRoot:
    """Page or Frame. `selectors` maps an exact CSS string to a single element;
    `inputs` is the list returned for the big input/textarea sweep selector."""

    def __init__(self, selectors=None, inputs=None, content="", frames=None,
                 url="", name=""):
        self.selectors = selectors or {}
        self.inputs = inputs or []
        self._content = content
        self.frames = frames if frames is not None else []
        self.url = url
        self.name = name

    async def query_selector(self, sel):
        return self.selectors.get(sel)

    async def query_selector_all(self, sel):
        if sel == ALL_INPUTS:
            return self.inputs
        el = self.selectors.get(sel)
        return [el] if el else []

    async def content(self):
        return self._content

    async def wait_for_timeout(self, _ms):
        return None


def run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# routing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "url,source,expected",
    [
        ("https://acme.wd1.myworkdayjobs.com/job/123", None, "workday"),
        (None, "workday", "workday"),
        ("https://career5.successfactors.com/career?o=1", None, "successfactors"),
        ("https://jobs.sap.com/job/123", None, "successfactors"),
        ("https://x.taleo.net/careersection/apply", None, "oracle"),
        ("https://efxx.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/job",
         None, "oracle"),
        ("https://boards.greenhouse.io/acme/jobs/1", None, "greenhouse"),
        ("https://example.com/careers/1", None, "generic"),
    ],
)
def test_routing(url, source, expected):
    assert get_applier(source, url).name == expected


# --------------------------------------------------------------------------- #
# Workday: precise data-automation-id fill + auth wall
# --------------------------------------------------------------------------- #
def test_workday_fills_by_automation_id_and_flags_account_wall():
    first = FakeEl({"data-automation-id": "legalNameSection_firstName"})
    last = FakeEl({"data-automation-id": "legalNameSection_lastName"})
    email = FakeEl({"data-automation-id": "email"})
    phone = FakeEl({"data-automation-id": "phone-number"})
    pw = FakeEl({"data-automation-id": "password"}, value="")
    apply_btn = FakeEl({"data-automation-id": "apply", "_text": "Apply"})

    selectors = {
        '[data-automation-id="apply"]': apply_btn,
        '[data-automation-id="legalNameSection_firstName"]': first,
        '[data-automation-id="legalNameSection_lastName"]': last,
        'input[data-automation-id="email"]': email,
        'input[data-automation-id="phone-number"]': phone,
        'input[type="password"], [data-automation-id="password"]': pw,
    }
    page = FakeRoot(selectors=selectors, content="Create Account to apply")

    values = candidate_values(ANSWER_BANK)
    result = run(WorkdayApplier().prefill(page, values))

    assert first.value == "Faisal"
    assert last.value == "Al Saud"
    assert email.value == "faisal@example.com"
    assert phone.value == "+966500000000"
    # account wall surfaced as the first missing item; password never filled
    assert pw.value == ""
    assert result["missing"]
    assert "Sign in" in result["missing"][0]
    assert apply_btn.clicked


def test_workday_skips_prefilled_value():
    first = FakeEl(
        {"data-automation-id": "legalNameSection_firstName"}, value="Existing"
    )
    page = FakeRoot(
        selectors={
            '[data-automation-id="legalNameSection_firstName"]': first,
        }
    )
    run(WorkdayApplier().prefill(page, candidate_values(ANSWER_BANK)))
    assert first.value == "Existing"  # not overwritten


# --------------------------------------------------------------------------- #
# SuccessFactors: form lives in a careersection iframe
# --------------------------------------------------------------------------- #
def test_successfactors_resolves_iframe_and_fills():
    first = FakeEl({"name": "firstName"})
    email = FakeEl({"name": "email", "type": "email"})
    frame = FakeRoot(
        selectors={
            'input[name="firstName"]': first,
            'input[name="email"]': email,
        },
        url="https://career.successfactors.com/careersection/apply",
        name="careersection",
    )
    page = FakeRoot(frames=[frame], content="Please sign in to apply")

    result = run(SuccessFactorsApplier().prefill(page, candidate_values(ANSWER_BANK)))

    assert first.value == "Faisal"
    assert email.value == "faisal@example.com"
    assert "Sign in" in result["missing"][0]


# --------------------------------------------------------------------------- #
# Oracle: ARIA-labelled fields + sensitive field left blank in the sweep
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://acme.wd1.myworkdayjobs.com/en-US/careers/job/9", "acme.wd1.myworkdayjobs.com"),
        ("https://X.Taleo.net:443/careersection/apply", "x.taleo.net"),
        ("acme.wd1.myworkdayjobs.com/job/1", "acme.wd1.myworkdayjobs.com"),
        ("https://www.neom.com/en-us/careers", "neom.com"),
        ("https://www.maaden.com.sa/en/careers", "maaden.com.sa"),
        ("", ""),
        (None, ""),
    ],
)
def test_tenant_key(url, expected):
    assert tenant_key(url) == expected


# --------------------------------------------------------------------------- #
# Workday: sign in with the user's own account, fill, then save a DRAFT
# --------------------------------------------------------------------------- #
def test_workday_logs_in_and_saves_draft():
    apply_btn = FakeEl({"data-automation-id": "apply", "_text": "Apply"})
    signin = FakeEl({"data-automation-id": "signInLink", "_text": "Sign In"})
    email = FakeEl({"data-automation-id": "email"})  # account email (login)
    pw = FakeEl({"data-automation-id": "password"})
    signin_submit = FakeEl({"data-automation-id": "signInSubmitButton"})
    first = FakeEl({"data-automation-id": "legalNameSection_firstName"})
    save_btn = FakeEl({"data-automation-id": "saveForLaterButton", "_text": "Save"})

    selectors = {
        '[data-automation-id="apply"]': apply_btn,
        '[data-automation-id="signInLink"]': signin,
        'input[data-automation-id="email"]': email,
        'input[data-automation-id="password"]': pw,
        '[data-automation-id="signInSubmitButton"]': signin_submit,
        '[data-automation-id="legalNameSection_firstName"]': first,
        '[data-automation-id="saveForLaterButton"]': save_btn,
        # NOTE: the auth-wall combined selector is intentionally absent → after
        # login no password field remains, so no wall is flagged.
    }
    page = FakeRoot(selectors=selectors, content="My Information")
    creds = {"username": "acct@corp.com", "password": "s3cret"}

    result = run(
        WorkdayApplier().prefill(
            page, candidate_values(ANSWER_BANK),
            credentials=creds, save_draft=True,
        )
    )

    assert email.value == "acct@corp.com"   # login filled the account email
    assert pw.value == "s3cret"             # password typed only for sign-in
    assert signin_submit.clicked
    assert first.value == "Faisal"          # form field filled after login
    assert save_btn.clicked                 # draft saved, not submitted
    assert result["logged_in"] is True
    assert result["draft_saved"] is True
    assert not result["missing"]            # no auth wall


def test_workday_without_credentials_flags_wall_and_no_draft():
    pw = FakeEl({"data-automation-id": "password"})
    page = FakeRoot(
        selectors={
            'input[type="password"], [data-automation-id="password"]': pw,
        },
        content="Create Account to apply",
    )
    result = run(WorkdayApplier().prefill(page, candidate_values(ANSWER_BANK)))
    assert pw.value == ""                    # never typed without creds
    assert result["logged_in"] is False
    assert result["draft_saved"] is False
    assert "Sign in" in result["missing"][0]


def test_oracle_fills_and_leaves_salary_blank():
    first = FakeEl({"name": "firstName"})
    salary = FakeEl(
        {"name": "expectedSalary", "aria-label": "Expected Salary", "required": ""},
        tag="input",
    )
    page = FakeRoot(
        selectors={'input[name="firstName"]': first},
        inputs=[first, salary],
        content="Sign in to continue",
    )
    result = run(OracleApplier().prefill(page, candidate_values(ANSWER_BANK)))

    assert first.value == "Faisal"
    assert salary.value == ""  # sensitive, untouched
    assert any("sensitive" in m for m in result["missing"])
