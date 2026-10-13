"""AI Review Queue pipeline: fetch (Google, or sample data) → language → sentiment → AI draft → approve → publish.

Sample data: until Google approves Business Profile API access for the Cloud project, every Business Profile
call fails with quota 0. So the queue (and the team's workflow) can be used before that, a sync falls back to
realistic sample reviews. They are labelled everywhere, never sent to Google, and deleted automatically the
first time real reviews are fetched for that client (and when a location is linked).
"""

import random
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import ai
from .config import settings
from .google import api as google_api
from .google import service as google_service
from .models import SAMPLE_REVIEW_PREFIX, Client, GoogleConnection, Review
from .publishers import PublishError, publish_review_reply
from .security import audit
from .sentiment import detect_language, detect_sentiment

# (rating, text). Industry-neutral so they read naturally for any local business; English, Hindi and Hinglish.
SAMPLE_TEXTS = [
    (5, "Excellent service from start to finish. The staff were friendly and explained everything clearly. Highly recommend!"),
    (5, "Best experience I've had in {city}. Quick, professional and very polite team."),
    (4, "Good experience overall. Slight wait at the front desk but the team made up for it."),
    (5, "बहुत अच्छी सर्विस! स्टाफ बहुत मददगार था। ज़रूर फिर आएंगे।"),
    (2, "Waited over 40 minutes past my appointment time and nobody gave an update. Not happy."),
    (1, "Very poor experience. Staff were rude on the phone and my issue still isn't sorted. Want a refund."),
    (3, "Service was okay, nothing special. Prices are a bit high compared to others nearby."),
    (5, "Amazing team, they went out of their way to help. Thank you so much!"),
    (4, "Clean place, polite staff. Parking is difficult though."),
    (5, "Bahut badiya experience tha, staff ne sab kuch achhe se samjhaya. Recommend karunga!"),
    (2, "Booked online but when I arrived they had no record of it. Disappointing."),
    (5, "Loved it! Will definitely be coming back and telling my friends."),
    (4, "Very professional. Took a little longer than promised but the result was great."),
    (1, ""),  # rating-only review, as Google allows
    (5, ""),
]
FIRST = ["Aarav", "Ishita", "Rahul", "Neha", "Vikram", "Pooja", "Arjun", "Kavya", "Siddharth", "Meera", "Rohan", "Ananya", "Karan", "Divya"]
LAST = ["Sharma", "Patel", "Iyer", "Reddy", "Gupta", "Menon", "Khan", "Desai", "Joshi", "Bose", "Kulkarni", "Singh"]

INITIAL_BATCH = 6
MAX_SAMPLES_PER_CLIENT = 30


def sample_count(db: Session, client_id: int) -> int:
    return db.scalar(select(func.count()).select_from(Review).where(Review.client_id == client_id, Review.external_review_id.startswith(SAMPLE_REVIEW_PREFIX))) or 0


def add_samples(db: Session, client: Client, n: int, rnd: random.Random | None = None) -> list[Review]:
    """Insert n sample reviews (spread over the last 10 days, newest last). Returns them, flushed."""
    rnd = rnd or random.Random()
    now = datetime.now(timezone.utc)
    out = []
    for i in range(n):
        rating, text = rnd.choice(SAMPLE_TEXTS)
        text = text.format(city=client.city or "town")
        age = timedelta(hours=rnd.randint(1, 240)) if n > 1 else timedelta(minutes=rnd.randint(1, 30))
        r = Review(tenant_id=client.tenant_id, client_id=client.id, external_review_id=f"{SAMPLE_REVIEW_PREFIX}s{uuid.uuid4().hex[:12]}",
                   author=f"{rnd.choice(FIRST)} {rnd.choice(LAST)[0]}.", rating=rating, text=text, language=detect_language(text),
                   sentiment=detect_sentiment(text, rating), created_at=now - age, reply_status="new")
        db.add(r)
        out.append(r)
    db.flush()
    return out


def draft(r: Review, c: Client, instruction: str = "") -> dict:
    """AI-draft a reply with the client's brand-voice prompt (or the brand-voice template when the AI isn't
    available). Returns the AI meta: source ai|template, provider, model, usage, ms, error."""
    reply, meta = ai.review_reply(
        company=c.company_name, industry=c.industry, city=c.city, phone=c.contacts[0].phone if c.contacts else "",
        brand_voice=c.brand_voice, author=r.author, rating=r.rating, text=r.text, language=r.language, sentiment=r.sentiment, instruction=instruction,
    )
    r.reply, r.reply_status, r.drafted_at = reply, "drafted", datetime.now(timezone.utc)
    clear_approval(r)
    r.reply_source = meta["source"]
    r.reply_model = f"{meta['provider']}/{meta['model']}" if meta["source"] == "ai" else ""
    r.reply_error = meta.get("error", "") if meta["source"] == "template" else ""
    return meta


def draft_details(meta: dict, reply: str, instruction: str = "") -> dict:
    """What goes into audit_logs.details for a draft."""
    d = {k: meta[k] for k in ("source", "provider", "model", "usage", "ms", "request_id", "error", "error_code") if meta.get(k) not in (None, "")}
    if instruction:
        d["instruction"] = instruction
    d["reply"] = reply
    return d


def approve(r: Review, user_id: int | None, rule: str = "") -> None:
    r.approved_by, r.approved_at, r.approval_rule = user_id, datetime.now(timezone.utc), rule


def clear_approval(r: Review) -> None:
    r.approved_by, r.approved_at, r.approval_rule = None, None, ""


def publish(r: Review, c: Client) -> dict:
    """Post the reply through the official Google Business Profile API (reviews.updateReply) and mark it
    published. Sample reviews are only marked. Returns audit details. Raises PublishError.

    Last line of defence: whatever calls this, an unapproved reply is never sent."""
    if not r.approved_at or r.reply_status not in ("approved", "failed"):
        raise PublishError("This reply hasn't been approved — approve it before publishing")
    if r.is_sample:
        r.reply_status, r.published_at = "published", datetime.now(timezone.utc)
        return {"target": "sample", "reply": r.reply, "approved_by": r.approved_by, "approval_rule": r.approval_rule or None}
    res = publish_review_reply(c, r.external_review_id, r.reply or "") or {}
    r.reply_status = "published"
    r.published_at = google_api.parse_time(res.get("updateTime")) or datetime.now(timezone.utc)
    return {"target": "google" if c.gmb and c.gmb.is_live else "simulated", "reply": r.reply,
            "approved_by": r.approved_by, "approval_rule": r.approval_rule or None,
            "google": {k: res[k] for k in ("updateTime",) if k in res} or None,
            "location": f"{c.gmb.google_account}/{c.gmb.location_id}" if c.gmb and c.gmb.is_live else None}


def process_new(db: Session, c: Client, reviews: list[Review], limit: int | None = None) -> dict:
    """Draft AI replies for newly arrived reviews (newest first, up to `limit`) and auto-publish positive ones
    when the client opted in (Client Workspace → Publishing safety). Negative/neutral always wait for a human.
    Each step is written to audit_logs as a system action."""
    limit = settings.review_autodraft_limit if limit is None else limit
    drafted = auto = 0
    errors: list[str] = []
    for r in sorted(reviews, key=lambda x: _aware(x.created_at), reverse=True)[:limit]:
        if r.reply_status != "new":
            continue
        meta = draft(r, c)
        drafted += 1
        audit(db, None, f"[auto] AI drafted reply ({meta['source']})", tenant_id=c.tenant_id, client_id=c.id, entity_type="review", entity_id=r.id,
              details=draft_details(meta, r.reply))
        recent = datetime.now(timezone.utc) - _aware(r.created_at) < timedelta(days=14)  # never auto-reply to old reviews
        if c.auto_publish.get("reviews") and r.sentiment == "positive" and r.rating >= 4 and recent:
            try:
                approve(r, None, rule="auto_publish")  # the client's standing approval for positive 4-5★ replies
                r.reply_status = "approved"
                details = publish(r, c)
                auto += 1
                audit(db, None, "[auto] published reply" + (" (sample — not sent to Google)" if r.is_sample else " to Google"), tenant_id=c.tenant_id,
                      client_id=c.id, entity_type="review", entity_id=r.id, details={**details, "rule": "auto-publish positive 4-5★"})
            except PublishError as e:
                r.reply_status = "failed"
                errors.append(f"{c.company_name}: {e}")
                audit(db, None, f"[auto] publish failed: {e}", tenant_id=c.tenant_id, client_id=c.id, entity_type="review", entity_id=r.id, details={"error": str(e)})
    return {"drafted": drafted, "auto_published": auto, "errors": errors}


def sync_live(db: Session, c: Client) -> dict:
    """Full Google sync of a linked client (reviews + insights), then AI drafts for the new reviews."""
    out = google_service.sync_client(db, c)
    out.update(process_new(db, c, [db.get(Review, i) for i in out.pop("new_review_ids", [])]))
    return out


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def agency_approval_pending(db: Session, tenant_id: int) -> bool:
    errs = db.scalars(select(GoogleConnection.last_error).where(GoogleConnection.tenant_id == tenant_id, GoogleConnection.status == "active"))
    return any(google_api.is_approval_pending(None, e) for e in errs if e)


def source_state(c: Client, samples: int) -> str:
    """Where this client's reviews come from right now:
    live | approval_pending (linked/signed in, Google quota 0) | error (e.g. access expired) | sample | none."""
    g = c.gmb
    pending = bool(g and g.last_error and google_api.is_approval_pending(None, g.last_error))
    if g and g.is_live:
        return "approval_pending" if pending else ("error" if g.last_error and g.status != "connected" else "live")
    if g and g.has_own_token and pending:
        return "approval_pending"
    return "sample" if samples else "none"


def sync(db: Session, clients: list[Client], *, rnd: random.Random | None = None) -> dict:
    """Pull reviews for the given clients and run the pipeline on what's new.

    - Linked to Google: fetch from Google. If Google says quota 0 (API approval pending), fall back to sample
      reviews for that client so the queue still works.
    - Not linked: sample reviews (unless REVIEW_SAMPLE_DATA=0). A client without reviews gets a first batch;
      after that each sync brings one new sample review for one client, like a real review arriving.
    """
    rnd = rnd or random.Random()
    out = {"profiles": 0, "new_reviews": 0, "sample_reviews": 0, "drafted": 0, "auto_published": 0, "errors": [], "approval_pending": [], "clients": []}

    def run(c: Client, reviews: list[Review], kind: str, **extra) -> None:
        p = process_new(db, c, reviews)
        out["drafted"] += p["drafted"]
        out["auto_published"] += p["auto_published"]
        out["errors"] += p["errors"]
        out["clients"].append({"client_id": c.id, "client_name": c.company_name, "mode": kind, "new": len(reviews),
                               "review_ids": [r.id for r in reviews], **p, **extra})

    def samples_for(c: Client, first_only: bool = False) -> None:
        have = sample_count(db, c.id)
        if have >= MAX_SAMPLES_PER_CLIENT or (first_only and have):
            return
        new = add_samples(db, c, INITIAL_BATCH if have == 0 else 1, rnd)
        out["sample_reviews"] += len(new)
        run(c, new, "sample")

    not_live = []
    for c in clients:
        if c.gmb and c.gmb.is_live:
            try:
                res = google_service.sync_reviews(db, c)
                c.gmb.last_sync, c.gmb.last_error = datetime.now(timezone.utc), ""
                if c.gmb.status == "expired":
                    c.gmb.status = "connected"
                out["profiles"] += 1
                out["new_reviews"] += res["new_reviews"]
                run(c, [db.get(Review, i) for i in res["new_review_ids"]], "live", updated=res["updated_reviews"], removed_samples=res["removed_samples"])
            except google_api.GoogleApiError as e:
                c.gmb.last_error = str(e)
                if e.auth_failed:
                    c.gmb.status = "expired"
                if e.approval_pending:
                    out["approval_pending"].append(c.company_name)
                    if settings.review_sample_data:
                        samples_for(c)
                else:
                    out["errors"].append(f"{c.company_name}: {e}")
        else:
            not_live.append(c)
    if settings.review_sample_data and not_live:
        fresh = [c for c in not_live if not db.scalar(select(Review.id).where(Review.client_id == c.id).limit(1))]
        for c in fresh[:10]:  # first batch for clients with no reviews at all (10 per sync keeps big imports quick)
            samples_for(c, first_only=True)
        if not fresh:
            samples_for(rnd.choice(not_live))
    out["mode"] = "live" if out["profiles"] and not out["sample_reviews"] else ("mixed" if out["profiles"] else "sample")
    return out
