"""IMAP connector: parse Bayt / Indeed / LinkedIn job-alert emails.

Reads recent messages from a configured inbox and extracts job links + titles.
Disabled (returns []) unless IMAP credentials are configured in settings. The
parsing is intentionally conservative — alert emails vary, so we pull anchor
links that look like job postings and use the link text as the title.
"""
from __future__ import annotations

import asyncio
import email
import imaplib
import re
from email.header import decode_header, make_header
from typing import Any

from app.config import settings
from app.connectors.base import Connector

# Links that typically point at an individual posting on the major alert sources.
_JOB_LINK_RE = re.compile(
    r'<a[^>]+href="([^"]*(?:/job/|/jobs/|/viewjob|/jobs/view/|jobId=)[^"]*)"[^>]*>'
    r"(.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")


class EmailAlertsConnector(Connector):
    name = "email_alerts"

    async def fetch(self, query: str | None, filters: dict[str, Any]) -> list[dict]:
        if not (settings.imap_host and settings.imap_user and settings.imap_password):
            return []
        limit = int(filters.get("limit", 30))
        return await asyncio.to_thread(self._fetch_sync, limit)

    def _fetch_sync(self, limit: int) -> list[dict]:
        jobs: list[dict] = []
        seen: set[str] = set()
        conn = imaplib.IMAP4_SSL(settings.imap_host)  # type: ignore[arg-type]
        try:
            conn.login(settings.imap_user, settings.imap_password)  # type: ignore[arg-type]
            conn.select(settings.imap_folder)
            typ, data = conn.search(None, "ALL")
            if typ != "OK":
                return []
            ids = data[0].split()[-limit:]
            for mid in reversed(ids):
                typ, msg_data = conn.fetch(mid, "(RFC822)")
                if typ != "OK" or not msg_data or not msg_data[0]:
                    continue
                msg = email.message_from_bytes(msg_data[0][1])
                html = self._html_body(msg)
                for url, raw_text in _JOB_LINK_RE.findall(html or ""):
                    title = _TAG_RE.sub("", raw_text).strip()
                    if not title or url in seen:
                        continue
                    seen.add(url)
                    jobs.append(
                        {
                            "source": self.name,
                            "external_id": url[:500],
                            "title": title[:300],
                            "company": None,
                            "location": None,
                            "url": url,
                            "description": None,
                            "posted_at": None,
                            "raw": {"subject": str(make_header(decode_header(
                                msg.get("Subject", "")))) },
                        }
                    )
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass
        return jobs

    @staticmethod
    def _html_body(msg: email.message.Message) -> str | None:
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode(errors="ignore")
            return None
        payload = msg.get_payload(decode=True)
        return payload.decode(errors="ignore") if payload else None
