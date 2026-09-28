from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import ai
from ..db import get_db
from ..models import Client, ContentItem, ContentVariant, Tenant, User
from ..publishers import PublishError, publish_post
from ..security import audit, can, get_client, require, require_section, scoped_ids
from ..serializers import content_out

router = APIRouter(prefix="/api/content", tags=["content"])

Platform = Literal["gmb", "facebook", "instagram", "linkedin", "youtube", "x"]
ContentType = Literal["post", "offer", "event", "update"]


def available_platforms(c: Client) -> list[str]:
    return ["gmb"] + [a.platform for a in c.social_accounts]


def can_approve(db: Session, user: User) -> bool:
    """With client approval required, only the client-portal user can move content past review."""
    tenant = db.get(Tenant, user.tenant_id)
    return can(user, "content.approve") and (not tenant.require_client_approval or user.role == "client")


class GenerateIn(BaseModel):
    client_id: int
    topic: str = Field(min_length=2, max_length=300)
    content_type: ContentType = "post"
    platforms: list[Platform] = Field(min_length=1)


@router.post("/generate")
def generate(body: GenerateIn, user: User = Depends(require("content.create")), db: Session = Depends(get_db)):
    c = get_client(db, user, body.client_id)
    platforms = [p for p in body.platforms if p in available_platforms(c)]
    if not platforms:
        raise HTTPException(422, "None of the selected platforms are connected for this client")
    data, source = ai.generate_content(company=c.company_name, industry=c.industry, city=c.city, website=c.website, brand_voice=c.brand_voice,
                                       topic=body.topic, content_type=body.content_type, platforms=platforms)
    return {**data, "source": source}


class VariantIn(BaseModel):
    platform: Platform
    copy: str
    format: str


class ContentIn(BaseModel):
    client_id: int
    topic: str
    content_type: ContentType = "post"
    master_copy: str
    hashtags: list[str] = []
    creative_brief: str = ""
    variants: list[VariantIn] = Field(min_length=1)
    scheduled_at: datetime | None = None
    status: Literal["draft", "in_review", "scheduled"] = "draft"


@router.post("", status_code=201)
def create(body: ContentIn, user: User = Depends(require("content.create")), db: Session = Depends(get_db)):
    c = get_client(db, user, body.client_id)
    if body.status == "scheduled" and not can_approve(db, user):
        raise HTTPException(403, "This content needs approval before it can be scheduled")
    if body.status == "scheduled" and not body.scheduled_at:
        raise HTTPException(422, "Pick a schedule time")
    item = ContentItem(tenant_id=user.tenant_id, client_id=c.id, topic=body.topic, content_type=body.content_type, master_copy=body.master_copy,
                       hashtags=body.hashtags, creative_brief=body.creative_brief, status=body.status, scheduled_at=body.scheduled_at, created_by=user.id,
                       variants=[ContentVariant(**v.model_dump()) for v in body.variants])
    db.add(item)
    db.flush()
    audit(db, user, f"content {body.status.replace('_', ' ')}: {body.topic}", client_id=c.id, entity_type="content", entity_id=item.id)
    db.commit()
    return content_out(item, c.company_name)


@router.get("")
def list_content(client_id: int | None = None, status: str | None = None, month: str | None = None,
                 user: User = Depends(require_section("content")), db: Session = Depends(get_db)):
    """month=YYYY-MM limits to items scheduled in that month (calendar view)."""
    ids = scoped_ids(db, user, client_id)
    names = dict(db.execute(select(Client.id, Client.company_name).where(Client.id.in_(ids))).all())
    q = select(ContentItem).where(ContentItem.client_id.in_(ids)).order_by(ContentItem.scheduled_at.is_(None), ContentItem.scheduled_at)
    if status:
        q = q.where(ContentItem.status == status)
    items = list(db.scalars(q))
    if month:
        items = [i for i in items if i.scheduled_at and i.scheduled_at.strftime("%Y-%m") == month]
    return [content_out(i, names[i.client_id]) for i in items]


# Allowed transitions: action -> (from states, to state, permission check)
TRANSITIONS = {
    "submit": ({"draft"}, "in_review"),
    "request_changes": ({"in_review"}, "draft"),
    "approve": ({"in_review"}, "scheduled"),
    "publish": ({"scheduled", "failed"}, "published"),
}


@router.post("/{content_id}/{action}")
def transition(content_id: int, action: Literal["submit", "request_changes", "approve", "publish"],
               user: User = Depends(require_section("content")), db: Session = Depends(get_db)):
    item = db.get(ContentItem, content_id)
    if not item or item.tenant_id != user.tenant_id:
        raise HTTPException(404, "Content not found")
    c = get_client(db, user, item.client_id)
    sources, target = TRANSITIONS[action]
    if item.status not in sources:
        raise HTTPException(409, f"Cannot {action.replace('_', ' ')} content that is {item.status.replace('_', ' ')}")
    if action == "submit" and not can(user, "content.create"):
        raise HTTPException(403, "Your role cannot submit content")
    if action in ("approve", "request_changes") and not can_approve(db, user):
        raise HTTPException(403, "Your role cannot approve this content")
    if action == "publish":
        if not can(user, "content.publish"):
            raise HTTPException(403, "Your role cannot publish")
        retry = item.status == "failed"
        try:
            for v in item.variants:
                v.external_post_id = v.external_post_id or publish_post(c, v.platform, v.copy)
        except PublishError as e:
            item.status = "failed"
            audit(db, user, f"publish failed: {e}", client_id=c.id, entity_type="content", entity_id=item.id)
            db.commit()
            raise HTTPException(502, str(e))
        item.scheduled_at = datetime.now(timezone.utc)
        label = "retried publish" if retry else "published now"
    else:
        label = {"submit": "sent for approval", "request_changes": "requested changes", "approve": "approved & scheduled"}[action]
    item.status = target
    audit(db, user, f"{label}: {item.topic}", client_id=c.id, entity_type="content", entity_id=item.id)
    db.commit()
    return content_out(item, c.company_name)


@router.get("/platforms/{client_id}")
def platforms(client_id: int, user: User = Depends(require_section("content")), db: Session = Depends(get_db)):
    c = get_client(db, user, client_id)
    return {"platforms": available_platforms(c), "brand_voice": c.brand_voice, "can_schedule": can_approve(db, user)}
