"""Unit tests for the LinkedIn apply-URL resolver's pure functions."""
from __future__ import annotations

from app.services.linkedin_resolve import (
    _csrf_from_cookie,
    extract_job_id,
    is_linkedin_url,
    parse_apply_method,
)


def test_extract_job_id_from_slugged_view_url():
    url = "https://sa.linkedin.com/jobs/view/software-engineer-at-minio-4428125825"
    assert extract_job_id(url) == "4428125825"


def test_extract_job_id_from_current_job_id_param():
    url = "https://www.linkedin.com/jobs/search?currentJobId=3954321098&start=0"
    assert extract_job_id(url) == "3954321098"


def test_extract_job_id_from_external_id():
    assert extract_job_id("linkedin:4428125825") == "4428125825"


def test_extract_job_id_none_when_absent():
    assert extract_job_id("https://example.com/careers") is None
    assert extract_job_id(None) is None


def test_is_linkedin_url():
    assert is_linkedin_url("https://www.linkedin.com/jobs/view/123")
    assert is_linkedin_url("https://sa.linkedin.com/jobs/view/x-123")
    assert not is_linkedin_url("https://boards.greenhouse.io/acme/jobs/1")
    assert not is_linkedin_url(None)


def test_parse_apply_method_offsite_with_url():
    payload = {
        "applyMethod": {
            "com.linkedin.voyager.jobs.OffsiteApply": {
                "companyApplyUrl": "https://boards.greenhouse.io/acme/jobs/42",
            }
        }
    }
    assert parse_apply_method(payload) == (
        "offsite",
        "https://boards.greenhouse.io/acme/jobs/42",
    )


def test_parse_apply_method_offsite_without_url():
    payload = {"applyMethod": {"com.linkedin.voyager.jobs.OffsiteApply": {}}}
    assert parse_apply_method(payload) == ("offsite", None)


def test_parse_apply_method_easy_apply():
    payload = {
        "applyMethod": {"com.linkedin.voyager.jobs.ComplexOnsiteApply": {"x": 1}}
    }
    assert parse_apply_method(payload) == ("easyapply", None)


def test_parse_apply_method_unknown():
    assert parse_apply_method({}) == (None, None)
    assert parse_apply_method({"applyMethod": {}}) == (None, None)


def test_csrf_from_cookie():
    assert _csrf_from_cookie('li_at=AAA; JSESSIONID="ajax:123456"') == "ajax:123456"
    assert _csrf_from_cookie("JSESSIONID=ajax:789; li_at=BBB") == "ajax:789"
    assert _csrf_from_cookie("li_at=only") is None
