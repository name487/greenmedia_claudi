from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from .. import importer
from ..db import get_db
from ..google import api as google_api
from .. import review_queue
from ..metrics import compare, periods, series, totals
from ..models import AuditLog, Client, ClientContact, Competitor, ContentItem, GmbAccount, Keyword, KeywordSearchLog, MetaConnectAttempt, MetricDaily, Report, Review, ScoreSnapshot, SearchKeyword, Task, User
from ..security import audit, get_client, require, require_section, visible_client_ids
from ..serializers import client_brief, client_out, contact_out, content_out, keyword_out, report_out, review_out, task_out
from .common import user_names

router = APIRouter(prefix="/api/clients", tags=["clients"])


SORTS = {
    "name": lambda r: r["company_name"].lower(),
    "rating": lambda r: -(r["rating"] or 0),
    "pending": lambda r: -r["pending_reviews"],
    "newest": lambda r: -r["id"],
}


@router.get("")
def list_clients(q: str = "", industry: str | None = None, status: str | None = None, service: str | None = None,
                 plan: str | None = None, manager_id: int | None = None, sort: Literal["name", "rating", "pending", "newest"] = "name",
                 user: User = Depends(require_section("dashboard")), db: Session = Depends(get_db)):
    """Search matches company, city, industry, website and any contact's name, email or phone."""
    ids = visible_client_ids(db, user)
    rows = db.scalars(select(Client).where(Client.id.in_(ids)))
    pending_by_client = dict(db.execute(
        select(Review.client_id, func.count()).where(Review.client_id.in_(ids), Review.reply_status.in_(("new", "drafted", "approved"))).group_by(Review.client_id)
    ).all())
    managers = user_names(db, user.tenant_id)
    needle = q.strip().lower()
    out = []
    for c in rows:
        if needle:
            hay = " ".join([c.company_name, c.city, c.industry, c.website, *[f"{x.name} {x.email} {x.phone}" for x in c.contacts]]).lower()
            if needle not in hay:
                continue
        if (industry and c.industry != industry) or (status and c.status != status) or (service and service not in c.services):
            continue
        if (plan and c.plan != plan) or (manager_id and c.account_manager_id != manager_id):
            continue
        out.append({**client_brief(c), "services": c.services, "pending_reviews": pending_by_client.get(c.id, 0),
                    "account_manager_id": c.account_manager_id, "account_manager_name": managers.get(c.account_manager_id)})
    out.sort(key=lambda r: (SORTS[sort](r), r["company_name"].lower()))
    return out


@router.get("/facets")
def facets(user: User = Depends(require_section("clients")), db: Session = Depends(get_db)):
    clients = list(db.scalars(select(Client).where(Client.tenant_id == user.tenant_id)))
    staff = db.execute(select(User.id, User.name).where(User.tenant_id == user.tenant_id, User.role != "client", User.status == "active").order_by(User.name)).all()
    return {"industries": sorted({c.industry for c in clients if c.industry}), "services": sorted(set(DEFAULT_SERVICES) | {s for c in clients for s in c.services}),
            "statuses": list(STATUSES), "plans": list(PLANS), "managers": [{"id": i, "name": n} for i, n in staff]}


PLANS = ("Starter", "Growth", "Pro", "Agency")
STATUSES = ("active", "onboarding", "paused")
DEFAULT_SERVICES = ["GMB Management", "Review Management", "Social Media", "SEO", "Monthly Reports"]
EMAIL = r"^([^@\s]+@[^@\s]+\.[^@\s]+)?$"  # empty allowed


def _website(v: str) -> str:
    v = v.strip()
    return v if not v or v.lower().startswith(("http://", "https://")) else "https://" + v


def _check_name(db: Session, tenant_id: int, name: str, exclude_id: int | None = None) -> str:
    name = name.strip()
    q = select(Client.id).where(Client.tenant_id == tenant_id, func.lower(Client.company_name) == name.lower())
    if exclude_id:
        q = q.where(Client.id != exclude_id)
    if db.scalar(q):
        raise HTTPException(409, f"A client named “{name}” already exists")
    return name


def _check_manager(db: Session, tenant_id: int, manager_id: int | None) -> int | None:
    if manager_id is None:
        return None
    m = db.get(User, manager_id)
    if not m or m.tenant_id != tenant_id or m.role == "client" or m.status != "active":
        raise HTTPException(422, "Account manager must be an active staff member")
    return m.id


class ContactIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(default="", max_length=200, pattern=EMAIL)
    phone: str = Field(default="", max_length=40)
    designation: str = Field(default="", max_length=80)
    is_primary: bool = False


class ClientIn(BaseModel):
    company_name: str = Field(min_length=2, max_length=200)
    website: str = Field(default="", max_length=300)
    industry: str = Field(default="", max_length=100)
    city: str = Field(default="", max_length=100)
    plan: Literal["Starter", "Growth", "Pro", "Agency"] = "Starter"
    status: Literal["active", "onboarding", "paused"] = "onboarding"
    services: list[str] | None = None
    account_manager_id: int | None = None
    notes: str = ""
    # Convenience for a first contact (the web "Add client" form); or send `contacts`.
    contact_name: str = ""
    contact_email: str = Field(default="", pattern=EMAIL)
    contact_phone: str = ""
    contacts: list[ContactIn] = []


@router.post("", status_code=201)
def create_client(body: ClientIn, user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    name = _check_name(db, user.tenant_id, body.company_name)
    manager = _check_manager(db, user.tenant_id, body.account_manager_id) or user.id
    c = Client(tenant_id=user.tenant_id, company_name=name, website=_website(body.website), industry=body.industry.strip(), city=body.city.strip(),
               plan=body.plan, status=body.status, services=[x.strip() for x in (body.services or ["GMB Management", "Review Management"]) if x.strip()],
               account_manager_id=manager, notes=body.notes,
               brand_voice={"tone": "Warm and professional", "preferred_phrases": [], "prohibited_claims": [], "cta_style": "Contact us", "languages": ["en"],
                            "escalation_rule": "Ratings of 2 or less go to the account manager before any reply is published."})
    contacts = list(body.contacts)
    if body.contact_name.strip():
        contacts.insert(0, ContactIn(name=body.contact_name.strip(), email=body.contact_email, phone=body.contact_phone, designation="Owner"))
    for i, x in enumerate(contacts):
        primary = x.is_primary or (i == 0 and not any(y.is_primary for y in contacts))
        c.contacts.append(ClientContact(tenant_id=user.tenant_id, name=x.name.strip(), email=x.email.strip().lower(), phone=x.phone.strip(),
                                        designation=x.designation.strip(), is_primary=primary))
    db.add(c)
    db.flush()
    audit(db, user, f"created client {c.company_name}", client_id=c.id, entity_type="client", entity_id=c.id)
    db.commit()
    db.refresh(c)
    return client_out(c)


class ImportIn(BaseModel):
    csv: str = Field(max_length=5_000_000)


@router.get("/import/template", response_class=PlainTextResponse)
def import_template(user: User = Depends(require("client.edit"))):
    return PlainTextResponse(importer.TEMPLATE, headers={"Content-Disposition": "attachment; filename=clients-template.csv"})


@router.post("/import")
def import_clients(body: ImportIn, user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    """Bulk-create clients from CSV text. All-or-nothing on validation errors; existing names are skipped."""
    out = importer.import_clients(db, user.tenant_id, user.id, body.csv)
    if out["errors"]:
        raise HTTPException(422, {"errors": out["errors"]})
    return out


@router.get("/{client_id}")
def client_detail(client_id: int, user: User = Depends(require_section("dashboard")), db: Session = Depends(get_db)):
    c = get_client(db, user, client_id)
    (cs, ce), (ps, pe) = periods(30)
    users = user_names(db, user.tenant_id)
    name = c.company_name
    return {
        **client_out(c),
        "account_manager_name": users.get(c.account_manager_id),
        "kpis": compare(totals(db, [c.id], cs, ce), totals(db, [c.id], ps, pe)),
        "reviews": [review_out(r, name) for r in db.scalars(select(Review).where(Review.client_id == c.id).order_by(Review.created_at.desc()).limit(5))],
        "content": [content_out(x, name) for x in db.scalars(select(ContentItem).where(ContentItem.client_id == c.id).order_by(ContentItem.scheduled_at))],
        "keywords": [keyword_out(k, name) for k in db.scalars(select(Keyword).where(Keyword.client_id == c.id))],
        "open_tasks": [task_out(t, name, users.get(t.assigned_to)) for t in db.scalars(select(Task).where(Task.client_id == c.id, Task.status != "done"))],
        "reports": [report_out(r, name) for r in db.scalars(select(Report).where(Report.client_id == c.id).order_by(Report.created_at.desc()))],
    }


class BrandVoiceIn(BaseModel):
    """Per-client brand voice. It becomes the AI prompt for review replies (and shapes content). Fields not sent are kept."""
    tone: str | None = Field(default=None, max_length=200)
    preferred_phrases: list[Annotated[str, Field(max_length=150)]] | None = Field(default=None, max_length=15)
    prohibited_claims: list[Annotated[str, Field(max_length=150)]] | None = Field(default=None, max_length=15)
    cta_style: str | None = Field(default=None, max_length=150)
    sign_off: str | None = Field(default=None, max_length=150)
    reply_length: Literal["short", "medium", "long"] | None = None
    languages: list[Annotated[str, Field(min_length=2, max_length=10)]] | None = Field(default=None, max_length=8)
    review_prompt: str | None = Field(default=None, max_length=2000)  # free-text instructions for review replies
    escalation_rule: str | None = Field(default=None, max_length=300)


def merge_brand_voice(current: dict, body: BrandVoiceIn) -> dict:
    out = dict(current or {})
    for k, v in body.model_dump(exclude_unset=True).items():
        if isinstance(v, list):
            v = [x.strip() for x in v if x and x.strip()]
        elif isinstance(v, str):
            v = v.strip()
        out[k] = v
    return out


class ClientPatch(BaseModel):
    company_name: str | None = Field(default=None, min_length=2, max_length=200)
    website: str | None = Field(default=None, max_length=300)
    industry: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)
    plan: Literal["Starter", "Growth", "Pro", "Agency"] | None = None
    status: Literal["active", "onboarding", "paused"] | None = None
    services: list[str] | None = None
    account_manager_id: int | None = None
    notes: str | None = None
    auto_publish: dict[str, bool] | None = None
    brand_voice: BrandVoiceIn | None = None


@router.patch("/{client_id}")
def update_client(client_id: int, body: ClientPatch, user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    c = get_client(db, user, client_id)
    changes = body.model_dump(exclude_unset=True)
    changes = {k: v for k, v in changes.items() if v is not None or k == "account_manager_id"}
    if "company_name" in changes:
        changes["company_name"] = _check_name(db, user.tenant_id, changes["company_name"], exclude_id=c.id)
    if "website" in changes:
        changes["website"] = _website(changes["website"])
    if "services" in changes:
        changes["services"] = [x.strip() for x in changes["services"] if x.strip()]
    if "account_manager_id" in changes:
        changes["account_manager_id"] = _check_manager(db, user.tenant_id, changes["account_manager_id"])
    for k in ("industry", "city"):
        if k in changes:
            changes[k] = changes[k].strip()
    voice_before = dict(c.brand_voice or {})
    if "brand_voice" in changes:
        changes["brand_voice"] = merge_brand_voice(c.brand_voice, body.brand_voice)
    for k, v in changes.items():
        setattr(c, k, v)
    if "auto_publish" in changes:
        on = [k for k, v in changes["auto_publish"].items() if v]
        audit(db, user, f"auto-publish now {'on for ' + ', '.join(on) if on else 'off everywhere'}", client_id=c.id, entity_type="client", entity_id=c.id)
    elif changes:
        changed_voice = {k: {"before": voice_before.get(k), "after": v} for k, v in (changes.get("brand_voice") or {}).items() if voice_before.get(k) != v}
        audit(db, user, f"updated {', '.join(changes)}", client_id=c.id, entity_type="client", entity_id=c.id,
              details={"brand_voice": changed_voice} if changed_voice else None)
    db.commit()
    return client_out(c)


@router.delete("/{client_id}")
def delete_client(client_id: int, confirm_name: str, user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    """Permanently delete a client and everything recorded for it (reviews, content, metrics, tasks, reports,
    keywords, contacts, connected accounts). The audit log keeps its history. Client-portal logins for this
    client are disabled. The caller must retype the company name (?confirm_name=...)."""
    c = get_client(db, user, client_id)
    if confirm_name.strip().lower() != c.company_name.lower():
        raise HTTPException(422, "Type the client's exact name to confirm deletion")
    name, cid = c.company_name, c.id
    counts = {
        "reviews": db.execute(delete(Review).where(Review.client_id == cid)).rowcount,
        "content": len(list(db.scalars(select(ContentItem.id).where(ContentItem.client_id == cid)))),
        "keywords": db.execute(delete(Keyword).where(Keyword.client_id == cid)).rowcount,
        "metric_days": db.execute(delete(MetricDaily).where(MetricDaily.client_id == cid)).rowcount,
        "tasks": db.execute(delete(Task).where(Task.client_id == cid)).rowcount,
        "reports": db.execute(delete(Report).where(Report.client_id == cid)).rowcount,
        "search_keywords": db.execute(delete(SearchKeyword).where(SearchKeyword.client_id == cid)).rowcount,
        "competitors": db.execute(delete(Competitor).where(Competitor.client_id == cid)).rowcount,
    }
    db.execute(delete(ScoreSnapshot).where(ScoreSnapshot.client_id == cid))
    db.execute(delete(KeywordSearchLog).where(KeywordSearchLog.client_id == cid))
    db.execute(delete(MetaConnectAttempt).where(MetaConnectAttempt.client_id == cid))
    for item in db.scalars(select(ContentItem).where(ContentItem.client_id == cid)):
        db.delete(item)  # ORM delete so content variants go with it
    db.flush()  # dependents must be gone before the client row (PostgreSQL enforces the foreign keys)
    portal = list(db.scalars(select(User).where(User.client_id == cid)))
    for u in portal:
        u.client_id, u.status = None, "disabled"
    db.execute(update(AuditLog).where(AuditLog.client_id == cid).values(client_id=None))
    db.delete(c)  # contacts, GMB and social accounts cascade
    db.flush()
    audit(db, user, f"deleted client {name} ({', '.join(f'{v} {k}' for k, v in counts.items() if v) or 'no data'}"
                    f"{f'; disabled {len(portal)} portal login(s)' if portal else ''})", entity_type="client", entity_id=cid)
    db.commit()
    return {"deleted": True, "removed": counts, "disabled_portal_users": [u.email for u in portal]}


# ---------- contacts ----------

def _contact(db: Session, c: Client, contact_id: int) -> ClientContact:
    x = db.get(ClientContact, contact_id)
    if not x or x.client_id != c.id:
        raise HTTPException(404, "Contact not found")
    return x


def _make_primary(c: Client, x: ClientContact) -> None:
    for other in c.contacts:
        other.is_primary = other.id == x.id


@router.get("/{client_id}/contacts")
def list_contacts(client_id: int, user: User = Depends(require_section("dashboard")), db: Session = Depends(get_db)):
    return [contact_out(x) for x in get_client(db, user, client_id).contacts]


@router.post("/{client_id}/contacts", status_code=201)
def add_contact(client_id: int, body: ContactIn, user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    c = get_client(db, user, client_id)
    x = ClientContact(tenant_id=user.tenant_id, client_id=c.id, name=body.name.strip(), email=body.email.strip().lower(), phone=body.phone.strip(),
                      designation=body.designation.strip(), is_primary=False)
    db.add(x)
    db.flush()
    db.refresh(c)
    if body.is_primary or len(c.contacts) == 1:
        _make_primary(c, x)
    audit(db, user, f"added contact {x.name}", client_id=c.id, entity_type="client_contact", entity_id=x.id)
    db.commit()
    return contact_out(x)


class ContactPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    email: str | None = Field(default=None, max_length=200, pattern=EMAIL)
    phone: str | None = Field(default=None, max_length=40)
    designation: str | None = Field(default=None, max_length=80)
    is_primary: bool | None = None


@router.patch("/{client_id}/contacts/{contact_id}")
def update_contact(client_id: int, contact_id: int, body: ContactPatch, user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    c = get_client(db, user, client_id)
    x = _contact(db, c, contact_id)
    changes = body.model_dump(exclude_none=True)
    for k in ("name", "email", "phone", "designation"):
        if k in changes:
            setattr(x, k, changes[k].strip().lower() if k == "email" else changes[k].strip())
    if changes.get("is_primary"):
        _make_primary(c, x)
    audit(db, user, f"updated contact {x.name}", client_id=c.id, entity_type="client_contact", entity_id=x.id)
    db.commit()
    return contact_out(x)


@router.delete("/{client_id}/contacts/{contact_id}")
def delete_contact(client_id: int, contact_id: int, user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    c = get_client(db, user, client_id)
    x = _contact(db, c, contact_id)
    was_primary, name = x.is_primary, x.name
    c.contacts.remove(x)  # delete-orphan removes the row
    db.flush()
    if was_primary and c.contacts:
        _make_primary(c, c.contacts[0])  # promote the next contact so there is always a primary
    audit(db, user, f"removed contact {name}", client_id=c.id, entity_type="client_contact", entity_id=contact_id)
    db.commit()
    return {"deleted": True}


@router.post("/{client_id}/gmb/sync")
def gmb_sync(client_id: int, user: User = Depends(require_section("gmb")), db: Session = Depends(get_db)):
    """Live profiles: pull reviews + insights from Google. Demo profiles: just mark them synced."""
    c = get_client(db, user, client_id)
    if c.gmb and c.gmb.is_live:
        try:
            result = review_queue.sync_live(db, c)
        except google_api.GoogleApiError as e:
            db.commit()  # keep the recorded error/status
            raise HTTPException(502, str(e))
        audit(db, user, f"Google sync: {result['new_reviews']} new reviews", client_id=c.id, entity_type="gmb_account", entity_id=c.gmb.id)
        db.commit()
        return {**client_out(c), "sync": result}
    was = c.gmb.status if c.gmb else None
    if not c.gmb:
        c.gmb = GmbAccount(tenant_id=user.tenant_id, location_id="locations/pending")
    c.gmb.status = "connected"
    c.gmb.last_sync = datetime.now(timezone.utc)
    audit(db, user, "GMB sync" if was == "connected" else "GMB connected", client_id=c.id, entity_type="gmb_account", entity_id=c.gmb.id or "")
    db.commit()
    return client_out(c)


@router.post("/{client_id}/social/{platform}/reconnect")
def reconnect(client_id: int, platform: str, user: User = Depends(require_section("social")), db: Session = Depends(get_db)):
    c = get_client(db, user, client_id)
    acct = next((a for a in c.social_accounts if a.platform == platform), None)
    if not acct:
        raise HTTPException(404, "Account not found")
    acct.status = "connected"
    audit(db, user, f"reconnected {platform}", client_id=c.id, entity_type="social_account", entity_id=acct.id)
    db.commit()
    return client_out(c)


@router.get("/{client_id}/insights")
def gmb_insights(client_id: int, days: int = 45, user: User = Depends(require_section("gmb")), db: Session = Depends(get_db)):
    """Daily GMB insight series for one client (GMB Center chart)."""
    c = get_client(db, user, client_id)
    (cs, ce), _ = periods(max(7, min(days, 90)))
    return [{k: d[k] for k in ("date", "gmb_views", "gmb_calls", "gmb_directions", "web_clicks")} for d in series(db, [c.id], cs, ce)]
