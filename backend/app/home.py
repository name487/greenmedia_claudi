"""Owner home screen pieces around the Business Score: score history, this week's marketing tracker, the Growth
Action checklist, Google performance by metric, the social calendar and Keyword Planner ideas."""

import hashlib
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .models import Client, ContentItem, Keyword, KeywordSearchLog, MetricDaily, Review, ScoreSnapshot, SearchKeyword, User

LOCAL_KM = 5.0


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def week_bounds(today: date) -> tuple[date, date]:
    start = today - timedelta(days=today.weekday())
    return start, start + timedelta(days=6)


# ---------- score history ----------

def record_snapshot(db: Session, c: Client, value: int, today: date) -> None:
    snap = db.scalar(select(ScoreSnapshot).where(ScoreSnapshot.client_id == c.id, ScoreSnapshot.date == today))
    if snap is None:
        db.add(ScoreSnapshot(tenant_id=c.tenant_id, client_id=c.id, date=today, value=value))
    else:
        snap.value = value


def history(db: Session, c: Client, today: date) -> list[dict]:
    """This week, Monday first; days still to come (or never recorded) are null."""
    start, end = week_bounds(today)
    have = {s.date: s.value for s in db.scalars(select(ScoreSnapshot).where(ScoreSnapshot.client_id == c.id, ScoreSnapshot.date.between(start, end)))}
    return [{"date": (start + timedelta(days=i)).isoformat(), "value": have.get(start + timedelta(days=i))} for i in range(7)]


# ---------- this week's tracker ----------

def tracker(db: Session, c: Client, today: date) -> dict:
    start, _ = week_bounds(today)
    since = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    items = list(db.scalars(select(ContentItem).where(ContentItem.client_id == c.id)))
    approved = sum(1 for i in items if i.approved_at and _aware(i.approved_at) >= since)
    published = sum(1 for i in items if i.status == "published" and i.published_at and _aware(i.published_at) >= since)
    replies = db.scalar(select(func.count()).select_from(Review).where(Review.client_id == c.id, Review.reply_status == "published",
                                                                      Review.published_at >= since)) or 0
    rows = [
        ("posts_approved", "AI posts approved", settings.weekly_post_target, approved, "content"),
        ("posts_published", "AI posts published", settings.weekly_post_target, published, "content"),
        ("review_replies", "Review replies", settings.weekly_reply_target, replies, "reviews"),
    ]
    tasks = [{"key": k, "label": label, "target": t, "achieved": a, "pending": max(0, t - a), "section": sec} for k, label, t, a, sec in rows]
    behind = next((t for t in tasks if t["pending"]), None)
    return {"week_start": start.isoformat(), "tasks": tasks,
            "headline": f"{behind['label']} - {behind['pending']} more to achieve the target" if behind else "All of this week's targets are done"}


# ---------- Growth Action checklist ----------

def growth_actions(c: Client, data: dict, track: dict, tracked_keywords: int) -> list[dict]:
    gmb, contact = c.gmb, (c.contacts[0] if c.contacts else None)
    social = {a.platform: a.status == "connected" for a in c.social_accounts}
    stats, task = data["stats"], {t["key"]: t for t in track["tasks"]}
    fresh = next((i for i in data["score"]["items"] if i["key"] == "fresh_reviews"), None)
    actions = [
        ("profile", "Complete your profile", "Google connected, phone and brand voice set",
         bool(gmb and gmb.status == "connected" and contact and contact.phone and (c.brand_voice or {}).get("tone")), "Complete now", "profile"),
        ("approve", "Approve posts", f"{task['posts_approved']['achieved']} of {task['posts_approved']['target']} this week",
         task["posts_approved"]["pending"] == 0, "Approve", "content"),
        ("publish", "Publish posts", f"{task['posts_published']['achieved']} of {task['posts_published']['target']} this week",
         task["posts_published"]["pending"] == 0, "Create post", "content"),
        ("reply", "Reply to every review", f"{stats['reply_pending']} waiting", stats["reply_pending"] == 0, "Reply", "reviews"),
        ("replies_week", "Review replies this week", f"{task['review_replies']['achieved']} of {task['review_replies']['target']}",
         task["review_replies"]["pending"] == 0, "Reply", "reviews"),
        ("facebook", "Connect Facebook", "Post to your Page automatically", social.get("facebook", False), "Connect", "social"),
        ("instagram", "Connect Instagram", "Post to Instagram automatically", social.get("instagram", False), "Connect", "social"),
        ("keywords", "Track your keywords", f"{tracked_keywords} of 3 added", tracked_keywords >= 3, "Add keywords", "keyword_planner"),
        ("new_reviews", "Get new Google reviews", fresh["detail"] if fresh else "", bool(fresh and fresh["status"] == "good"), "Share QR", "review_qr"),
        ("score", "Reach a score of 70", f"Now {data['score']['value']}", data["score"]["value"] >= 70, "Improve", "score"),
    ]
    return [{"key": k, "title": t, "detail": d, "done": done, "action": a, "target": tgt} for k, t, d, done, a, tgt in actions]


# ---------- Google performance ----------

PERF_METRICS = {"views": "gmb_views", "leads": "leads", "calls": "gmb_calls", "directions": "gmb_directions", "website": "web_clicks"}


def performance(db: Session, c: Client, days: int, today: date) -> dict:
    start = today - timedelta(days=days - 1)
    rows = list(db.scalars(select(MetricDaily).where(MetricDaily.client_id == c.id, MetricDaily.date.between(start, today)).order_by(MetricDaily.date)))
    series = [{"date": r.date.isoformat(), **{k: getattr(r, col) for k, col in PERF_METRICS.items()}} for r in rows]
    return {"days": days, "totals": {k: sum(s[k] for s in series) for k in PERF_METRICS}, "series": series}


# ---------- social calendar ----------

def calendar(db: Session, c: Client, month: date) -> dict:
    """Each day's most advanced post status: posted > approved > generated."""
    first = month.replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    rank = {"generated": 1, "approved": 2, "posted": 3}
    days: dict[str, str] = {}
    pending = 0
    for i in db.scalars(select(ContentItem).where(ContentItem.client_id == c.id)):
        if i.status == "in_review":
            pending += 1
        state = "posted" if i.status == "published" else "approved" if i.status in ("scheduled", "publishing") else \
            "generated" if i.status in ("draft", "in_review") else None
        when = _aware(i.published_at or i.scheduled_at or i.created_at)
        if not state or not when or not (first <= when.date() < nxt):
            continue
        key = when.date().isoformat()
        if rank[state] > rank.get(days.get(key, ""), 0):
            days[key] = state
    return {"month": first.isoformat()[:7], "pending_approval": pending, "days": days}


# ---------- competitors and social ----------

def competitor_groups(rows: list[dict]) -> dict:
    local = [r for r in rows if r.get("is_you") or (r.get("distance_km") is not None and r["distance_km"] <= LOCAL_KM)]
    return {"local": local, "surrounding": [r for r in rows if r not in local], "local_km": LOCAL_KM}


def social(c: Client) -> list[dict]:
    have = {a.platform: a for a in c.social_accounts}
    return [{"platform": p, "connected": bool(have.get(p) and have[p].status == "connected"), "status": have[p].status if p in have else "not_connected",
             "handle": have[p].handle if p in have else ""} for p in ("facebook", "instagram")]


def support(db: Session, c: Client) -> dict | None:
    am = db.get(User, c.account_manager_id) if c.account_manager_id else None
    return {"name": am.name, "phone": am.phone, "email": am.email} if am else None


# ---------- Keyword Planner ----------

MODIFIERS = ["{k}", "{k} near me", "{k} in {city}", "best {k}", "best {k} in {city}", "{k} shop", "{k} price", "{k} services",
             "{k} near me open now", "cheap {k}", "{k} store near me", "{k} contractors near me", "{k} installation", "top {k} near me",
             "{k} {city}", "{k} cost", "{k} dealers", "affordable {k} near me", "{k} reviews", "{k} companies near me"]


def _h(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)


def credits(db: Session, c: Client, today: date) -> dict:
    first = datetime.combine(today.replace(day=1), datetime.min.time(), tzinfo=timezone.utc)
    used = db.scalar(select(func.count()).select_from(KeywordSearchLog).where(KeywordSearchLog.client_id == c.id, KeywordSearchLog.created_at >= first)) or 0
    return {"used": used, "limit": settings.keyword_search_monthly_limit}


def ideas(db: Session, c: Client, seed: str, city: str) -> list[dict]:
    """Keyword ideas for a seed word. Terms Google has already shown this profile for come first with their real
    impressions (source "google"); the rest are expansions with estimated monthly searches (source "estimate")."""
    seed, city_l = seed.strip().lower(), city.strip().lower() or c.city.lower()
    out, seen = [], set()
    for k in db.scalars(select(SearchKeyword).where(SearchKeyword.client_id == c.id).order_by(SearchKeyword.impressions.desc())):
        if seed in k.keyword.lower() and k.keyword.lower() not in seen:
            seen.add(k.keyword.lower())
            out.append({"keyword": k.keyword, "searches": k.impressions, "competition": None, "source": "google"})
    base = 200 + _h(seed) % 4800
    for n, tpl in enumerate(MODIFIERS):
        kw = tpl.format(k=seed, city=city_l)
        if kw in seen:
            continue
        seen.add(kw)
        h = _h(kw)
        searches = max(10, round(base * (0.72 ** n) * (0.6 + (h % 80) / 100), -1))
        out.append({"keyword": kw, "searches": int(searches), "competition": ("low", "medium", "high")[h % 3], "source": "estimate"})
    return out


def tracked(db: Session, c: Client) -> list[dict]:
    return [{"id": k.id, "keyword": k.keyword, "location": k.location, "volume": k.volume}
            for k in db.scalars(select(Keyword).where(Keyword.client_id == c.id).order_by(Keyword.id))]
