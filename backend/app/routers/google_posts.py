"""Google Post (mobile app): the daily text posts the Content Agent writes for the Google profile, their settings, and
"write one now". Approve / reject use the AI Post endpoints (/ai-posts/{id}/approve|reject) — a post is a post."""

import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import google_posts as gp
from ..ai_posts import TZ
from ..db import get_db
from ..models import ContentItem, User
from ..security import audit, require_section
from .ai_posts import _client, _may_create, _post
from .content import _unapprove, can_approve

router = APIRouter(prefix="/api/clients", tags=["google posts"])
ORDER = {"pending": 0, "approved": 1, "posted": 2, "not_posted": 3, "rejected": 4}


@router.get("/{client_id}/google-posts")
def overview(client_id: int, user: User = Depends(require_section("content")), db: Session = Depends(get_db)):
    c = _client(db, user, client_id)
    kws = gp.keywords(db, c)
    s = gp.settings_of(c)
    by = db.get(User, s["auto_by"]) if s["auto"] and s["auto_by"] else None
    items = sorted(gp.text_posts(db, c), key=lambda i: (gp.day_of(i) or datetime.min.date()), reverse=True)
    nxt = gp.next_keyword(db, c)
    return {
        "settings": {"daily": s["daily"], "auto": s["auto"], "time": s["time"], "auto_by": by.name if by else ""},
        "can_approve": can_approve(db, user), "can_create": _may_create(user, c), "connected": bool(c.gmb and c.gmb.status == "connected"),
        "keywords": [{"keyword": k, "volume": v} for k, v in kws[:10]], "keyword_count": len(kws),
        "next_keyword": nxt[0] if nxt else "",
        "counts": {g: sum(1 for i in items if gp.GROUP.get(i.status, "pending") == g) for g in ORDER},
        "items": [gp.post_out(i, kws, c) for i in items],
    }


class SettingsIn(BaseModel):
    daily: bool | None = None
    auto: bool | None = None
    time: str | None = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


@router.put("/{client_id}/google-posts/settings")
def update_settings(client_id: int, body: SettingsIn, user: User = Depends(require_section("content")), db: Session = Depends(get_db)):
    c = _client(db, user, client_id, create=True)
    s = dict(c.google_posts or {})
    changes = body.model_dump(exclude_none=True)
    if "auto" in changes:
        if not can_approve(db, user):
            raise HTTPException(403, "Only someone who approves posts can let them post automatically")
        s["auto"], s["auto_by"] = changes["auto"], user.id if changes["auto"] else None
    for k in ("daily", "time"):
        if k in changes:
            s[k] = changes[k]
    c.google_posts = s
    audit(db, user, "Google Post settings: " + ", ".join(f"{k}={v}" for k, v in changes.items()), client_id=c.id, entity_type="client", entity_id=c.id)
    db.commit()
    return overview(client_id, user, db)


class GenerateIn(BaseModel):
    keyword: str | None = Field(None, min_length=2, max_length=200)


@router.post("/{client_id}/google-posts/generate", status_code=201)
def generate(client_id: int, body: GenerateIn | None = None, user: User = Depends(require_section("content")), db: Session = Depends(get_db)):
    """Write the next Google post now (for the next day without one)."""
    c = _client(db, user, client_id, create=True)
    day = gp.next_free_day(db, c)
    if day > datetime.now(TZ).date() + timedelta(days=14):
        raise HTTPException(409, "The next two weeks already have their Google posts")
    try:
        item = gp.draft(db, c, user.id, day=day, keyword=body.keyword if body else None)
    except ValueError as e:
        raise HTTPException(422, str(e))
    audit(db, user, f"Google post written ({item.ai_source}) for {day.isoformat()}: {item.target_keyword}", client_id=c.id,
          entity_type="content", entity_id=item.id)
    db.commit()
    return gp.post_out(item, gp.keywords(db, c), c)


class EditIn(BaseModel):
    text: str = Field(min_length=20, max_length=gp.GOOGLE_LIMIT)


@router.patch("/{client_id}/google-posts/{post_id}")
def edit(client_id: int, post_id: int, body: EditIn, user: User = Depends(require_section("content")), db: Session = Depends(get_db)):
    """Change the text. Any approval is cleared, so it waits for approval again."""
    c = _client(db, user, client_id, create=True)
    item = _text_post(db, c, post_id)
    if item.status in ("published", "publishing"):
        raise HTTPException(409, "A posted Google post can't be changed here")
    text = re.sub(r"[ \t]{2,}", " ", body.text).strip()
    item.master_copy = text
    for v in item.variants:
        if v.platform == "gmb":
            v.copy, v.status, v.error = text, "pending", ""
    _unapprove(item)
    item.status, item.updated_at = "in_review", datetime.now(timezone.utc)
    audit(db, user, f"edited Google post: {item.target_keyword}", client_id=c.id, entity_type="content", entity_id=item.id)
    db.commit()
    return gp.post_out(item, gp.keywords(db, c), c)


def _text_post(db: Session, c, post_id: int) -> ContentItem:
    item = _post(db, c, post_id)
    if item.media_type != "text":
        raise HTTPException(404, "Post not found")
    return item
