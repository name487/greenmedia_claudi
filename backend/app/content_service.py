"""Content scheduling and publishing: one code path for "publish now", the Celery worker and the in-process scheduler.

Lifecycle of a content_items row:

    draft ──submit──▶ in_review ──approve──▶ scheduled ──(due)──▶ publishing ──▶ published
      ▲                    │                    │  ▲                   │
      └──request changes───┘◀────unschedule─────┘  └──temporary error──┤ (retry with backoff, up to N attempts)
                                                                       └──▶ failed (permanent error or out of attempts)

Each variant (one per platform) tracks its own status, so a retry only posts the platforms that haven't gone out.
A post is claimed with a single conditional UPDATE (scheduled → publishing) before anything is sent, so two
workers, a duplicate Celery delivery or a double click can never publish it twice.
"""

import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from .config import settings
from .models import Client, ContentItem, User
from .publishers import PublishError, publish_post
from .security import audit

log = logging.getLogger("greenmedia.content")

STUCK_AFTER = timedelta(minutes=15)  # a "publishing" row older than this belonged to a worker that died


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_utc(dt: datetime | None) -> datetime | None:
    """Store every time in UTC (SQLite keeps no offset, so a local time would be read back wrong)."""
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def schedule(item: ContentItem, when: datetime) -> None:
    item.status, item.scheduled_at = "scheduled", to_utc(when)
    item.attempts, item.next_attempt_at, item.last_error, item.updated_at = 0, None, "", utcnow()
    for v in item.variants:
        if v.status == "failed":
            v.status, v.error = "pending", ""


def due_ids(db: Session, now: datetime | None = None, limit: int = 200) -> list[int]:
    now = now or utcnow()
    when = func.coalesce(ContentItem.next_attempt_at, ContentItem.scheduled_at)
    return list(db.scalars(select(ContentItem.id).where(ContentItem.status == "scheduled", ContentItem.scheduled_at.is_not(None), when <= now)
                           .order_by(when).limit(limit)))


def recover_stuck(db: Session, now: datetime | None = None) -> int:
    """Put back rows a crashed worker left in "publishing" so the next sweep retries them (published variants are kept)."""
    now = now or utcnow()
    stuck = list(db.scalars(select(ContentItem).where(ContentItem.status == "publishing", or_(ContentItem.updated_at.is_(None), ContentItem.updated_at < now - STUCK_AFTER))))
    for item in stuck:
        item.status, item.next_attempt_at, item.updated_at = "scheduled", now, now
        audit(db, None, f"[scheduler] publish interrupted, retrying: {item.topic}", tenant_id=item.tenant_id, client_id=item.client_id,
              entity_type="content", entity_id=item.id)
    db.commit()
    return len(stuck)


def claim(db: Session, content_id: int, now: datetime | None = None) -> bool:
    """Atomically move a due, scheduled item to "publishing". Only one caller ever wins."""
    now = now or utcnow()
    res = db.execute(update(ContentItem).where(
        ContentItem.id == content_id, ContentItem.status == "scheduled", ContentItem.scheduled_at.is_not(None),
        func.coalesce(ContentItem.next_attempt_at, ContentItem.scheduled_at) <= now,
    ).values(status="publishing", updated_at=now).execution_options(synchronize_session=False))
    db.commit()
    return res.rowcount == 1


def _publish(db: Session, item: ContentItem, user: User | None) -> dict:
    """Post every variant that hasn't gone out, then settle the item's status. Caller holds the claim."""
    client = db.get(Client, item.client_id)
    now = utcnow()
    item.attempts = (item.attempts or 0) + 1
    errors, transient = [], True
    for v in item.variants:
        if v.status == "published" and v.external_post_id:
            continue
        try:
            v.external_post_id = publish_post(client, v.platform, v.copy)
            v.status, v.published_at, v.error = "published", now, ""
        except PublishError as e:
            v.status, v.error = "failed", str(e)
            errors.append(f"{v.platform}: {e}")
            transient = transient and e.transient
        except httpx.HTTPError as e:  # network trouble talking to the platform: try again later
            v.status, v.error = "failed", f"{e.__class__.__name__}: {e}"
            errors.append(f"{v.platform}: {v.error}")
    details = {"attempt": item.attempts, "variants": {v.platform: {"status": v.status, "post_id": v.external_post_id, "error": v.error or None} for v in item.variants}}
    prefix = "" if user else "[scheduler] "
    if not errors:
        item.status, item.published_at, item.last_error, item.next_attempt_at = "published", now, "", None
        verb = f"{prefix}published: {item.topic}"
    elif transient and item.attempts < settings.content_max_attempts:
        delay = timedelta(minutes=settings.content_retry_minutes * 2 ** (item.attempts - 1))
        item.status, item.last_error, item.next_attempt_at = "scheduled", "; ".join(errors), now + delay
        details["retry_at"] = item.next_attempt_at.isoformat()
        verb = f"{prefix}publish attempt {item.attempts} failed, retrying: {item.topic}"
    else:
        item.status, item.last_error, item.next_attempt_at = "failed", "; ".join(errors), None
        verb = f"{prefix}publish failed: {item.topic}"
    item.updated_at = now
    if errors:
        details["errors"] = errors
    audit(db, user, verb, tenant_id=item.tenant_id, client_id=item.client_id, entity_type="content", entity_id=item.id, details=details)
    db.commit()
    return {"id": item.id, "status": item.status, "errors": errors}


def run_publish(db: Session, content_id: int, user: User | None = None) -> dict:
    """Claim and publish one item. Safe to call any number of times (duplicates are skipped)."""
    if not claim(db, content_id):
        return {"id": content_id, "status": "skipped"}
    item = db.get(ContentItem, content_id)
    db.refresh(item)
    try:
        return _publish(db, item, user)
    except Exception:  # never leave the row stuck in "publishing"
        db.rollback()
        item = db.get(ContentItem, content_id)
        item.status, item.next_attempt_at, item.last_error = "scheduled", utcnow() + timedelta(minutes=settings.content_retry_minutes), "Unexpected error while publishing"
        db.commit()
        log.exception("publishing content %s failed", content_id)
        raise


def dispatch(db: Session, content_id: int, user: User | None = None) -> str:
    """Hand a due item to Celery when Redis is configured, otherwise publish it right here. Returns "queued" or the final status."""
    if settings.celery_enabled:
        from .celery_app import publish_content
        publish_content.delay(content_id, user.id if user else None)
        return "queued"
    return run_publish(db, content_id, user)["status"]


def publish_due(db: Session) -> dict:
    """One sweep (in-process scheduler / cron, or Celery beat → dispatch_due)."""
    recover_stuck(db)
    out = {"published": 0, "failed": 0, "retrying": 0, "queued": 0}
    for cid in due_ids(db):
        if settings.celery_enabled:
            from .celery_app import publish_content
            publish_content.delay(cid, None)
            out["queued"] += 1
            continue
        status = run_publish(db, cid)["status"]
        key = {"published": "published", "failed": "failed", "scheduled": "retrying"}.get(status)
        if key:
            out[key] += 1
    return out
