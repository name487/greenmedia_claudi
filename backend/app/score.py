"""Business Score: one 0-100 number for a client's Google presence, with the parts that make it up and what to
do about each. Shown on the mobile app's home screen and in the printable report."""

import math
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .ai import pct
from .metrics import periods, series, totals
from .models import Client, Competitor, ContentItem, ContentVariant, Review, SearchKeyword

PENDING = ("new", "drafted", "approved", "failed")
REPLY_WINDOW = 50  # "Reply pending x / 50": the most recent reviews
HEATMAP_WEEKS = 15


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def label(score: int) -> str:
    return "excellent" if score >= 85 else "good" if score >= 65 else "average" if score >= 45 else "poor"


def _item(key: str, title: str, share: float, max_points: int, detail: str, tip: str) -> dict:
    share = max(0.0, min(1.0, share))
    return {"key": key, "label": title, "points": round(share * max_points), "max": max_points, "detail": detail, "tip": tip,
            "status": "good" if share >= 0.8 else "ok" if share >= 0.5 else "poor"}


def compute(c: Client, reviews: list[Review], gmb_posts_30d: int, cur: dict, keywords: list[SearchKeyword], now: datetime) -> dict:
    gmb = c.gmb
    rating = gmb.rating if gmb and gmb.rating else (round(sum(r.rating for r in reviews) / len(reviews), 1) if reviews else 0)
    total_reviews = max(gmb.review_count if gmb else 0, len(reviews))
    recent = sorted(reviews, key=lambda r: _aware(r.created_at), reverse=True)[:REPLY_WINDOW]
    replied = sum(r.reply_status == "published" for r in recent)
    fresh = sum((now - _aware(r.created_at)) <= timedelta(days=30) for r in reviews)
    views = cur["gmb_views"]
    actions = cur["gmb_calls"] + cur["gmb_directions"] + cur["web_clicks"]
    rate = actions / views if views else 0
    seen_terms = sum(not k.below_threshold for k in keywords)
    connected = bool(gmb and gmb.status == "connected")

    items = [
        _item("rating", "Google rating", (rating - 3.0) / 1.8 if rating else 0, 20, f"{rating:.1f} out of 5" if rating else "No rating yet",
              "Ask happy customers to review you — put your review QR at the counter and share it on WhatsApp."),
        _item("review_count", "Number of reviews", math.log10(total_reviews + 1) / math.log10(301), 10, f"{total_reviews} reviews",
              "Businesses with 300+ reviews win most local searches. Ask every satisfied customer."),
        _item("replies", "Replies to reviews", replied / len(recent) if recent else 1, 20,
              f"{replied} of the last {len(recent)} answered" if recent else "No reviews to answer",
              "Reply to every review, good or bad — use Reply with AI to answer in seconds."),
        _item("fresh_reviews", "New reviews (30 days)", fresh / 8, 10, f"{fresh} in the last 30 days",
              "Google favours businesses that keep getting reviews. Aim for 2 a week."),
        _item("posts", "Google posts (30 days)", gmb_posts_30d / 4, 15, f"{gmb_posts_30d} published",
              "Post an offer, update or festival greeting at least once a week, with your area and service in the caption."),
        _item("profile", "Google profile connected", (1 if not gmb.last_error else 0.5) if connected else 0, 10,
              "Connected" if connected else "Not connected", "Connect your Google Business Profile so replies and posts go live."),
        _item("search", "Search visibility", seen_terms / 10, 10, f"Found for {seen_terms} search terms",
              "Use the search terms below in your posts, services and replies to appear for more searches."),
        _item("actions", "Customer actions", rate / 0.08, 5, f"{rate * 100:.1f}% of viewers called, visited or got directions",
              "Add photos, opening hours and an offer so more viewers call or visit."),
    ]
    value = sum(i["points"] for i in items)
    return {"value": value, "label": label(value), "items": items, "rating": rating, "total_reviews": total_reviews,
            "reply_pending": sum(r.reply_status in PENDING for r in recent), "reply_window": len(recent)}


def _bucket(rows: list[dict], key) -> list[dict]:
    out: dict[str, dict] = {}
    for r in rows:
        k = key(date.fromisoformat(r["date"]))
        b = out.setdefault(k, {"start": k, "views": 0, "actions": 0})
        b["views"] += r["gmb_views"]
        b["actions"] += r["gmb_calls"] + r["gmb_directions"] + r["web_clicks"]
    return [out[k] for k in sorted(out)]


def build(db: Session, c: Client, today: date | None = None) -> dict:
    today = today or date.today()
    now = datetime.now(timezone.utc)
    (cs, ce), (ps, pe) = periods(30, today)
    cur, prev = totals(db, [c.id], cs, ce), totals(db, [c.id], ps, pe)
    reviews = list(db.scalars(select(Review).where(Review.client_id == c.id)))
    month_ago = now - timedelta(days=30)
    posts = list(db.scalars(select(ContentItem).where(ContentItem.client_id == c.id, ContentItem.status == "published")))
    gmb_posts_30d = sum(any(v.platform == "gmb" and v.status == "published" for v in p.variants) and _aware(p.published_at) >= month_ago
                        for p in posts if p.published_at)
    keywords = list(db.scalars(select(SearchKeyword).where(SearchKeyword.client_id == c.id).order_by(SearchKeyword.impressions.desc())))
    rivals = list(db.scalars(select(Competitor).where(Competitor.client_id == c.id)))
    score = compute(c, reviews, gmb_posts_30d, cur, keywords, now)

    # Activity heatmap: reviews received + replies published + posts published, Monday-first weeks
    first = today - timedelta(days=today.weekday()) - timedelta(weeks=HEATMAP_WEEKS - 1)
    days = {first + timedelta(days=i): 0 for i in range(HEATMAP_WEEKS * 7)}
    variants = db.scalars(select(ContentVariant).join(ContentItem).where(ContentItem.client_id == c.id, ContentVariant.status == "published"))
    stamps = [r.created_at for r in reviews] + [r.published_at for r in reviews if r.reply_status == "published"] + [v.published_at for v in variants]
    for ts in stamps:
        d = _aware(ts).date() if ts else None
        if d in days:
            days[d] += 1

    daily = series(db, [c.id], today - timedelta(days=179), today)
    actions = cur["gmb_calls"] + cur["gmb_directions"] + cur["web_clicks"]
    prev_actions = prev["gmb_calls"] + prev["gmb_directions"] + prev["web_clicks"]
    gmb = c.gmb
    contact = c.contacts[0] if c.contacts else None
    live = bool(keywords) and not keywords[0].is_sample
    you = {"name": c.company_name, "rating": score["rating"], "review_count": score["total_reviews"], "is_you": True,
           "address": gmb.address if gmb else "", "distance_km": 0.0}
    return {
        "client": {"id": c.id, "company_name": c.company_name, "industry": c.industry, "city": c.city,
                   "email": (gmb.google_email if gmb else "") or (contact.email if contact else ""), "phone": contact.phone if contact else "",
                   "address": gmb.address if gmb else "", "maps_uri": gmb.maps_uri if gmb else "", "review_uri": gmb.review_uri if gmb else "",
                   "google_connected": bool(gmb and gmb.status == "connected")},
        "as_of": (_aware(gmb.last_sync) if gmb and gmb.last_sync else now).isoformat(),
        "score": {"value": score["value"], "label": score["label"], "items": score["items"]},
        "stats": {"reply_pending": score["reply_pending"], "reply_window": score["reply_window"],
                  "reviews_lifetime": score["total_reviews"], "rating": score["rating"],
                  "views_30d": cur["gmb_views"], "views_change_pct": pct(cur["gmb_views"], prev["gmb_views"]),
                  "engagements_30d": actions, "engagements_change_pct": pct(actions, prev_actions),
                  "engagement_rate": round(100 * actions / cur["gmb_views"], 1) if cur["gmb_views"] else 0},
        "heatmap": {"start": first.isoformat(), "weeks": HEATMAP_WEEKS, "counts": [days[d] for d in sorted(days)],
                    "today_index": (today - first).days},
        "chart": {
            "daily": _bucket([r for r in daily if date.fromisoformat(r["date"]) > today - timedelta(days=30)], lambda d: d.isoformat()),
            "weekly": _bucket([r for r in daily if date.fromisoformat(r["date"]) > today - timedelta(weeks=12)],
                              lambda d: (d - timedelta(days=d.weekday())).isoformat()),
            # skip a first month the data only partly covers, so it doesn't read as a slump
            "monthly": _bucket([r for r in daily if not daily or daily[0]["date"].endswith("-01") or r["date"][:7] != daily[0]["date"][:7]],
                               lambda d: d.replace(day=1).isoformat())[-6:],
        },
        "keywords": {"source": "google" if live else ("sample" if keywords else "none"),
                     "period_start": keywords[0].period_start.isoformat() if keywords else None,
                     "period_end": keywords[0].period_end.isoformat() if keywords else None,
                     "items": [{"keyword": k.keyword, "impressions": k.impressions, "below_threshold": k.below_threshold} for k in keywords]},
        "competitors": sorted([you] + [{"id": x.id, "name": x.name, "rating": x.rating, "review_count": x.review_count, "maps_uri": x.maps_uri,
                                        "address": x.address, "distance_km": x.distance_km, "is_sample": x.is_sample, "is_you": False}
                                       for x in rivals],
                              key=lambda x: (-x["review_count"], -x["rating"])),
    }
