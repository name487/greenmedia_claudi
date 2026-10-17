"""Celery (Redis broker) for scheduled publishing and Google sync.

Run next to the API (same backend/.env, REDIS_URL set):

    celery -A app.celery_app worker -l info          # executes tasks
    celery -A app.celery_app beat -l info            # every minute: queue due posts; every GOOGLE_SYNC_MINUTES: sync Google
    # development shortcut: one process for both
    celery -A app.celery_app worker -B -l info

Beat doesn't hold any schedule state: the database does (content_items.scheduled_at / next_attempt_at). Rescheduling or
unscheduling is just a database update, nothing to revoke, and a Redis restart loses nothing — the next sweep re-queues
whatever is due. Duplicate deliveries are harmless because content_service.claim() lets only one worker publish a post.
"""

from celery import Celery

from .config import settings

celery = Celery("greenmedia", broker=settings.redis_url or "memory://", backend=settings.redis_url or None)
celery.conf.update(
    task_acks_late=True,  # a task lost with its worker is redelivered (claim() keeps it single-publish)
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_default_queue="greenmedia",
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    result_expires=24 * 3600,
    beat_schedule={
        "dispatch-due-content": {"task": "greenmedia.dispatch_due", "schedule": 60.0},
        "sync-google": {"task": "greenmedia.sync_google", "schedule": settings.google_sync_minutes * 60.0},
        "google-daily-posts": {"task": "greenmedia.google_posts", "schedule": 3600.0},
    },
)


def _db():
    from .db import SessionLocal
    return SessionLocal()


@celery.task(name="greenmedia.publish_content")
def publish_content(content_id: int, user_id: int | None = None) -> dict:
    from . import content_service
    from .models import User
    from .security import load_role

    with _db() as db:
        user = db.get(User, user_id) if user_id else None
        if user:
            load_role(db, user)
        return content_service.run_publish(db, content_id, user)


@celery.task(name="greenmedia.render_video")
def render_video_task(content_id: int) -> None:
    """Render an AI viral video (app → AI Post) off the web process."""
    from . import ai_posts

    ai_posts.render_job(content_id)


@celery.task(name="greenmedia.dispatch_due")
def dispatch_due() -> dict:
    """Beat, every minute: recover stuck rows and queue one publish task per due post."""
    from . import content_service

    with _db() as db:
        return content_service.publish_due(db)


@celery.task(name="greenmedia.sync_google")
def sync_google() -> dict:
    from .jobs import sync_google as run

    with _db() as db:
        return run(db)


@celery.task(name="greenmedia.google_posts")
def google_posts_task() -> dict:
    """Beat, hourly: the Content Agent writes tomorrow's Google post where daily posts are on."""
    from .jobs import google_posts as run

    with _db() as db:
        return run(db)
