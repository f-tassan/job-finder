"""Celery application: broker/backend, queues, task registration, Beat schedule."""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab  # noqa: F401 (handy for future schedules)

from app.config import settings

celery_app = Celery(
    "job_finder",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_default_queue="default",
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Emit a STARTED state when a worker picks a task up, so the UI can tell
    # "queued behind a busy worker" (PENDING) apart from "actually running"
    # (STARTED) instead of showing a dead 0% for both.
    task_track_started=True,
    timezone="UTC",
    beat_schedule={
        "discovery-periodic": {
            "task": "discovery.run",
            "schedule": settings.discovery_interval_minutes * 60.0,
        },
        # Scan the IMAP inbox for "application received" confirmation emails and
        # auto-mark the matching applications as submitted. No-op unless IMAP is
        # configured in .env.
        "email-confirmations": {
            "task": "email_watch.run",
            "schedule": settings.email_watch_interval_minutes * 60.0,
        },
    },
)

# Import task modules so their @celery_app.task decorators register. Done after
# celery_app is defined to avoid a circular import.
from app.tasks import discovery, email_watch, render, tailor  # noqa: E402,F401
