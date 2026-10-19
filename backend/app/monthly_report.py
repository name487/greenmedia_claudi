"""The owner's monthly report (app → Report, and the downloadable PDF): the month's Performance Summary against the month
before, the Growth Action Report (what was done against the targets) and the Performance Report (12-month trends with a
one-line insight each)."""

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .ai_posts import TZ
from .config import settings
from .models import Client, ContentItem, ContentVariant, GoogleMedia, MetricDaily, Review, ScoreSnapshot

PERIODS = {"last_month": 1, "3m": 3, "6m": 6, "12m": 12}


def month_start(d: date) -> date:
    return d.replace(day=1)


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 + n, 12)
    return date(y, m + 1, 1)


def month_end(d: date) -> date:
    return add_months(d, 1) - timedelta(days=1)


def label(d: date) -> str:
    return d.strftime("%b %y")  # "Sep 26", as the app shows months


def default_month(today: date | None = None) -> date:
    """The last full month (the report is about a finished month)."""
    today = today or datetime.now(TZ).date()
    return add_months(month_start(today), -1)


def _utc(d: date) -> datetime:
    return datetime.combine(d, time(), tzinfo=TZ).astimezone(timezone.utc)


def _day_of(dt: datetime | None) -> date | None:
    if dt is None:
        return None
    dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    return dt.astimezone(TZ).date()


class Data:
    """Everything counted per day once, so every chart and tile is a sum over days."""

    def __init__(self, db: Session, c: Client, start: date, end: date):
        self.metrics = {r.date: r for r in db.scalars(select(MetricDaily).where(MetricDaily.client_id == c.id, MetricDaily.date.between(start, end)))}
        lo, hi = _utc(start), _utc(end + timedelta(days=1))
        self.posts: dict[date, int] = {}
        gmb_posts = select(ContentItem.published_at).join(ContentVariant).where(
            ContentItem.client_id == c.id, ContentItem.status == "published", ContentVariant.platform == "gmb",
            ContentItem.published_at >= lo, ContentItem.published_at < hi)
        for (at,) in db.execute(gmb_posts):
            self.posts[_day_of(at)] = self.posts.get(_day_of(at), 0) + 1
        self.media: dict[date, int] = {}
        for (at,) in db.execute(select(GoogleMedia.uploaded_at).where(GoogleMedia.client_id == c.id, GoogleMedia.status == "uploaded",
                                                                       GoogleMedia.uploaded_at >= lo, GoogleMedia.uploaded_at < hi)):
            self.media[_day_of(at)] = self.media.get(_day_of(at), 0) + 1
        self.replies: dict[date, int] = {}
        for (at,) in db.execute(select(Review.published_at).where(Review.client_id == c.id, Review.reply_status == "published",
                                                                   Review.published_at >= lo, Review.published_at < hi)):
            self.replies[_day_of(at)] = self.replies.get(_day_of(at), 0) + 1
        self.scores = {s.date: s.value for s in db.scalars(select(ScoreSnapshot).where(ScoreSnapshot.client_id == c.id,
                                                                                         ScoreSnapshot.date.between(start, end)))}

    def total(self, key: str, start: date, end: date) -> int:
        days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        if key in ("posts", "media", "replies"):
            src = getattr(self, key)
            return sum(src.get(d, 0) for d in days)
        rows = [self.metrics[d] for d in days if d in self.metrics]
        if key == "engagements":
            return sum(r.gmb_calls + r.gmb_directions + r.web_clicks for r in rows)
        return sum(getattr(r, {"views": "gmb_views", "calls": "gmb_calls", "directions": "gmb_directions", "website": "web_clicks",
                               "leads": "leads"}[key]) for r in rows)

    def rate(self, start: date, end: date) -> float:
        views = self.total("views", start, end)
        return round(self.total("engagements", start, end) * 100 / views, 1) if views else 0.0

    def score(self, start: date, end: date) -> int | None:
        vals = [v for d, v in self.scores.items() if start <= d <= end]
        return round(sum(vals) / len(vals)) if vals else None


def _change(cur: float, prev: float) -> float:
    if not prev:
        return 0.0 if not cur else 100.0
    return round((cur - prev) * 100 / prev, 1)


SUMMARY = [("views", "Profile Views"), ("leads", "Leads"), ("calls", "Calls"), ("directions", "Direction Req."), ("media", "Media Uploaded"),
           ("engagement", "Engagement"), ("replies", "Review Replies"), ("posts", "Google Posts"), ("website", "Website")]

GROWTH = [("posts", "SEO Post Published", lambda: settings.weekly_post_target), ("media", "Media Uploaded", lambda: settings.weekly_media_target),
          ("replies", "Review Replies", lambda: settings.weekly_reply_target)]

TRENDS = [("score", "Growth in Score", "Marketing Score"), ("views", "Growth in Views", "Profile Views"),
          ("engagements", "Growth in Engagement", "Engagements"), ("leads", "Growth in Leads", "Leads"), ("calls", "Growth in Calls", "Calls"),
          ("directions", "Direction Requests", "Direction Requests"), ("conversion", "Views v/s Engagements Conversion", "Views vs Engagement Conversion")]


def _target(weekly: int, days: int) -> int:
    return max(1, round(weekly * days / 7))


def insight(business: str, what: str, cur: float | None, prev: float | None, month: date, unit: str = "") -> str:
    m, p = label(month), label(add_months(month, -1))
    if cur is None or prev is None:
        return f"Not enough history yet to compare {what}. It builds up month by month."
    ch = _change(cur, prev) if not unit else round(cur - prev, 1)
    amount = f"{abs(ch):g}{' points' if unit else '%'}"
    if ch <= -1:
        return f"{business} saw a {amount} drop in {what} in {m} compared to {p}, but with ongoing improvements, growth is expected in coming months."
    if ch >= 1:
        return f"{business} saw a {amount} rise in {what} in {m} compared to {p}. Great work, keep the momentum going."
    return f"{what} held steady in {m} compared to {p}. Fresh posts and photos help push it up."


def build(db: Session, c: Client, month: date) -> dict:
    month = month_start(month)
    first = add_months(month, -12)  # 12 months shown + the one before for the first comparison
    data = Data(db, c, first, month_end(month))
    prev = add_months(month, -1)

    def value(key: str, start: date, end: date):
        if key == "engagement" or key == "conversion":
            return data.rate(start, end)
        if key == "score":
            return data.score(start, end)
        return data.total(key, start, end)

    summary = []
    for key, name in SUMMARY:
        cur, before = value(key, month, month_end(month)), value(key, prev, month_end(prev))
        summary.append({"key": key, "label": name, "value": cur, "previous": before, "change_pct": _change(cur, before),
                        "unit": "%" if key == "engagement" else ""})

    growth = []
    for key, name, weekly in GROWTH:
        periods = {}
        # last month: its weeks (days 1-7, 8-14, 15-21, 22-28, 29-end)
        weeks, d = [], month
        while d <= month_end(month):
            end = min(d + timedelta(days=6), month_end(month))
            weeks.append({"label": f"W{len(weeks) + 1}", "start": d.isoformat(), "target": _target(weekly(), (end - d).days + 1),
                          "achieved": data.total(key, d, end)})
            d = end + timedelta(days=1)
        periods["last_month"] = weeks
        for p, n in PERIODS.items():
            if p == "last_month":
                continue
            periods[p] = [{"label": label(m), "start": m.isoformat(), "target": _target(weekly(), (month_end(m) - m).days + 1),
                           "achieved": data.total(key, m, month_end(m))} for m in (add_months(month, -i) for i in range(n - 1, -1, -1))]
        growth.append({"key": key, "label": name, "weekly_target": weekly(), "periods": periods})

    trends = []
    for key, name, what in TRENDS:
        points = [{"label": label(m), "month": m.isoformat()[:7], "value": value(key, m, month_end(m))} for m in (add_months(month, -i) for i in range(11, -1, -1))]
        cur, before = value(key, month, month_end(month)), value(key, prev, month_end(prev))
        unit = "%" if key == "conversion" else ""
        trends.append({"key": key, "label": name, "unit": unit, "points": points, "has_data": any(p["value"] for p in points),
                       "insight": insight(c.company_name, what, cur, before, month, unit)})

    return {"client": {"id": c.id, "company_name": c.company_name, "city": c.city}, "month": month.isoformat()[:7], "month_label": label(month),
            "previous_label": label(prev), "summary": summary, "growth": growth, "trends": trends}


def pending_counts(db: Session, c: Client) -> dict:
    """For the PDF's agent cards: what's waiting now."""
    reviews_waiting = db.scalar(select(func.count()).select_from(Review).where(Review.client_id == c.id, Review.reply_status != "published")) or 0
    media_left = db.scalar(select(func.count()).select_from(GoogleMedia).where(GoogleMedia.client_id == c.id,
                                                                              GoogleMedia.status.in_(("scheduled", "pending")))) or 0
    posts_waiting = db.scalar(select(func.count()).select_from(ContentItem).where(ContentItem.client_id == c.id, ContentItem.status == "in_review")) or 0
    return {"reviews_waiting": reviews_waiting, "media_left": media_left, "posts_waiting": posts_waiting}
