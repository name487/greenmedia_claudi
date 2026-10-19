"""Google Media (mobile app): add photos and videos to the Google profile, see them as Scheduled / Uploaded / Not Posted,
approve, retry or remove them. The uploader's own upload is the approval when they may approve; otherwise it waits."""

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import google_media as gm
from .. import media
from ..db import get_db
from ..models import GoogleMedia, User
from ..security import audit, require_section
from .ai_posts import _client, _may_create
from .content import can_approve

router = APIRouter(prefix="/api/clients", tags=["google media"])
categories_router = APIRouter(prefix="/api/google-media", tags=["google media"])


@categories_router.get("/categories")
def categories(user: User = Depends(require_section("content"))):
    return {"categories": gm.CATEGORIES}


@router.get("/{client_id}/google-media")
def list_media(client_id: int, tab: Literal["scheduled", "uploaded", "not_posted"] = "scheduled",
               user: User = Depends(require_section("content")), db: Session = Depends(get_db)):
    c = _client(db, user, client_id)
    rows = list(db.scalars(select(GoogleMedia).where(GoogleMedia.client_id == c.id)))
    counts = {g: sum(1 for m in rows if gm.GROUP.get(m.status) == g) for g in ("scheduled", "uploaded", "not_posted")}
    items = [m for m in rows if gm.GROUP.get(m.status) == tab]
    far = datetime.max.replace(tzinfo=timezone.utc)
    if tab == "scheduled":
        items.sort(key=lambda m: gm._aware(m.scheduled_at) or far)
    else:
        items.sort(key=lambda m: gm._aware(m.uploaded_at or m.created_at), reverse=True)
    return {"tab": tab, "counts": counts, "items": [gm.out(m) for m in items], "can_approve": can_approve(db, user),
            "can_upload": _may_create(user, c), "connected": bool(c.gmb and c.gmb.status == "connected")}


@router.post("/{client_id}/google-media", status_code=201)
async def add_media(client_id: int, file: UploadFile = File(...), category: str = Form("ADDITIONAL"),
                    when: Literal["now", "spread"] = Form("now"), user: User = Depends(require_section("content")),
                    db: Session = Depends(get_db)):
    """Add one photo or video. "now" uploads it within the minute; "spread" gives it the next free day (one a day)."""
    c = _client(db, user, client_id, create=True)
    if category not in gm.CATEGORY:
        raise HTTPException(422, "Unknown category")
    data = await file.read(media.MAX_VIDEO + 1)
    name = file.filename or ""
    is_video = (file.content_type or "").startswith("video/") or name.rsplit(".", 1)[-1].lower() in media.VIDEO_EXTS
    try:
        if is_video:
            rel, thumb, _ = media.save_video(c.id, data, name)
        else:
            rel, thumb = media.save_profile_photo(c.id, data), ""
    except media.MediaError as e:
        raise HTTPException(422, str(e))
    approved = can_approve(db, user)
    at = datetime.now(timezone.utc) if when == "now" else gm.next_days(db, c, 1)[0]
    m = GoogleMedia(tenant_id=c.tenant_id, client_id=c.id, kind="video" if is_video else "photo", category=category, path=rel, thumb_path=thumb,
                    status="scheduled" if approved else "pending", scheduled_at=at, created_by=user.id,
                    approved_by=user.id if approved else None, approved_at=datetime.now(timezone.utc) if approved else None)
    db.add(m)
    db.flush()
    audit(db, user, f"Google {m.kind} added ({gm.CATEGORY[category]['label']}, {when})", client_id=c.id, entity_type="google_media", entity_id=m.id)
    db.commit()
    return gm.out(m)


def _media(db: Session, client_id: int, media_id: int) -> GoogleMedia:
    m = db.scalar(select(GoogleMedia).where(GoogleMedia.id == media_id, GoogleMedia.client_id == client_id))
    if not m:
        raise HTTPException(404, "Media not found")
    return m


@router.post("/{client_id}/google-media/{media_id}/approve")
def approve(client_id: int, media_id: int, user: User = Depends(require_section("content")), db: Session = Depends(get_db)):
    c = _client(db, user, client_id)
    if not can_approve(db, user):
        raise HTTPException(403, "Your role cannot approve media")
    m = _media(db, c.id, media_id)
    if m.status != "pending":
        raise HTTPException(409, "This one doesn't need approval")
    m.status, m.approved_by, m.approved_at = "scheduled", user.id, datetime.now(timezone.utc)
    m.scheduled_at = max(gm._aware(m.scheduled_at) or m.approved_at, m.approved_at)
    audit(db, user, "approved Google media", client_id=c.id, entity_type="google_media", entity_id=m.id)
    db.commit()
    return gm.out(m)


@router.post("/{client_id}/google-media/{media_id}/retry")
def retry(client_id: int, media_id: int, user: User = Depends(require_section("content")), db: Session = Depends(get_db)):
    """Try a failed upload again now (needs someone who may approve, as it goes straight out)."""
    c = _client(db, user, client_id)
    if not can_approve(db, user):
        raise HTTPException(403, "Your role cannot upload to Google")
    m = _media(db, c.id, media_id)
    if m.status != "failed":
        raise HTTPException(409, "Only media that wasn't posted can be retried")
    now = datetime.now(timezone.utc)
    m.status, m.scheduled_at, m.attempts, m.error, m.approved_by, m.approved_at = "scheduled", now, 0, "", user.id, now
    audit(db, user, "retrying Google media upload", client_id=c.id, entity_type="google_media", entity_id=m.id)
    db.commit()
    return gm.out(m)


@router.delete("/{client_id}/google-media/{media_id}", status_code=204)
def remove(client_id: int, media_id: int, user: User = Depends(require_section("content")), db: Session = Depends(get_db)):
    """Remove one that hasn't gone to Google yet (an uploaded one lives on the profile; remove it there)."""
    c = _client(db, user, client_id, create=True)
    m = _media(db, c.id, media_id)
    if m.status in ("uploaded", "publishing"):
        raise HTTPException(409, "It's already on your Google profile — remove it from Google")
    for rel in (m.path, m.thumb_path):
        if rel:
            media.path_of(rel).unlink(missing_ok=True)
    db.delete(m)
    audit(db, user, "removed Google media before upload", client_id=c.id, entity_type="google_media", entity_id=media_id)
    db.commit()
