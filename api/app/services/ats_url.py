"""URL helpers for ATS portals (no DB/heavy imports, so freely unit-testable).

`tenant_key` reduces a job URL to the per-tenant storage key used for portal
credentials: enterprise ATS accounts are per-employer, and the employer is
identified by the URL host (e.g. `acme.wd1.myworkdayjobs.com`).
"""
from __future__ import annotations

from urllib.parse import urlparse


def tenant_key(url: str | None) -> str:
    """The per-tenant storage key for a job URL: its lowercased host, no port and
    no leading `www.` (so a login saved for `neom.com` matches `www.neom.com`)."""
    if not url:
        return ""
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    if not netloc:
        # No scheme (bare host or host/path); reparse with one.
        netloc = urlparse("//" + url).netloc.lower()
    host = netloc.split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host
