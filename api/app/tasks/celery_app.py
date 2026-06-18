"""Celery application.

Phase 0 wires the broker/backend and the two queues (`default`, `browser`) so the
worker, browser-worker, and beat services start cleanly. Tasks are registered in
later phases.
"""
from __future__ import annotations

from celery import Celery

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
)

# Task modules are imported here as they are implemented (Phase 2+).
# celery_app.autodiscover_tasks(["app.tasks"])
