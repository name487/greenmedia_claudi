import random
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import ai
from ..db import get_db
from ..google import api as google_api
from ..google import service as google_service
from ..models import Client, Review, User
from ..publishers import PublishError, publish_review_reply
from ..security import audit, can, get_client, require_section, scoped_ids
from ..sentiment import detect_language, detect_sentiment
from ..serializers import review_out

router = APIRouter(prefix="/api/reviews", tags=["reviews"])

FILTERS = {
    "pending": lambda r: r.reply_status in ("new", "drafted", "approved"),
    "approved": lambda r: r.reply_status == "approved",
    "negative": lambda r: r.sentiment == "negative" and r.reply_status != "published",
    "published": lambda r: r.reply_status == "published",
    "all": lambda r: True,
}


@router.get("")
def list_reviews(filter: Literal["pending", "approved", "negative", "published", "all"] = "pending", client_id: int | None = None,
                 user: User = Depends(require_section("reviews")), db: Session = Depends(get_db)):
    ids = scoped_ids(db, user, client_id)
    names = dict(db.execute(select(Client.id, Client.company_name).where(Client.id.in_(ids))).all())
    rows = list(db.scalars(select(Review).where(Review.client_id.in_(ids)).order_by(Review.created_at.desc())))
    counts = {k: sum(1 for r in rows if f(r)) for k, f in FILTERS.items()}
    items = [r for r in rows if FILTERS[filter](r)]
    items.sort(key=lambda r: r.sentiment != "negative")  # negatives first, stable on recency
    return {"counts": counts, "items": [review_out(r, names[r.client_id]) for r in items]}


def _load(db: Session, user: User, review_id: int) -> tuple[Review, Client]:
    r = db.get(Review, review_id)
    if not r or r.tenant_id != user.tenant_id:
        raise HTTPException(404, "Review not found")
    return r, get_client(db, user, r.client_id)


def _draft(r: Review, c: Client) -> str:
    reply, source = ai.review_reply(
        company=c.company_name, industry=c.industry, city=c.city, phone=c.contacts[0].phone if c.contacts else "",
        brand_voice=c.brand_voice, author=r.author, rating=r.rating, text=r.text, language=r.language, sentiment=r.sentiment,
    )
    r.reply, r.reply_status = reply, "drafted"
    return source


def _publish(db: Session, user: User | None, r: Review, c: Client) -> None:
    try:
        publish_review_reply(c, r.external_review_id, r.reply or "")
    except PublishError as e:
        r.reply_status = "failed"
        if user:
            audit(db, user, f"publish failed: {e}", client_id=c.id, entity_type="review", entity_id=r.id)
        db.commit()
        raise HTTPException(502, str(e))
    r.reply_status, r.published_at = "published", datetime.now(timezone.utc)


@router.post("/{review_id}/draft")
def draft(review_id: int, user: User = Depends(require_section("reviews")), db: Session = Depends(get_db)):
    r, c = _load(db, user, review_id)
    if r.reply_status == "published":
        raise HTTPException(409, "Already published")
    source = _draft(r, c)
    audit(db, user, f"AI drafted reply ({source})", client_id=c.id, entity_type="review", entity_id=r.id)
    db.commit()
    return {**review_out(r, c.company_name), "source": source}


class ReplyIn(BaseModel):
    reply: str


@router.patch("/{review_id}")
def edit(review_id: int, body: ReplyIn, user: User = Depends(require_section("reviews")), db: Session = Depends(get_db)):
    r, c = _load(db, user, review_id)
    if r.reply_status == "published":
        raise HTTPException(409, "Already published")
    r.reply, r.reply_status = body.reply.strip(), "drafted"  # an edit always needs re-approval
    audit(db, user, "edited reply", client_id=c.id, entity_type="review", entity_id=r.id)
    db.commit()
    return review_out(r, c.company_name)


@router.post("/{review_id}/{action}")
def transition(review_id: int, action: Literal["approve", "reject", "publish", "reopen"], user: User = Depends(require_section("reviews")), db: Session = Depends(get_db)):
    r, c = _load(db, user, review_id)
    if action == "approve":
        if not can(user, "review.approve"):
            raise HTTPException(403, "Your role cannot approve replies")
        if not r.reply or r.reply_status not in ("drafted", "failed"):
            raise HTTPException(409, "Only drafted replies can be approved")
        r.reply_status = "approved"
    elif action == "publish":
        if not can(user, "review.publish"):
            raise HTTPException(403, "Your role cannot publish replies")
        if not r.reply:
            raise HTTPException(409, "Nothing to publish")
        if r.rating <= 2 and r.reply_status != "approved":
            raise HTTPException(409, "Replies to reviews of 2★ or less must be approved first")
        if r.reply_status not in ("drafted", "approved", "failed"):
            raise HTTPException(409, f"Cannot publish a {r.reply_status} reply")
        _publish(db, user, r, c)
    elif action == "reject":
        if r.reply_status == "published":
            raise HTTPException(409, "Already published")
        r.reply_status = "rejected"
    else:  # reopen
        if r.reply_status != "rejected":
            raise HTTPException(409, "Only rejected reviews can be reopened")
        r.reply_status = "drafted" if r.reply else "new"
    audit(db, user, {"approve": "approved reply", "reject": "rejected reply", "publish": "published reply to Google", "reopen": "reopened review"}[action],
          client_id=c.id, entity_type="review", entity_id=r.id)
    db.commit()
    return review_out(r, c.company_name)


INCOMING = [(5, "Loved the service today, team was super quick and helpful!"), (1, "Booked online but nobody was there when I arrived. Very poor experience."), (4, "Good experience, will come back again.")]


class SyncIn(BaseModel):
    client_id: int | None = None


@router.post("/sync")
def sync(body: SyncIn, user: User = Depends(require_section("gmb")), db: Session = Depends(get_db)):
    """Simulates the Google review webhook: fetch → language → sentiment → AI draft → (optional) auto-publish.
    Production: triggered by GBP Pub/Sub notifications or a scheduled pull."""
    ids = scoped_ids(db, user, body.client_id)
    pool = [c for c in db.scalars(select(Client).where(Client.id.in_(ids))) if c.gmb and c.gmb.status == "connected"]
    live = [c for c in pool if c.gmb.is_live]
    if live:
        # Real Google profiles in scope: pull their reviews instead of simulating one.
        new, errors = 0, []
        for c in live:
            try:
                new += google_service.sync_reviews(db, c)["new_reviews"]
                c.gmb.last_sync, c.gmb.last_error = datetime.now(timezone.utc), ""
            except google_api.GoogleApiError as e:
                c.gmb.last_error = str(e)
                errors.append(f"{c.company_name}: {e}")
        audit(db, user, f"Google review sync: {new} new", entity_type="review")
        db.commit()
        return {"mode": "live", "profiles": len(live), "new_reviews": new, "errors": errors}
    if not pool:
        raise HTTPException(409, "No connected Google Business Profiles")
    c = random.choice(pool)
    rating, text = random.choice(INCOMING)
    r = Review(tenant_id=user.tenant_id, client_id=c.id, external_review_id=f"demo_{uuid.uuid4().hex[:10]}", author="New Customer", rating=rating, text=text,
               language=detect_language(text), sentiment=detect_sentiment(text, rating))
    db.add(r)
    db.flush()
    audit(db, user, "review received", client_id=c.id, entity_type="review", entity_id=r.id)
    source = _draft(r, c)
    auto = bool(c.auto_publish.get("reviews")) and r.sentiment == "positive"
    if auto:
        try:
            _publish(db, None, r, c)
        except HTTPException:
            auto = False
    audit(db, user, "auto-published reply" if auto else f"AI drafted reply ({source})", client_id=c.id, entity_type="review", entity_id=r.id)
    db.commit()
    return {"mode": "demo", **review_out(r, c.company_name)}
