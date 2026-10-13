from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import review_queue
from ..config import settings
from ..db import get_db
from ..models import AuditLog, Client, Review, User
from ..publishers import PublishError
from ..security import audit, can, get_client, require_section, scoped_ids
from ..serializers import iso, review_out

router = APIRouter(prefix="/api/reviews", tags=["reviews"])

PENDING = ("new", "drafted", "approved", "failed")

FILTERS = {
    "pending": lambda r: r.reply_status in PENDING,  # failed = publish failed, still needs a reply
    "approved": lambda r: r.reply_status == "approved",
    "negative": lambda r: r.sentiment == "negative" and r.reply_status != "published",
    "published": lambda r: r.reply_status == "published",
    "all": lambda r: True,
}


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def _stats(rows: list[Review], now: datetime) -> dict:
    pending = [r for r in rows if r.reply_status in PENDING]
    recent = [r for r in rows if _aware(r.created_at) >= now - timedelta(days=90)]
    answered = [r for r in recent if r.reply_status == "published" and r.published_at and _aware(r.published_at) >= _aware(r.created_at)]
    ages = [(now - _aware(r.created_at)).total_seconds() / 3600 for r in pending]
    return {
        "needs_reply": len(pending),
        "negative_waiting": sum(r.sentiment == "negative" for r in pending),
        "ai_drafts_ready": sum(r.reply_status == "drafted" for r in pending),
        "awaiting_approval": sum(r.reply_status == "drafted" and r.rating <= 2 for r in pending),
        "overdue": sum(a > 48 for a in ages),
        "oldest_waiting_hours": round(max(ages)) if ages else None,
        "response_rate": round(100 * sum(r.reply_status == "published" for r in recent) / len(recent)) if recent else None,
        "avg_response_hours": round(sum((_aware(r.published_at) - _aware(r.created_at)).total_seconds() for r in answered) / len(answered) / 3600, 1) if answered else None,
        "avg_rating": round(sum(r.rating for r in recent) / len(recent), 1) if recent else None,
    }


def _sources(db: Session, user: User, clients: list[Client], rows: list[Review]) -> dict:
    samples: dict[int, int] = {}
    for r in rows:
        if r.is_sample:
            samples[r.client_id] = samples.get(r.client_id, 0) + 1
    items = [{"client_id": c.id, "client_name": c.company_name, "state": review_queue.source_state(c, samples.get(c.id, 0)), "samples": samples.get(c.id, 0),
              "title": c.gmb.title if c.gmb else "", "last_sync": iso(c.gmb.last_sync) if c.gmb else None, "last_error": c.gmb.last_error if c.gmb else ""}
             for c in sorted(clients, key=lambda c: c.company_name)]
    states = [x["state"] for x in items]
    return {
        "clients": items,
        "summary": {k: states.count(k) for k in ("live", "approval_pending", "error", "sample", "none")},
        "approval_pending": "approval_pending" in states or review_queue.agency_approval_pending(db, user.tenant_id),
        "sample_data_enabled": settings.review_sample_data,
    }


def _priority(now: datetime):
    def key(r: Review):
        if r.reply_status in PENDING:  # waiting: negatives / 2★ first, then longest waiting
            return (0, r.sentiment != "negative" and r.rating > 2, _aware(r.created_at).timestamp())
        return (1, 0, -_aware(r.created_at).timestamp())
    return key


@router.get("")
def list_reviews(filter: Literal["pending", "approved", "negative", "published", "all"] = "pending", client_id: int | None = None,
                 rating: int | None = None, sentiment: Literal["positive", "neutral", "negative"] | None = None,
                 source: Literal["google", "sample"] | None = None, q: str = "",
                 sort: Literal["priority", "newest", "oldest", "rating"] = "priority", limit: int = 50, offset: int = 0,
                 user: User = Depends(require_section("reviews")), db: Session = Depends(get_db)):
    """The AI Review Queue. Filters narrow the list and the tab counts; stats and sources describe the whole scope."""
    if rating is not None and not 1 <= rating <= 5:
        raise HTTPException(422, "rating must be 1-5")
    limit, offset = max(1, min(limit, 200)), max(0, offset)
    ids = scoped_ids(db, user, client_id)
    clients = list(db.scalars(select(Client).where(Client.id.in_(ids))))
    names = {c.id: c.company_name for c in clients}
    rows = list(db.scalars(select(Review).where(Review.client_id.in_(ids))))
    now = datetime.now(timezone.utc)
    needle = q.strip().lower()
    narrowed = [r for r in rows
                if (rating is None or r.rating == rating) and (sentiment is None or r.sentiment == sentiment)
                and (source is None or r.is_sample == (source == "sample"))
                and (not needle or needle in f"{r.author} {r.text} {r.reply or ''} {names[r.client_id]}".lower())]
    counts = {k: sum(1 for r in narrowed if f(r)) for k, f in FILTERS.items()}
    items = [r for r in narrowed if FILTERS[filter](r)]
    if sort == "priority":
        items.sort(key=_priority(now))
    elif sort == "rating":
        items.sort(key=lambda r: (r.rating, -_aware(r.created_at).timestamp()))
    else:
        items.sort(key=lambda r: _aware(r.created_at), reverse=sort == "newest")
    page = items[offset:offset + limit]
    hist = _history(db, user.tenant_id, [r.id for r in page], per_review=10)
    return {
        "counts": counts, "total": len(items), "limit": limit, "offset": offset,
        "items": [{**review_out(r, names[r.client_id]), "history": hist.get(r.id, [])} for r in page],
        "stats": _stats(rows, now), "sources": _sources(db, user, clients, rows),
    }


def _load(db: Session, user: User, review_id: int) -> tuple[Review, Client]:
    r = db.get(Review, review_id)
    if not r or r.tenant_id != user.tenant_id:
        raise HTTPException(404, "Review not found")
    return r, get_client(db, user, r.client_id)


def _publish(db: Session, user: User | None, r: Review, c: Client) -> dict:
    try:
        return review_queue.publish(r, c)
    except PublishError as e:
        r.reply_status = "failed"
        if user:
            audit(db, user, f"publish failed: {e}", client_id=c.id, entity_type="review", entity_id=r.id, details={"error": str(e), "reply": r.reply})
        db.commit()
        raise HTTPException(502, str(e))


class DraftIn(BaseModel):
    instruction: str = Field(default="", max_length=500)  # e.g. "shorter", "mention our Sunday hours"


@router.post("/{review_id}/draft")
def draft(review_id: int, body: DraftIn | None = None, user: User = Depends(require_section("reviews")), db: Session = Depends(get_db)):
    """Draft (or regenerate) the reply with the client's brand-voice prompt. Optional instruction steers a regenerate."""
    r, c = _load(db, user, review_id)
    if r.reply_status == "published":
        raise HTTPException(409, "Already published")
    instruction = (body.instruction if body else "").strip()
    before = r.reply
    meta = review_queue.draft(r, c, instruction)
    verb = "regenerated reply" if before else "drafted reply"
    audit(db, user, f"AI {verb} ({meta['source']}{', ' + meta['model'] if meta['source'] == 'ai' else ''})", client_id=c.id, entity_type="review",
          entity_id=r.id, details={**review_queue.draft_details(meta, r.reply, instruction), **({"before": before} if before else {})})
    db.commit()
    return {**review_out(r, c.company_name), "source": meta["source"], "ai": meta}


class ReplyIn(BaseModel):
    reply: str = Field(min_length=1, max_length=4000)  # Google's limit is 4096 bytes


@router.patch("/{review_id}")
def edit(review_id: int, body: ReplyIn, user: User = Depends(require_section("reviews")), db: Session = Depends(get_db)):
    r, c = _load(db, user, review_id)
    if r.reply_status == "published":
        raise HTTPException(409, "Already published")
    new = body.reply.strip()
    if not new:
        raise HTTPException(422, "Reply can't be empty")
    before = r.reply
    r.reply, r.reply_status = new, "drafted"  # an edit always needs re-approval
    review_queue.clear_approval(r)
    if new != before:
        r.reply_source, r.reply_model = "human", ""
    audit(db, user, "edited reply", client_id=c.id, entity_type="review", entity_id=r.id, details={"before": before, "after": new})
    db.commit()
    return review_out(r, c.company_name)


Action = Literal["approve", "reject", "publish", "reopen"]
VERB = {"approve": "approved reply", "reject": "rejected reply", "publish": "published reply to Google", "reopen": "reopened review", "draft": "AI drafted reply"}


def _act(db: Session, user: User, r: Review, c: Client, action: str) -> None:
    """One state transition with its permission and escalation rules, written to audit_logs. Raises HTTPException."""
    details: dict = {"from": r.reply_status}
    if action == "draft":
        if r.reply_status == "published":
            raise HTTPException(409, "Already published")
        meta = review_queue.draft(r, c)
        details.update(review_queue.draft_details(meta, r.reply))
    elif action == "approve":
        if not can(user, "review.approve"):
            raise HTTPException(403, "Your role cannot approve replies")
        if not r.reply or r.reply_status not in ("drafted", "failed"):
            raise HTTPException(409, "Only drafted replies can be approved")
        r.reply_status = "approved"
        review_queue.approve(r, user.id)
        details["reply"] = r.reply
    elif action == "publish":
        if not can(user, "review.publish"):
            raise HTTPException(403, "Your role cannot publish replies")
        if not r.reply:
            raise HTTPException(409, "Nothing to publish")
        if r.reply_status not in ("approved", "failed") or not r.approved_at:
            raise HTTPException(409, "Replies must be approved first — Approve, then Publish" + (" (2★ or lower: an account manager should check it)" if r.rating <= 2 else ""))
        details.update(_publish(db, user, r, c))
    elif action == "reject":
        if r.reply_status == "published":
            raise HTTPException(409, "Already published")
        r.reply_status = "rejected"
        review_queue.clear_approval(r)
        details["reply"] = r.reply
    else:  # reopen
        if r.reply_status != "rejected":
            raise HTTPException(409, "Only rejected reviews can be reopened")
        r.reply_status = "drafted" if r.reply else "new"
        review_queue.clear_approval(r)
    verb = VERB[action]
    if action == "publish" and details.get("target") != "google":
        verb = "published reply (sample — not sent to Google)" if r.is_sample else "published reply (demo client — simulated)"
    details["to"] = r.reply_status
    audit(db, user, verb, client_id=c.id, entity_type="review", entity_id=r.id, details=details)


@router.get("/{review_id}/history")
def history(review_id: int, user: User = Depends(require_section("reviews")), db: Session = Depends(get_db)):
    """Everything that happened to this review, newest first, from audit_logs."""
    r, _ = _load(db, user, review_id)
    return _history(db, user.tenant_id, [r.id]).get(r.id, [])


def _history(db: Session, tenant_id: int, ids: list[int], per_review: int = 20) -> dict[int, list[dict]]:
    if not ids:
        return {}
    rows = db.scalars(select(AuditLog).where(AuditLog.tenant_id == tenant_id, AuditLog.entity_type == "review",
                                             AuditLog.entity_id.in_([str(i) for i in ids])).order_by(AuditLog.id.desc()))
    names = dict(db.execute(select(User.id, User.name).where(User.tenant_id == tenant_id)).all())
    out: dict[int, list[dict]] = {}
    for a in rows:
        lst = out.setdefault(int(a.entity_id), [])
        if len(lst) < per_review:
            lst.append({"action": a.action, "user_name": names.get(a.user_id) if a.user_id else "System", "created_at": iso(a.created_at), "details": a.details or {}})
    return out


@router.post("/{review_id}/{action}")
def transition(review_id: int, action: Action, user: User = Depends(require_section("reviews")), db: Session = Depends(get_db)):
    r, c = _load(db, user, review_id)
    _act(db, user, r, c, action)
    db.commit()
    return review_out(r, c.company_name)


class BulkIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=100)
    action: Literal["draft", "approve", "publish", "reject"]


@router.post("/bulk")
def bulk(body: BulkIn, user: User = Depends(require_section("reviews")), db: Session = Depends(get_db)):
    """Apply one action to many reviews. Each review follows the same rules as the single action (2★ escalation,
    role permissions); the ones that can't be done are reported, the rest go through."""
    done, failed = 0, []
    for rid in dict.fromkeys(body.ids):
        try:
            r, c = _load(db, user, rid)
            _act(db, user, r, c, body.action)
            db.commit()
            done += 1
        except HTTPException as e:
            if e.status_code != 502:  # a failed publish was already recorded and committed
                db.rollback()
            failed.append({"id": rid, "error": e.detail})
    return {"done": done, "failed": failed}


class SyncIn(BaseModel):
    client_id: int | None = None


@router.post("/sync")
def sync(body: SyncIn, user: User = Depends(require_section("gmb")), db: Session = Depends(get_db)):
    """Fetch new reviews: from Google for linked clients, sample reviews while Google API approval is pending or
    a client isn't linked yet. New reviews get AI drafts; positive ones auto-publish when the client opted in."""
    ids = scoped_ids(db, user, body.client_id)
    clients = list(db.scalars(select(Client).where(Client.id.in_(ids)).order_by(Client.id)))
    if not clients:
        raise HTTPException(409, "No clients to sync")
    if not settings.review_sample_data and not any(c.gmb and c.gmb.is_live for c in clients):
        raise HTTPException(409, "No client here is linked to Google yet (and sample data is turned off with REVIEW_SAMPLE_DATA=0)")
    out = review_queue.sync(db, clients)
    parts = [f"{out['new_reviews']} new from Google"] if out["profiles"] else []
    if out["sample_reviews"]:
        parts.append(f"{out['sample_reviews']} sample")
    audit(db, user, f"review sync: {', '.join(parts) or 'nothing new'}; {out['drafted']} AI drafts", entity_type="review")
    db.commit()
    return out
