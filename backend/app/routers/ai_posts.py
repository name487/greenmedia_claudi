"""AI Post (mobile app): product items, AI posters, viral videos, the owner's Pending / Approved / Rejected / Posted /
Not Posted lists, and approve-and-schedule / reject. Nothing is published until someone who may approve has approved it."""

from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import ai_posts, content_service, media, reply_keywords
from ..config import settings
from ..db import get_db
from ..models import Client, ContentItem, ProductItem, User
from ..security import audit, can, get_client, require_section
from .content import _approve, _check_schedule, _publishable, can_approve

router = APIRouter(prefix="/api/clients", tags=["ai posts"])
templates_router = APIRouter(prefix="/api/video-templates", tags=["ai posts"])

PERIOD_DAYS = {"week": 7, "month": 30, "quarter": 91}


def _may_create(user: User, c: Client) -> bool:
    return user.client_id == c.id or can(user, "content.create")


def _client(db: Session, user: User, client_id: int, create: bool = False) -> Client:
    c = get_client(db, user, client_id)
    if create and not _may_create(user, c):
        raise HTTPException(403, "Your role cannot create posts")
    return c


def _kws(db: Session, c: Client) -> list[tuple[str, int]]:
    return reply_keywords.for_clients(db, [c.id])[c.id]


@templates_router.get("")
def video_templates(user: User = Depends(require_section("content"))):
    return {"templates": [{k: t[k] for k in ("key", "name", "tagline", "intro", "bg", "accent", "motion")} for t in ai_posts.TEMPLATES]}


# ---------- product items ----------

@router.get("/{client_id}/items")
def list_items(client_id: int, user: User = Depends(require_section("content")), db: Session = Depends(get_db)):
    c = _client(db, user, client_id)
    return {"items": [ai_posts.item_out(i) for i in db.scalars(select(ProductItem).where(ProductItem.client_id == c.id).order_by(ProductItem.id.desc()))]}


@router.post("/{client_id}/items", status_code=201)
async def add_item(client_id: int, image: UploadFile = File(...), name: str = Form(..., min_length=2, max_length=120),
                   description: str = Form("", max_length=1000), price: str = Form("", max_length=40),
                   user: User = Depends(require_section("content")), db: Session = Depends(get_db)):
    c = _client(db, user, client_id, create=True)
    data = await image.read(media.MAX_UPLOAD + 1)
    try:
        rel = media.save_photo(c.id, data)
    except media.MediaError as e:
        raise HTTPException(422, str(e))
    i = ProductItem(tenant_id=c.tenant_id, client_id=c.id, name=name.strip(), description=description.strip(), price=price.strip(), image_path=rel)
    db.add(i)
    db.flush()
    audit(db, user, f"added product “{i.name}”", client_id=c.id, entity_type="product_item", entity_id=i.id)
    db.commit()
    return ai_posts.item_out(i)


@router.delete("/{client_id}/items/{item_id}", status_code=204)
def delete_item(client_id: int, item_id: int, user: User = Depends(require_section("content")), db: Session = Depends(get_db)):
    c = _client(db, user, client_id, create=True)
    i = db.scalar(select(ProductItem).where(ProductItem.id == item_id, ProductItem.client_id == c.id))
    if not i:
        raise HTTPException(404, "Item not found")
    db.delete(i)
    audit(db, user, f"removed product “{i.name}”", client_id=c.id, entity_type="product_item", entity_id=item_id)
    db.commit()


# ---------- posts ----------

@router.get("/{client_id}/ai-posts/overview")
def overview(client_id: int, user: User = Depends(require_section("content")), db: Session = Depends(get_db)):
    c = _client(db, user, client_id)
    rows = list(db.scalars(select(ContentItem.status).where(ContentItem.client_id == c.id)))
    counts = {g: 0 for g in ("pending", "approved", "rejected", "posted", "not_posted")}
    for s in rows:
        counts[ai_posts.GROUP.get(s, "pending")] += 1
    return {"quota": ai_posts.quota(db, c), "counts": counts, "can_approve": can_approve(db, user), "can_create": _may_create(user, c),
            "business": ai_posts.business(c)}


@router.get("/{client_id}/ai-posts")
def list_posts(client_id: int, tab: Literal["pending", "approved", "rejected", "posted", "not_posted"] = "pending",
               period: Literal["week", "month", "quarter", "lifetime"] = "lifetime", user: User = Depends(require_section("content")),
               db: Session = Depends(get_db)):
    c = _client(db, user, client_id)
    rows = [i for i in db.scalars(select(ContentItem).where(ContentItem.client_id == c.id)) if ai_posts.GROUP.get(i.status, "pending") == tab]
    if tab == "posted" and period != "lifetime":
        since = datetime.now(timezone.utc) - timedelta(days=PERIOD_DAYS[period])
        rows = [i for i in rows if i.published_at and ai_posts._aware(i.published_at) >= since]
    key = {"approved": lambda i: ai_posts._aware(i.scheduled_at) or datetime.max.replace(tzinfo=timezone.utc)}.get(
        tab, lambda i: -(ai_posts._aware(i.published_at or i.updated_at or i.created_at)).timestamp())
    rows.sort(key=key)
    kws = _kws(db, c)
    return {"tab": tab, "period": period, "items": [ai_posts.post_out(i, kws, c) for i in rows]}


def _post(db: Session, c: Client, post_id: int) -> ContentItem:
    item = db.scalar(select(ContentItem).where(ContentItem.id == post_id, ContentItem.client_id == c.id))
    if not item:
        raise HTTPException(404, "Post not found")
    return item


@router.get("/{client_id}/ai-posts/free-slot")
def free_slot(client_id: int, month: str | None = None, user: User = Depends(require_section("content")), db: Session = Depends(get_db)):
    c = _client(db, user, client_id)
    try:
        m = date.fromisoformat(f"{month}-01") if month else None
    except ValueError:
        raise HTTPException(422, "month must look like 2026-10")
    return ai_posts.free_slot(db, c, m)


@router.get("/{client_id}/ai-posts/{post_id}")
def get_post(client_id: int, post_id: int, user: User = Depends(require_section("content")), db: Session = Depends(get_db)):
    c = _client(db, user, client_id)
    return ai_posts.post_out(_post(db, c, post_id), _kws(db, c), c)


class PosterIn(BaseModel):
    item_id: int
    notes: str = Field("", max_length=300)


@router.post("/{client_id}/ai-posts/poster", status_code=201)
def make_poster(client_id: int, body: PosterIn, user: User = Depends(require_section("content")), db: Session = Depends(get_db)):
    c = _client(db, user, client_id, create=True)
    q = ai_posts.quota(db, c)["posts"]
    if q["used"] >= q["limit"]:
        raise HTTPException(429, f"You've used all {q['limit']} AI posts for this month")
    product = db.scalar(select(ProductItem).where(ProductItem.id == body.item_id, ProductItem.client_id == c.id))
    if not product:
        raise HTTPException(404, "Item not found")
    topic = product.name + (f" — {product.description}" if product.description else "") + (f" ({media.price_label(product.price)})" if product.price else "")
    item, meta = ai_posts.new_post(c, user.id, topic, "image", [product], body.notes)
    try:
        poster = media.render_poster(c.id, product.image_path, {"name": product.name, "description": product.description, "price": product.price},
                                     ai_posts.business(c))
    except (media.MediaError, OSError) as e:
        raise HTTPException(422, f"Couldn't create the poster: {e}")
    item.image_url = media.url(poster)
    db.add(item)
    db.flush()
    audit(db, user, f"AI poster created ({meta['source']}): {product.name}", client_id=c.id, entity_type="content", entity_id=item.id)
    db.commit()
    return ai_posts.post_out(item, _kws(db, c), c)


class VideoIn(BaseModel):
    template: str
    item_ids: list[int] = Field(default_factory=list, max_length=6)
    notes: str = Field("", max_length=300)


@router.post("/{client_id}/ai-posts/video", status_code=201)
def make_video(client_id: int, body: VideoIn, background: BackgroundTasks, user: User = Depends(require_section("content")), db: Session = Depends(get_db)):
    c = _client(db, user, client_id, create=True)
    if body.template not in ai_posts.TEMPLATE_BY_KEY:
        raise HTTPException(422, "Unknown video template")
    q = ai_posts.quota(db, c)["videos"]
    if q["used"] >= q["limit"]:
        raise HTTPException(429, f"You've used all {q['limit']} viral videos for this month")
    rows = list(db.scalars(select(ProductItem).where(ProductItem.client_id == c.id, ProductItem.image_path != "").order_by(ProductItem.id.desc())))
    products = [p for p in rows if p.id in body.item_ids] if body.item_ids else rows[:4]
    if not products:
        raise HTTPException(422, "Add a product with a photo first — the video is made from your products")
    t = ai_posts.TEMPLATE_BY_KEY[body.template]
    topic = f"{t['name']} video: " + ", ".join(p.name for p in products)
    item, meta = ai_posts.new_post(c, user.id, topic, "video", products, body.notes)
    item.status, item.template, item.gen_progress = "generating", t["key"], 0
    db.add(item)
    db.flush()
    audit(db, user, f"viral video requested ({t['name']})", client_id=c.id, entity_type="content", entity_id=item.id,
          details={"products": [p.id for p in products], "caption_source": meta["source"]})
    db.commit()
    if settings.celery_enabled:
        from ..celery_app import render_video_task
        render_video_task.delay(item.id)
    else:
        background.add_task(ai_posts.render_job, item.id)
    return ai_posts.post_out(item, _kws(db, c), c)


class ApproveIn(BaseModel):
    scheduled_at: datetime


@router.post("/{client_id}/ai-posts/{post_id}/approve")
def approve(client_id: int, post_id: int, body: ApproveIn, user: User = Depends(require_section("content")), db: Session = Depends(get_db)):
    """Approve the post and schedule it for the picked date and time."""
    c = _client(db, user, client_id)
    if not can_approve(db, user):
        raise HTTPException(403, "Your role cannot approve posts")
    item = _post(db, c, post_id)
    if item.status not in ("in_review", "draft", "rejected", "scheduled"):
        raise HTTPException(409, "This post is still being created" if item.status == "generating" else f"A {item.status.replace('_', ' ')} post can't be scheduled")
    _publishable(item)
    content_service.schedule(item, _check_schedule(body.scheduled_at))
    _approve(item, user)
    audit(db, user, f"approved & scheduled: {item.topic}", client_id=c.id, entity_type="content", entity_id=item.id,
          details={"scheduled_at": item.scheduled_at.isoformat()})
    db.commit()
    return ai_posts.post_out(item, _kws(db, c), c)


@router.post("/{client_id}/ai-posts/{post_id}/reject")
def reject(client_id: int, post_id: int, user: User = Depends(require_section("content")), db: Session = Depends(get_db)):
    c = _client(db, user, client_id)
    if not can_approve(db, user):
        raise HTTPException(403, "Your role cannot reject posts")
    item = _post(db, c, post_id)
    if item.status in ("published", "publishing", "generating"):
        raise HTTPException(409, f"A {item.status} post can't be rejected")
    item.status, item.approved_by, item.approved_at, item.updated_at = "rejected", None, None, datetime.now(timezone.utc)
    audit(db, user, f"rejected: {item.topic}", client_id=c.id, entity_type="content", entity_id=item.id)
    db.commit()
    return ai_posts.post_out(item, _kws(db, c), c)
