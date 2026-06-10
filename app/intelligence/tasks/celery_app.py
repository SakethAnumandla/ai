"""Celery application for async voice and receipt processing."""
from celery import Celery

from app.config import settings

celery_app = Celery(
    "expense_intelligence",
    broker=settings.celery_broker,
    backend=settings.celery_backend,
    include=[
        "app.intelligence.tasks.receipt_tasks",
        "app.intelligence.tasks.voice_tasks",
        "app.finance.tasks.report_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Limit forked workers — each child can hold DB connections to managed Postgres
    worker_concurrency=2,
)

if settings.celery_task_always_eager:
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
