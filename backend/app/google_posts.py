"""Google Post (mobile app): the Content Agent writes one text-only Google Business Profile update a day, each built
around one of the business's search keywords (Keyword Planner), so the profile keeps matching those searches.

Every post waits for the owner's approval, unless the owner turns on "Post automatically" — a standing approval recorded
as approval_rule = "auto_google_post" with the person who turned it on, like auto-publish for review replies."""

import logging
import re
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import ai, content_service, reply_keywords
from .ai_posts import TZ, GROUP, _aware, _iso
from .models import Client, ContentItem, ContentVariant, User

log = logging.getLogger(__name__)
RULE = "auto_google_post"
DEFAULT_TIME = "10:00"
GOOGLE_LIMIT = 1500

# A different angle each day so a week of posts doesn't read the same.
ANGLES = [
    ("tip", "a short, useful tip a customer searching for this would value"),
    ("why_us", "why local customers choose this business for this"),
    ("faq", "a question people often ask about this, answered simply"),
    ("offer", "a gentle reminder of the service with a clear call to action (no invented prices or discounts)"),
    ("story", "what a visit looks like, step by step, so a first-timer feels at ease"),
    ("local", "how the business serves people in its city and nearby areas"),
    ("seasonal", "a timely, seasonal reason to visit (festivals, weather, the season) without inventing events"),
]
# Used when the AI isn't available. Search phrases ("dental clinic near me") rarely fit a sentence, so they're quoted.
TEMPLATES = {
    "tip": 'Searching for "{kw}"? A quick tip from {company}: tell us what you need before you visit and we\'ll plan it around you. {cta} today.',
    "why_us": 'If you\'ve searched "{kw}", here\'s why people in {city} choose {company}: friendly experts, honest advice and care that fits your needs. {cta}.',
    "faq": 'A question we hear a lot: where to go for "{kw}" in {city}? Right here at {company}. Drop by or call — we\'ll help you choose. {cta}.',
    "offer": '"{kw}" — that\'s what {company} in {city} does every day. Visit us this week and see why our customers keep coming back. {cta} now.',
    "story": 'New to "{kw}"? At {company} we keep it simple: tell us what you need, we explain your options, and you decide. {cta}.',
    "local": 'Proudly serving {city} and nearby areas — if you\'re looking for "{kw}", {company} is just around the corner. {cta} today.',
    "seasonal": 'This season is a great time to look into "{kw}". {company} in {city} is ready to help. {cta} and plan your visit.',
}


def settings_of(c: Client) -> dict:
    s = c.google_posts or {}
    return {"daily": s.get("daily", True), "auto": bool(s.get("auto")), "auto_by": s.get("auto_by"), "time": s.get("time") or DEFAULT_TIME}


def _hm(s: dict) -> time:
    h, m = (int(x) for x in s["time"].split(":"))
    return time(h, m)


def keywords(db: Session, c: Client) -> list[tuple[str, int]]:
    return reply_keywords.for_clients(db, [c.id])[c.id]


def _is_brand(keyword: str, c: Client) -> bool:
    """Searches for the business's own name: nothing to write a post around."""
    brand = set(re.findall(r"\w+", c.company_name.lower()))
    return set(re.findall(r"\w+", keyword.lower())) <= brand


def text_posts(db: Session, c: Client) -> list[ContentItem]:
    return list(db.scalars(select(ContentItem).where(ContentItem.client_id == c.id, ContentItem.media_type == "text")))


def day_of(item: ContentItem) -> date | None:
    when = _aware(item.published_at if item.status == "published" and item.published_at else item.scheduled_at)
    return when.astimezone(TZ).date() if when else None


def next_keyword(db: Session, c: Client) -> tuple[str, int] | None:
    """The keyword written about least in the last 30 days; ties go to the bigger search volume."""
    kws = [kv for kv in keywords(db, c) if not _is_brand(kv[0], c)]
    if not kws:
        return None
    since = datetime.now(timezone.utc) - timedelta(days=30)
    uses: dict[str, int] = {}
    for i in text_posts(db, c):
        if i.status != "rejected" and _aware(i.created_at or since) >= since:
            uses[i.target_keyword.lower()] = uses.get(i.target_keyword.lower(), 0) + 1
    order = {k: n for n, (k, _) in enumerate(kws)}
    return min(kws, key=lambda kv: (uses.get(kv[0], 0), order[kv[0]]))


def next_free_day(db: Session, c: Client) -> date:
    """Tomorrow, or the first day after it without a Google post (rejected ones free their day)."""
    taken = {day_of(i) for i in text_posts(db, c) if i.status not in ("rejected", "failed")}
    day = datetime.now(TZ).date() + timedelta(days=1)
    while day in taken:
        day += timedelta(days=1)
    return day


def _clean(text: str) -> str:
    text = re.sub(r"(?<!\w)#\w+", "", text or "")  # Google posts don't use hashtags
    return re.sub(r"[ \t]{2,}", " ", text).strip()[:GOOGLE_LIMIT]


def write(c: Client, keyword: str, angle: tuple[str, str]) -> tuple[str, dict]:
    notes = (f"This is a text-only Google Business Profile update (no image, no hashtags, under 900 characters). Angle: {angle[1]}. "
             f'Use the search term "{keyword}" naturally in the first sentence, mention {c.city or "the city"} once, '
             "end with a clear call to action. Don't invent prices, offers or awards.")
    data, meta = ai.generate_content(company=c.company_name, industry=c.industry, city=c.city, website=c.website, brand_voice=c.brand_voice,
                                     topic=keyword, content_type="post", platforms=["gmb"], notes=notes)
    if meta["source"] == "ai":
        gmb = next((v["copy"] for v in data["variants"] if v["platform"] == "gmb"), data["master_copy"])
        return _clean(gmb), meta
    cta = (c.brand_voice or {}).get("cta_style") or "Call us"
    text = TEMPLATES[angle[0]].format(kw=keyword, company=c.company_name, city=c.city or "your area", cta=cta)
    return _clean(text), meta


def draft(db: Session, c: Client, user_id: int | None, day: date | None = None, keyword: str | None = None) -> ContentItem:
    """Write the post for `day` (default: the next free day) at the client's posting time. With "Post automatically"
    on, it is approved under that standing approval and scheduled; otherwise it waits for approval."""
    s = settings_of(c)
    if keyword:
        kv = (keyword.strip(), dict(keywords(db, c)).get(keyword.strip().lower(), 0))
    else:
        kv = next_keyword(db, c)
    if not kv:
        raise ValueError("Add your keywords in the Keyword Planner first — Google posts are written around them")
    day = day or next_free_day(db, c)
    angle = ANGLES[day.toordinal() % len(ANGLES)]
    text, meta = write(c, kv[0], angle)
    when = datetime.combine(day, _hm(s), tzinfo=TZ).astimezone(timezone.utc)
    item = ContentItem(tenant_id=c.tenant_id, client_id=c.id, topic=f"Google post: {kv[0]}", content_type="post", master_copy=text, hashtags=[],
                       status="in_review", created_by=user_id, updated_at=datetime.now(timezone.utc), ai_source=meta["source"],
                       ai_model=f"{meta['provider']}/{meta['model']}" if meta["source"] == "ai" else "", media_type="text", target_keyword=kv[0],
                       template=angle[0], scheduled_at=when, variants=[ContentVariant(platform="gmb", copy=text, format="text")])
    db.add(item)
    db.flush()
    approver = _auto_approver(db, c)
    if approver:
        content_service.schedule(item, max(when, datetime.now(timezone.utc) + timedelta(minutes=5)))
        item.approved_by, item.approved_at, item.approval_rule = approver.id, datetime.now(timezone.utc), RULE
    return item


def _auto_approver(db: Session, c: Client) -> User | None:
    """The person whose standing approval covers automatic posting, while they still may approve for this business."""
    s = settings_of(c)
    if not (s["auto"] and s["auto_by"]):
        return None
    from .routers.content import can_approve
    from .security import load_role

    u = db.get(User, s["auto_by"])
    if not u or u.status != "active" or u.tenant_id != c.tenant_id or (u.client_id and u.client_id != c.id):
        return None
    load_role(db, u)
    return u if can_approve(db, u) else None


def post_out(item: ContentItem, kws: list[tuple[str, int]], c: Client) -> dict:
    volume = dict(kws).get(item.target_keyword.lower(), 0)
    v = next((v for v in item.variants if v.platform == "gmb"), None)
    return {
        "id": item.id, "status": item.status, "group": GROUP.get(item.status, "pending"), "text": v.copy if v else item.master_copy,
        "keyword": item.target_keyword, "volume": volume, "angle": item.template, "day": (day_of(item) or date.today()).isoformat(),
        "scheduled_at": _iso(item.scheduled_at), "published_at": _iso(item.published_at), "created_at": _iso(item.created_at),
        "auto_approved": item.approval_rule == RULE and item.approved_at is not None, "ai_source": item.ai_source,
        "error": (v.error if v else "") or item.last_error or "",
    }


def run_daily(db: Session) -> dict:
    """Scheduler: for every business with daily posts on, make sure tomorrow (India time) has its Google post."""
    from .models import GmbAccount

    made = skipped = 0
    tomorrow = datetime.now(TZ).date() + timedelta(days=1)
    for c in db.scalars(select(Client).join(GmbAccount).where(GmbAccount.status == "connected", Client.status != "paused")):
        if not settings_of(c)["daily"]:
            continue
        if any(day_of(i) == tomorrow for i in text_posts(db, c) if i.status not in ("rejected", "failed")):
            continue
        try:
            draft(db, c, None, day=tomorrow)
            made += 1
        except ValueError:
            skipped += 1  # no keywords yet
        db.commit()
    return {"drafted": made, "no_keywords": skipped}
