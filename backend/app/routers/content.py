"""Content Studio API: AI post drafts, approval, scheduling (Celery + Redis, or in-process) and status tracking.

Statuses: draft, in_review (draft waiting for approval), scheduled, publishing (a worker is posting it), published, failed.
"""

from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import adapt, ai, content_service
from ..config import settings
from ..db import get_db
from ..models import Client, ContentItem, ContentVariant, Tenant, User
from ..security import audit, can, get_client, require, require_section, scoped_ids
from ..serializers import content_out

router = APIRouter(prefix="/api/content", tags=["content"])

ImageUrl = Annotated[str, Field(max_length=1000, pattern=r"^(https://\S+)?$", description="Public https image URL (required by Instagram)")]

Platform = Literal["gmb", "facebook", "instagram", "linkedin", "youtube", "x"]
ContentType = Literal["post", "offer", "event", "update"]
# Tabs in the UI: the four states people track, with the in-between states folded in
GROUPS = {"draft": ("draft", "in_review"), "scheduled": ("scheduled", "publishing"), "published": ("published",), "failed": ("failed",)}


def available_platforms(c: Client) -> list[str]:
    return ["gmb"] + [a.platform for a in c.social_accounts]


def can_approve(db: Session, user: User) -> bool:
    """With client approval required, only the client-portal user can move content past review."""
    tenant = db.get(Tenant, user.tenant_id)
    return can(user, "content.approve") and (not tenant.require_client_approval or user.role == "client")


def _platforms(c: Client, wanted: list[str]) -> list[str]:
    platforms = [p for p in wanted if p in available_platforms(c)]
    if not platforms:
        raise HTTPException(422, "None of the selected platforms are connected for this client")
    return platforms


def _ai(c: Client, topic: str, content_type: str, platforms: list[str], notes: str = "") -> tuple[dict, dict]:
    return ai.generate_content(company=c.company_name, industry=c.industry, city=c.city, website=c.website, brand_voice=c.brand_voice,
                               topic=topic, content_type=content_type, platforms=platforms, notes=notes)


def _ai_details(meta: dict) -> dict:
    return {k: meta[k] for k in ("source", "provider", "model", "usage", "ms", "request_id", "error") if meta.get(k) not in (None, "")}


class GenerateIn(BaseModel):
    client_id: int
    topic: str = Field(min_length=2, max_length=300)
    content_type: ContentType = "post"
    platforms: list[Platform] = Field(min_length=1)
    notes: str = Field(default="", max_length=500)


@router.post("/generate")
def generate(body: GenerateIn, user: User = Depends(require("content.create")), db: Session = Depends(get_db)):
    """Preview an AI draft (nothing saved)."""
    c = get_client(db, user, body.client_id)
    data, meta = _ai(c, body.topic, body.content_type, _platforms(c, body.platforms), body.notes)
    return {**data, "source": meta["source"], "ai": meta}


class DraftIn(GenerateIn):
    scheduled_at: datetime | None = None  # proposed time, kept on the draft
    image_url: ImageUrl = ""


@router.post("/draft", status_code=201)
def ai_draft(body: DraftIn, user: User = Depends(require("content.create")), db: Session = Depends(get_db)):
    """Generate an AI post for every selected platform and save it straight away as a Draft."""
    c = get_client(db, user, body.client_id)
    data, meta = _ai(c, body.topic, body.content_type, _platforms(c, body.platforms), body.notes)
    item = ContentItem(tenant_id=user.tenant_id, client_id=c.id, topic=body.topic, content_type=body.content_type, master_copy=data["master_copy"],
                       hashtags=data.get("hashtags", []), creative_brief=data.get("creative_brief", ""), status="draft",
                       scheduled_at=content_service.to_utc(body.scheduled_at), created_by=user.id, updated_at=content_service.utcnow(),
                       ai_source=meta["source"], ai_model=f"{meta['provider']}/{meta['model']}" if meta["source"] == "ai" else "", image_url=body.image_url,
                       variants=[ContentVariant(platform=v["platform"], copy=v["copy"], format=v["format"]) for v in data["variants"]])
    db.add(item)
    db.flush()
    audit(db, user, f"AI drafted post ({meta['source']}): {body.topic}", client_id=c.id, entity_type="content", entity_id=item.id,
          details={**_ai_details(meta), **({"notes": body.notes} if body.notes else {})})
    db.commit()
    return {**content_out(item, c.company_name), "ai": meta}


class VariantIn(BaseModel):
    platform: Platform
    copy: str = Field(min_length=1, max_length=5000)
    format: str = Field(default="1:1", max_length=10)


class ContentIn(BaseModel):
    client_id: int
    topic: str = Field(min_length=1, max_length=300)
    content_type: ContentType = "post"
    master_copy: str = ""
    hashtags: list[str] = []
    creative_brief: str = ""
    variants: list[VariantIn] = Field(min_length=1)
    scheduled_at: datetime | None = None
    status: Literal["draft", "in_review", "scheduled"] = "draft"
    ai_source: Literal["ai", "template", ""] = ""
    image_url: ImageUrl = ""


def _approve(item: ContentItem, user: User) -> None:
    item.approved_by, item.approved_at = user.id, content_service.utcnow()


def _unapprove(item: ContentItem) -> None:
    item.approved_by, item.approved_at = None, None


def _publishable(item: ContentItem) -> None:
    """Refuse to schedule a post a platform would reject (e.g. Instagram without an image, X over 280 chars)."""
    problems = adapt.blocking(item.variants, item.image_url or "")
    if problems:
        raise HTTPException(422, "Fix before scheduling: " + "; ".join(problems))


def _check_schedule(when: datetime | None) -> datetime:
    if not when:
        raise HTTPException(422, "Pick a publish date and time first")
    when = content_service.to_utc(when)
    if when < content_service.utcnow() - timedelta(minutes=5):
        raise HTTPException(422, "That time is in the past — pick a future time, or use Publish now")
    return when


@router.post("", status_code=201)
def create(body: ContentIn, user: User = Depends(require("content.create")), db: Session = Depends(get_db)):
    c = get_client(db, user, body.client_id)
    if body.status == "scheduled" and not can_approve(db, user):
        raise HTTPException(403, "This content needs approval before it can be scheduled")
    when = _check_schedule(body.scheduled_at) if body.status == "scheduled" else content_service.to_utc(body.scheduled_at)
    item = ContentItem(tenant_id=user.tenant_id, client_id=c.id, topic=body.topic, content_type=body.content_type, master_copy=body.master_copy,
                       hashtags=body.hashtags, creative_brief=body.creative_brief, status="draft", scheduled_at=when, created_by=user.id,
                       updated_at=content_service.utcnow(), ai_source=body.ai_source, image_url=body.image_url,
                       variants=[ContentVariant(**v.model_dump()) for v in body.variants])
    db.add(item)
    db.flush()
    if body.status == "scheduled":
        _publishable(item)
        content_service.schedule(item, when)
        _approve(item, user)  # created by someone allowed to approve: this is the approval
    else:
        item.status = body.status
    audit(db, user, f"content {body.status.replace('_', ' ')}: {body.topic}", client_id=c.id, entity_type="content", entity_id=item.id,
          details={"status": item.status, "scheduled_at": item.scheduled_at.isoformat() if item.scheduled_at else None,
                   "platforms": [v.platform for v in item.variants]})
    db.commit()
    return content_out(item, c.company_name)


@router.get("")
def list_content(client_id: int | None = None, status: str | None = None, month: str | None = None,
                 user: User = Depends(require_section("content")), db: Session = Depends(get_db)):
    """month=YYYY-MM limits to items scheduled in that month (calendar view). status = a raw status or a group
    (draft / scheduled / published / failed). Returns a plain list (see /api/content/board for counts)."""
    ids = scoped_ids(db, user, client_id)
    names = dict(db.execute(select(Client.id, Client.company_name).where(Client.id.in_(ids))).all())
    q = select(ContentItem).where(ContentItem.client_id.in_(ids)).order_by(ContentItem.scheduled_at.is_(None), ContentItem.scheduled_at)
    if status:
        q = q.where(ContentItem.status.in_(GROUPS.get(status, (status,))))
    items = list(db.scalars(q))
    if month:
        items = [i for i in items if i.scheduled_at and i.scheduled_at.strftime("%Y-%m") == month]
    return [content_out(i, names[i.client_id]) for i in items]


@router.get("/board")
def board(client_id: int | None = None, group: Literal["draft", "scheduled", "published", "failed", "all"] = "scheduled",
          user: User = Depends(require_section("content")), db: Session = Depends(get_db)):
    """Status tracking: counts per state and the items of one group, plus how the scheduler runs."""
    ids = scoped_ids(db, user, client_id)
    names = dict(db.execute(select(Client.id, Client.company_name).where(Client.id.in_(ids))).all())
    rows = list(db.scalars(select(ContentItem).where(ContentItem.client_id.in_(ids))))
    counts = {g: sum(r.status in states for r in rows) for g, states in GROUPS.items()}
    counts["all"] = len(rows)
    pick = [r for r in rows if group == "all" or r.status in GROUPS[group]]
    if group in ("published",):
        pick.sort(key=lambda r: content_service._aware(r.published_at or r.scheduled_at or r.created_at), reverse=True)
    elif group == "draft":
        pick.sort(key=lambda r: content_service._aware(r.updated_at or r.created_at), reverse=True)
    else:
        pick.sort(key=lambda r: content_service._aware(r.next_attempt_at or r.scheduled_at or r.created_at))
    return {"counts": counts, "items": [content_out(i, names[i.client_id]) for i in pick[:200]], "scheduler": scheduler_info()}


def scheduler_info() -> dict:
    if settings.celery_enabled:
        return {"mode": "celery", "detail": "Redis + Celery: beat checks every minute and a worker publishes due posts."}
    if settings.scheduler_minutes > 0:  # (ignored when Redis is set: Celery beat runs instead)
        return {"mode": "in_process", "detail": f"No Redis: the API publishes due posts every {settings.scheduler_minutes} min."}
    return {"mode": "off", "detail": "No scheduler running: set REDIS_URL and start Celery (or SCHEDULER_INTERVAL_MINUTES / cron). Publish now still works."}


def _load(db: Session, user: User, content_id: int) -> tuple[ContentItem, Client]:
    item = db.get(ContentItem, content_id)
    if not item or item.tenant_id != user.tenant_id:
        raise HTTPException(404, "Content not found")
    return item, get_client(db, user, item.client_id)


class ContentPatch(BaseModel):
    topic: str | None = Field(default=None, min_length=1, max_length=300)
    master_copy: str | None = None
    hashtags: list[str] | None = None
    creative_brief: str | None = None
    variants: list[VariantIn] | None = None  # copy per platform (platforms must already exist on the item)
    image_url: ImageUrl | None = None
    scheduled_at: datetime | None = None  # reschedule (scheduled items keep their status)


@router.patch("/{content_id}")
def edit(content_id: int, body: ContentPatch, user: User = Depends(require("content.create")), db: Session = Depends(get_db)):
    item, c = _load(db, user, content_id)
    changes = body.model_dump(exclude_unset=True)
    copy_fields = {"topic", "master_copy", "hashtags", "creative_brief", "variants", "image_url"} & set(changes)
    if item.status in ("published", "publishing"):
        raise HTTPException(409, f"Content that is {item.status} can't be edited")
    if copy_fields and item.status == "scheduled":
        raise HTTPException(409, "Unschedule it before changing the copy (it was approved as it is)")
    details: dict = {}
    for k in copy_fields - {"variants"}:
        details[k] = {"before": getattr(item, k), "after": changes[k]}
        setattr(item, k, changes[k])
    if body.variants is not None:
        by = {v.platform: v for v in item.variants}
        for v in body.variants:
            if v.platform not in by:
                raise HTTPException(422, f"This post has no {v.platform} version")
            if by[v.platform].copy != v.copy:
                details[f"copy_{v.platform}"] = {"before": by[v.platform].copy, "after": v.copy}
                by[v.platform].copy = v.copy
    if "scheduled_at" in changes:
        when = _check_schedule(body.scheduled_at) if item.status == "scheduled" else content_service.to_utc(body.scheduled_at)
        details["scheduled_at"] = {"before": item.scheduled_at.isoformat() if item.scheduled_at else None, "after": when.isoformat() if when else None}
        if item.status == "scheduled":
            content_service.schedule(item, when)
        else:
            item.scheduled_at = when
    if copy_fields and details and item.approved_at:
        # The approved text changed (e.g. a failed post being fixed): it must be approved again before it can go out.
        _unapprove(item)
        if item.status == "failed":
            item.status, item.next_attempt_at = "draft", None
        details["approval"] = "cleared — the copy changed after approval"
    item.updated_at = content_service.utcnow()
    verb = "rescheduled" if set(changes) == {"scheduled_at"} and item.status == "scheduled" else "edited"
    audit(db, user, f"{verb}: {item.topic}", client_id=c.id, entity_type="content", entity_id=item.id, details=details or None)
    db.commit()
    return content_out(item, c.company_name)


class AdaptIn(BaseModel):
    platforms: list[Platform] | None = None  # default: the post's current platforms; new connected ones are added


@router.post("/{content_id}/adapt")
def adapt_content(content_id: int, body: AdaptIn | None = None, user: User = Depends(require("content.create")), db: Session = Depends(get_db)):
    """Rewrite every platform version from the master copy (AI with the brand voice, or the rule-based adapter)."""
    item, c = _load(db, user, content_id)
    if item.status not in ("draft", "in_review", "failed"):
        raise HTTPException(409, "Unschedule it before adapting the copy")
    if not (item.master_copy or "").strip():
        raise HTTPException(422, "Write a master copy first")
    current = {v.platform: v for v in item.variants}
    if body and body.platforms:
        missing = [p for p in body.platforms if p not in available_platforms(c)]
        if missing:
            raise HTTPException(422, f"Not connected for {c.company_name}: {', '.join(missing)}")
    platforms = list(dict.fromkeys(body.platforms)) if body and body.platforms else [v.platform for v in item.variants]
    platforms = [p for p in platforms if not (p in current and current[p].status == "published")]  # never rewrite what's live
    variants, meta = ai.adapt_variants(company=c.company_name, industry=c.industry, city=c.city, website=c.website, brand_voice=c.brand_voice,
                                       topic=item.topic, master=item.master_copy, hashtags=item.hashtags or [], platforms=platforms)
    before = {p: current[p].copy for p in platforms if p in current}
    for v in variants:
        if v["platform"] in current:
            current[v["platform"]].copy, current[v["platform"]].format = v["copy"], v["format"]
        else:
            item.variants.append(ContentVariant(platform=v["platform"], copy=v["copy"], format=v["format"]))
    if item.approved_at:
        _unapprove(item)
        if item.status == "failed":
            item.status, item.next_attempt_at = "draft", None
    item.updated_at = content_service.utcnow()
    audit(db, user, f"adapted copy per platform ({meta['source']}): {item.topic}", client_id=c.id, entity_type="content", entity_id=item.id,
          details={**_ai_details(meta), "platforms": platforms, "before": before})
    db.commit()
    db.refresh(item)
    return {**content_out(item, c.company_name), "ai": meta}


@router.get("/calendar")
def calendar_view(start: str, days: int = 42, client_id: int | None = None, user: User = Depends(require_section("content")), db: Session = Depends(get_db)):
    """Posts with a time in [start, start+days): scheduled/publishing by their publish time, published by when they went
    out, drafts/failed by their planned time. start = YYYY-MM-DD (UTC)."""
    try:
        begin = content_service.to_utc(datetime.fromisoformat(start))
    except ValueError as e:
        raise HTTPException(422, "start must be YYYY-MM-DD") from e
    end = begin + timedelta(days=max(1, min(days, 62)))
    ids = scoped_ids(db, user, client_id)
    names = dict(db.execute(select(Client.id, Client.company_name).where(Client.id.in_(ids))).all())
    out = []
    for i in db.scalars(select(ContentItem).where(ContentItem.client_id.in_(ids))):
        at = content_service._aware(i.published_at if i.status == "published" and i.published_at else i.scheduled_at)
        if at and begin <= at < end:
            out.append({"id": i.id, "client_id": i.client_id, "client_name": names[i.client_id], "topic": i.topic, "status": i.status,
                        "at": at.isoformat(), "platforms": [{"platform": v.platform, "status": v.status} for v in i.variants],
                        "image_url": i.image_url or "", "last_error": i.last_error or "",
                        "group": next((g for g, st in GROUPS.items() if i.status in st), i.status)})
    out.sort(key=lambda x: x["at"])
    return {"start": begin.isoformat(), "end": end.isoformat(), "items": out}


Action = Literal["submit", "request_changes", "approve", "schedule", "unschedule", "publish", "retry"]


@router.post("/{content_id}/{action}")
def transition(content_id: int, action: Action, user: User = Depends(require_section("content")), db: Session = Depends(get_db)):
    """submit (draft→in_review), request_changes (in_review→draft), approve / schedule (→scheduled at its time),
    unschedule (scheduled→draft), publish (now) and retry (failed→publish now)."""
    item, c = _load(db, user, content_id)
    before = item.status

    def need(states: set[str]):
        if item.status not in states:
            raise HTTPException(409, f"Cannot {action.replace('_', ' ')} content that is {item.status.replace('_', ' ')}")

    if action == "submit":
        need({"draft"})
        if not can(user, "content.create"):
            raise HTTPException(403, "Your role cannot submit content")
        item.status = "in_review"
    elif action == "request_changes":
        need({"in_review"})
        if not can_approve(db, user):
            raise HTTPException(403, "Your role cannot approve this content")
        item.status = "draft"
        _unapprove(item)
    elif action in ("approve", "schedule"):
        need({"in_review"} if action == "approve" else {"draft", "in_review", "failed"})
        if not can_approve(db, user):
            raise HTTPException(403, "This content needs approval before it can be scheduled" if action == "schedule" else "Your role cannot approve this content")
        _publishable(item)
        content_service.schedule(item, _check_schedule(item.scheduled_at))
        _approve(item, user)
    elif action == "unschedule":
        need({"scheduled"})
        if not can_approve(db, user):
            raise HTTPException(403, "Your role cannot change the schedule")
        item.status, item.next_attempt_at, item.updated_at = "draft", None, content_service.utcnow()
        _unapprove(item)
    else:  # publish / retry: now
        need({"scheduled", "failed"} if action == "publish" else {"failed"})
        if not can(user, "content.publish"):
            raise HTTPException(403, "Your role cannot publish")
        if not item.approved_at:
            raise HTTPException(409, "This post hasn't been approved — approve & schedule it first")
        _publishable(item)
        content_service.schedule(item, content_service.utcnow())
        audit(db, user, f"{'retry' if before == 'failed' else 'publish now'} requested: {item.topic}", client_id=c.id, entity_type="content",
              entity_id=item.id, details={"from": before})
        db.commit()
        result = content_service.dispatch(db, item.id, user)
        db.refresh(item)
        if item.status == "failed":
            raise HTTPException(502, item.last_error or "Publishing failed")
        return {**content_out(item, c.company_name), "dispatch": result}
    item.updated_at = content_service.utcnow()
    label = {"submit": "sent for approval", "request_changes": "requested changes", "approve": "approved & scheduled", "schedule": "scheduled",
             "unschedule": "unscheduled"}[action]
    audit(db, user, f"{label}: {item.topic}", client_id=c.id, entity_type="content", entity_id=item.id,
          details={"from": before, "to": item.status, **({"scheduled_at": item.scheduled_at.isoformat()} if item.status == "scheduled" else {})})
    db.commit()
    return content_out(item, c.company_name)


@router.delete("/{content_id}")
def delete(content_id: int, user: User = Depends(require("content.create")), db: Session = Depends(get_db)):
    item, c = _load(db, user, content_id)
    if item.status in ("scheduled", "publishing", "published"):
        raise HTTPException(409, "Unschedule it first (published posts stay for the record)")
    audit(db, user, f"deleted content: {item.topic}", client_id=c.id, entity_type="content", entity_id=item.id, details={"status": item.status})
    db.delete(item)
    db.commit()
    return {"ok": True}


@router.get("/platforms/{client_id}")
def platforms(client_id: int, user: User = Depends(require_section("content")), db: Session = Depends(get_db)):
    c = get_client(db, user, client_id)
    return {"platforms": available_platforms(c), "brand_voice": c.brand_voice, "can_schedule": can_approve(db, user), "scheduler": scheduler_info()}
