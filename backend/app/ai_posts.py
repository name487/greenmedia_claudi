"""AI posts from the mobile app: posters from a product photo and short "viral" videos from a template, both
captioned by the AI with the brand voice, waiting for the owner's approval like every other post."""

import logging
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import ai, media, reply_keywords
from .config import settings
from .models import Client, ContentItem, ContentVariant, ProductItem

log = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Kolkata")

# Our own templates (Dhanda's meme clips can't be reused): an intro line set, colours and a camera move.
TEMPLATES = [
    {"key": "stop_scrolling", "name": "Stop Scrolling", "tagline": "A bold hook that stops the thumb", "intro": ["Stop scrolling!", "You need", "to see this"],
     "bg": "#0E1A3A", "accent": "#FFB400", "motion": "zoom"},
    {"key": "pov_found", "name": "POV: Found It", "tagline": "The relatable POV reel", "intro": ["POV:", "you found the best", "in {city}"],
     "bg": "#1B1035", "accent": "#FF5C8A", "motion": "pan"},
    {"key": "wait_for_it", "name": "Wait For It", "tagline": "Builds up, then reveals your products", "intro": ["Wait", "for", "it…"],
     "bg": "#111111", "accent": "#36D399", "motion": "zoom"},
    {"key": "deal_alert", "name": "Deal Alert", "tagline": "Loud and urgent — great for offers", "intro": ["Deal", "alert!", "Today only"],
     "bg": "#B3001B", "accent": "#FFE066", "motion": "pan"},
    {"key": "new_arrivals", "name": "New Arrivals", "tagline": "Fresh stock, quick cuts", "intro": ["Just in", "at {business}"],
     "bg": "#063B2E", "accent": "#7CF5C3", "motion": "pan"},
    {"key": "top_picks", "name": "Top Picks", "tagline": "Your bestsellers, one by one", "intro": ["Our top picks", "this week"],
     "bg": "#2A1A5E", "accent": "#C7A6FF", "motion": "zoom"},
    {"key": "made_for_you", "name": "Made For You", "tagline": "Warm and personal", "intro": ["Made", "for you", "with love"],
     "bg": "#5A2A0C", "accent": "#FFC48A", "motion": "zoom"},
    {"key": "local_favourite", "name": "Local Favourite", "tagline": "Proud local business vibe", "intro": ["{city}'s", "favourite", "{business}"],
     "bg": "#0B3D91", "accent": "#FFFFFF", "motion": "pan"},
]
TEMPLATE_BY_KEY = {t["key"]: t for t in TEMPLATES}
GEN_STEPS = [("Peeking at your photo", "Got a good look"), ("Spotting what matters", "Found the highlights"),
             ("Pulling in your details", "Details in hand"), ("Matching your style", "Style matched"), ("Bringing it to life", "Visuals ready")]

GROUP = {"generating": "pending", "in_review": "pending", "draft": "pending", "scheduled": "approved", "publishing": "approved",
         "rejected": "rejected", "published": "posted", "failed": "not_posted", "gen_failed": "not_posted"}


def _aware(dt):
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def business(c: Client) -> dict:
    contact = c.contacts[0] if c.contacts else None
    return {"name": c.company_name, "phone": contact.phone if contact else "", "address": (c.gmb.address if c.gmb else "") or c.city, "city": c.city}


def month_start() -> datetime:
    today = datetime.now(TZ).date()
    return datetime.combine(today.replace(day=1), time(), tzinfo=TZ)


def quota(db: Session, c: Client) -> dict:
    since = month_start()
    used = dict(db.execute(select(ContentItem.media_type, func.count()).where(ContentItem.client_id == c.id, ContentItem.media_type.in_(("image", "video")),
                                                                           ContentItem.created_at >= since).group_by(ContentItem.media_type)).all())
    return {"posts": {"used": used.get("image", 0), "limit": settings.ai_posts_monthly},
            "videos": {"used": used.get("video", 0), "limit": settings.viral_videos_monthly}}


def item_out(i: ProductItem) -> dict:
    return {"id": i.id, "name": i.name, "description": i.description, "price": i.price, "price_label": media.price_label(i.price) if i.price else "",
            "image_url": media.url(i.image_path), "created_at": i.created_at.isoformat() if i.created_at else None}


def post_out(item: ContentItem, kws: list[tuple[str, int]], c: Client) -> dict:
    text = f"{item.master_copy} {' '.join(item.hashtags or [])}"
    used = reply_keywords.used(text, kws, c.city, c.company_name, limit=3)
    return {
        "id": item.id, "status": item.status, "group": GROUP.get(item.status, "pending"), "topic": item.topic, "caption": item.master_copy,
        "hashtags": item.hashtags or [], "media_type": item.media_type, "image_url": item.image_url, "video_url": item.video_url,
        "template": item.template, "scheduled_at": _iso(item.scheduled_at), "published_at": _iso(item.published_at), "created_at": _iso(item.created_at),
        "updated_at": _iso(item.updated_at), "approved_at": _iso(item.approved_at),
        "generating": item.status == "generating", "gen_progress": item.gen_progress or 0, "gen_error": item.gen_error or "",
        "gen_steps": [{"doing": a, "done": b} for a, b in GEN_STEPS],
        "platforms": [{"platform": v.platform, "status": v.status, "error": v.error} for v in item.variants],
        "keywords": [{"keyword": k["keyword"], "volume": k["volume"]} for k in used],
        # a rough guide shown to owners: posts surface for a small share of the searches they match
        "estimated_views": round(sum(k["volume"] for k in used) * 0.05),
        "last_error": item.last_error or "",
    }


def _iso(dt):
    return _aware(dt).isoformat() if dt else None


def _caption(c: Client, topic: str, platforms: list[str], notes: str) -> tuple[dict, dict]:
    db = _session(c)
    kws = [k for k, _ in reply_keywords.for_clients(db, [c.id])[c.id][:3]] if db else []
    if kws:
        notes = (notes + f" Work in one or two of these search terms naturally: {'; '.join(kws)}.").strip()
    return ai.generate_content(company=c.company_name, industry=c.industry, city=c.city, website=c.website, brand_voice=c.brand_voice,
                               topic=topic, content_type="post", platforms=platforms, notes=notes)


def _session(c: Client):
    from sqlalchemy.orm import object_session
    return object_session(c)


def platforms(c: Client) -> list[str]:
    return ["gmb"] + [a.platform for a in c.social_accounts if a.platform in ("facebook", "instagram") and a.status == "connected"]


def new_post(c: Client, user_id: int, topic: str, media_type: str, products: list[ProductItem], notes: str) -> tuple[ContentItem, dict]:
    data, meta = _caption(c, topic, platforms(c), notes)
    item = ContentItem(tenant_id=c.tenant_id, client_id=c.id, topic=topic[:300], content_type="post", master_copy=data["master_copy"],
                       hashtags=data.get("hashtags", []), creative_brief=data.get("creative_brief", ""), status="in_review", created_by=user_id,
                       updated_at=datetime.now(timezone.utc), ai_source=meta["source"],
                       ai_model=f"{meta['provider']}/{meta['model']}" if meta["source"] == "ai" else "", media_type=media_type,
                       product_ids=[p.id for p in products],
                       variants=[ContentVariant(platform=v["platform"], copy=v["copy"], format="4:5" if media_type == "image" else "9:16")
                                 for v in data["variants"]])
    return item, meta


def render_job(content_id: int) -> None:
    """Render a viral video in the background, recording progress so the app can show each step."""
    from .db import SessionLocal

    with SessionLocal() as db:
        item = db.get(ContentItem, content_id)
        if not item or item.status != "generating":
            return
        c = db.get(Client, item.client_id)
        products = [p for p in db.scalars(select(ProductItem).where(ProductItem.id.in_(item.product_ids or []))) if p.image_path]

        def step(n: int) -> None:
            item.gen_progress = n
            db.commit()

        try:
            video_rel, thumb_rel = media.render_video(c.id, [p.image_path for p in products], TEMPLATE_BY_KEY[item.template], business(c), progress=step)
            item.video_url, item.image_url = media.url(video_rel), media.url(thumb_rel)
            item.status, item.gen_progress, item.updated_at = "in_review", len(GEN_STEPS), datetime.now(timezone.utc)
        except Exception as e:  # noqa: BLE001 — any failure is shown to the owner as "couldn't create the video"
            log.exception("video render failed for content %s", content_id)
            item.status, item.gen_error = "gen_failed", str(e)[:500] or e.__class__.__name__
        db.commit()


def free_slot(db: Session, c: Client, month: date | None = None) -> dict:
    """The next day (from tomorrow) with nothing scheduled or posted, at 7:00 AM India time, plus the month's busy days."""
    taken = set()
    for i in db.scalars(select(ContentItem).where(ContentItem.client_id == c.id, ContentItem.status.in_(("scheduled", "publishing", "published")),
                                         ContentItem.media_type != "text")):  # Google text posts have their own day
        when = _aware(i.published_at if i.status == "published" and i.published_at else i.scheduled_at)
        if when:
            taken.add(when.astimezone(TZ).date())
    day = datetime.now(TZ).date() + timedelta(days=1)
    while day in taken:
        day += timedelta(days=1)
    first = (month or day).replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    return {"suggested": datetime.combine(day, time(7, 0), tzinfo=TZ).isoformat(), "timezone": "Asia/Kolkata",
            "scheduled_dates": sorted(d.isoformat() for d in taken if first <= d < nxt), "month": first.isoformat()[:7]}
