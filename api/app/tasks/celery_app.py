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
    timezone="UTC",
    beat_schedule={
        "discovery-periodic": {
            "task": "discovery.run",
            "schedule": settings.discovery_interval_minutes * 60.0,
        },
    },
)

# Import task modules so their @celery_app.task decorators register. Done after
# celery_app is defined to avoid a circular import.
from app.tasks import discovery, tailor  # noqa: E402,F401
