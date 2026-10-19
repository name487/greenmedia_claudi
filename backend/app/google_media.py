"""Google Media (mobile app): photos and videos the owner adds to their Google Business Profile. Each one is uploaded on
its day by the scheduler (now, or one a day so the profile keeps getting fresh photos), only once approved."""

import logging
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from . import media
from .ai_posts import TZ, _aware, _iso
from .models import Client, GoogleMedia
from .publishers import PublishError, upload_profile_media

log = logging.getLogger(__name__)
UPLOAD_TIME = time(11, 0)  # India time, for "one a day"
MAX_ATTEMPTS = 5

# Google's photo categories (locationAssociation.category), with what to shoot for each.
CATEGORIES = [
    {"key": "EXTERIOR", "label": "Exterior Photos", "tip": "Make it easy for customers to find and recognise your business.", "icon": "storefront"},
    {"key": "INTERIOR", "label": "Interior Photos", "tip": "Show your clean, comfortable space so customers feel confident before they visit.", "icon": "chair"},
    {"key": "PRODUCT", "label": "Product Photos", "tip": "Help customers see your best items and decide what they want.", "icon": "shopping_bag"},
    {"key": "AT_WORK", "label": "Staff in Action", "tip": "Show real service in progress and make your business feel trustworthy.", "icon": "handyman"},
    {"key": "FOOD_AND_DRINK", "label": "Food and Drink", "tip": "Attract customers with your best dishes and drinks.", "icon": "restaurant"},
    {"key": "COMMON_AREA", "label": "Common Area Photo", "tip": "Show waiting, seating, or lobby areas so customers feel prepared.", "icon": "weekend"},
    {"key": "TEAMS", "label": "Team Photos", "tip": "Put faces to your name — people trust businesses they can see.", "icon": "groups"},
    {"key": "ADDITIONAL", "label": "Something Else", "tip": "Anything else that shows what makes you special — events, awards, happy customers.", "icon": "add_photo_alternate"},
]
CATEGORY = {c["key"]: c for c in CATEGORIES}
GROUP = {"pending": "scheduled", "scheduled": "scheduled", "publishing": "scheduled", "uploaded": "uploaded", "failed": "not_posted"}


def out(m: GoogleMedia) -> dict:
    return {
        "id": m.id, "kind": m.kind, "category": m.category, "category_label": CATEGORY.get(m.category, CATEGORY["ADDITIONAL"])["label"],
        "url": media.url(m.path), "thumb_url": media.url(m.thumb_path or m.path), "status": m.status, "group": GROUP.get(m.status, "scheduled"),
        "needs_approval": m.status == "pending", "scheduled_at": _iso(m.scheduled_at), "uploaded_at": _iso(m.uploaded_at),
        "created_at": _iso(m.created_at), "error": m.error,
    }


def next_days(db: Session, c: Client, n: int) -> list[datetime]:
    """n upload times, one a day from tomorrow, skipping days that already have media waiting or uploaded."""
    taken = set()
    for m in db.scalars(select(GoogleMedia).where(GoogleMedia.client_id == c.id, GoogleMedia.status != "failed")):
        when = _aware(m.uploaded_at or m.scheduled_at)
        if when:
            taken.add(when.astimezone(TZ).date())
    out, day = [], datetime.now(TZ).date() + timedelta(days=1)
    while len(out) < n:
        if day not in taken:
            out.append(datetime.combine(day, UPLOAD_TIME, tzinfo=TZ).astimezone(timezone.utc))
        day += timedelta(days=1)
    return out


def due(db: Session, now: datetime | None = None) -> list[int]:
    now = now or datetime.now(timezone.utc)
    return list(db.scalars(select(GoogleMedia.id).where(GoogleMedia.status == "scheduled", GoogleMedia.scheduled_at <= now,
                                                        GoogleMedia.approved_at.is_not(None)).order_by(GoogleMedia.scheduled_at).limit(100)))


def upload(db: Session, media_id: int) -> GoogleMedia | None:
    """Upload one due item. Only one caller wins the claim (scheduled -> publishing), so a double run can't upload twice."""
    claimed = db.execute(update(GoogleMedia).where(GoogleMedia.id == media_id, GoogleMedia.status == "scheduled",
                                                   GoogleMedia.approved_at.is_not(None)).values(status="publishing"))
    db.commit()
    if claimed.rowcount != 1:
        return None
    m = db.get(GoogleMedia, media_id)
    c = db.get(Client, m.client_id)
    try:
        m.external_name = upload_profile_media(c, media.url(m.path), m.kind == "video", m.category)
        m.status, m.uploaded_at, m.error = "uploaded", datetime.now(timezone.utc), ""
    except PublishError as e:
        m.attempts += 1
        m.error = str(e)[:500]
        if e.transient and m.attempts < MAX_ATTEMPTS:
            m.status, m.scheduled_at = "scheduled", datetime.now(timezone.utc) + timedelta(minutes=10 * m.attempts)
        else:
            m.status = "failed"
        log.warning("Google media %s upload failed: %s", m.id, e)
    db.commit()
    return m


def upload_due(db: Session) -> dict:
    """Scheduler: upload every approved photo/video whose time has come."""
    done = failed = 0
    # an upload interrupted mid-way (worker lost) isn't retried blindly — Google may have it already; a person retries
    stuck = datetime.now(timezone.utc) - timedelta(minutes=30)
    db.execute(update(GoogleMedia).where(GoogleMedia.status == "publishing", GoogleMedia.scheduled_at < stuck)
               .values(status="failed", error="The upload was interrupted — check your Google profile, then tap Retry if it's missing"))
    db.commit()
    for mid in due(db):
        m = upload(db, mid)
        if m and m.status == "uploaded":
            done += 1
        elif m and m.status == "failed":
            failed += 1
    return {"uploaded": done, "failed": failed}

