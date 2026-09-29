from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import importer
from ..db import get_db
from ..google import api as google_api
from ..google import service as google_service
from ..metrics import compare, periods, series, totals
from ..models import Client, ClientContact, ContentItem, GmbAccount, Keyword, Report, Review, Task, User
from ..security import audit, get_client, require, require_section, visible_client_ids
from ..serializers import client_brief, client_out, content_out, keyword_out, report_out, review_out, task_out
from .common import user_names

router = APIRouter(prefix="/api/clients", tags=["clients"])


@router.get("")
def list_clients(q: str = "", industry: str | None = None, status: str | None = None, service: str | None = None,
                 user: User = Depends(require_section("dashboard")), db: Session = Depends(get_db)):
    ids = visible_client_ids(db, user)
    rows = db.scalars(select(Client).where(Client.id.in_(ids)).order_by(Client.company_name))
    pending_by_client = dict(db.execute(
        select(Review.client_id, func.count()).where(Review.client_id.in_(ids), Review.reply_status.in_(("new", "drafted", "approved"))).group_by(Review.client_id)
    ).all())
    out = []
    for c in rows:
        hay = f"{c.company_name} {c.city} {c.contacts[0].name if c.contacts else ''}".lower()
        if q and q.lower() not in hay:
            continue
        if (industry and c.industry != industry) or (status and c.status != status) or (service and service not in c.services):
            continue
        out.append({**client_brief(c), "services": c.services, "pending_reviews": pending_by_client.get(c.id, 0)})
    return out


@router.get("/facets")
def facets(user: User = Depends(require_section("clients")), db: Session = Depends(get_db)):
    clients = list(db.scalars(select(Client).where(Client.tenant_id == user.tenant_id)))
    return {"industries": sorted({c.industry for c in clients if c.industry}), "services": sorted({s for c in clients for s in c.services}), "statuses": ["active", "onboarding", "paused"]}


class ClientIn(BaseModel):
    company_name: str = Field(min_length=2, max_length=200)
    website: str = ""
    industry: str = ""
    city: str = ""
    plan: Literal["Starter", "Growth", "Pro", "Agency"] = "Starter"
    contact_name: str = ""
    contact_email: str = ""
    contact_phone: str = ""


@router.post("", status_code=201)
def create_client(body: ClientIn, user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    c = Client(tenant_id=user.tenant_id, company_name=body.company_name, website=body.website, industry=body.industry, city=body.city, plan=body.plan,
               services=["GMB Management", "Review Management"], account_manager_id=user.id,
               brand_voice={"tone": "Warm and professional", "preferred_phrases": [], "prohibited_claims": [], "cta_style": "Contact us", "languages": ["en"],
                            "escalation_rule": "Ratings of 2 or less go to the account manager before any reply is published."})
    if body.contact_name:
        c.contacts.append(ClientContact(tenant_id=user.tenant_id, name=body.contact_name, email=body.contact_email, phone=body.contact_phone, designation="Owner"))
    db.add(c)
    db.flush()
    audit(db, user, f"created client {c.company_name}", client_id=c.id, entity_type="client", entity_id=c.id)
    db.commit()
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


class ClientPatch(BaseModel):
    notes: str | None = None
    status: Literal["active", "onboarding", "paused"] | None = None
    auto_publish: dict[str, bool] | None = None
    brand_voice: dict | None = None


@router.patch("/{client_id}")
def update_client(client_id: int, body: ClientPatch, user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    c = get_client(db, user, client_id)
    changes = body.model_dump(exclude_none=True)
    for k, v in changes.items():
        setattr(c, k, v)
    if "auto_publish" in changes:
        on = [k for k, v in changes["auto_publish"].items() if v]
        audit(db, user, f"auto-publish now {'on for ' + ', '.join(on) if on else 'off everywhere'}", client_id=c.id, entity_type="client", entity_id=c.id)
    else:
        audit(db, user, f"updated {', '.join(changes)}", client_id=c.id, entity_type="client", entity_id=c.id)
    db.commit()
    return client_out(c)


@router.post("/{client_id}/gmb/sync")
def gmb_sync(client_id: int, user: User = Depends(require_section("gmb")), db: Session = Depends(get_db)):
    """Live profiles: pull reviews + insights from Google. Demo profiles: just mark them synced."""
    c = get_client(db, user, client_id)
    if c.gmb and c.gmb.is_live:
        try:
            result = google_service.sync_client(db, c)
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
