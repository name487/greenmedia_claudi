from datetime import datetime, timedelta, timezone
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import ai
from ..db import get_db
from ..metrics import compare, periods, totals
from ..models import ContentItem, Keyword, Report, Review, User
from ..security import audit, get_client, require, require_section
from ..serializers import keyword_out, report_out

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("")
def list_reports(client_id: int, user: User = Depends(require_section("reports")), db: Session = Depends(get_db)):
    c = get_client(db, user, client_id)
    return [report_out(r, c.company_name) for r in db.scalars(select(Report).where(Report.client_id == c.id).order_by(Report.created_at.desc()))]


class GenerateIn(BaseModel):
    client_id: int


@router.post("/generate", status_code=201)
def generate(body: GenerateIn, user: User = Depends(require("report.deliver")), db: Session = Depends(get_db)):
    c = get_client(db, user, body.client_id)
    (cs, ce), (ps, pe) = periods(30)
    kws = list(db.scalars(select(Keyword).where(Keyword.client_id == c.id)))
    since = datetime.now(timezone.utc) - timedelta(days=30)
    replied = db.scalar(select(func.count()).select_from(Review).where(Review.client_id == c.id, Review.reply_status == "published", Review.published_at >= since))
    posts = db.scalar(select(func.count()).select_from(ContentItem).where(ContentItem.client_id == c.id, ContentItem.status == "published"))
    summary, source = ai.report_summary(company=c.company_name, industry=c.industry, current=totals(db, [c.id], cs, ce), previous=totals(db, [c.id], ps, pe),
                                        rank_up=sum(k.current_rank < k.previous_rank for k in kws), rank_down=sum(k.current_rank > k.previous_rank for k in kws),
                                        reviews_replied=replied, posts_published=posts)
    r = Report(tenant_id=user.tenant_id, client_id=c.id, period_start=cs, period_end=ce, summary=summary, source=source)
    db.add(r)
    db.flush()
    audit(db, user, f"generated report ({source})", client_id=c.id, entity_type="report", entity_id=r.id)
    db.commit()
    return report_out(r, c.company_name)


def _load(db: Session, user: User, report_id: int) -> tuple[Report, object]:
    r = db.get(Report, report_id)
    if not r or r.tenant_id != user.tenant_id:
        raise HTTPException(404, "Report not found")
    return r, get_client(db, user, r.client_id)


@router.get("/{report_id}")
def detail(report_id: int, user: User = Depends(require_section("reports")), db: Session = Depends(get_db)):
    r, c = _load(db, user, report_id)
    days = (r.period_end - r.period_start).days + 1
    prev_end = r.period_start - timedelta(days=1)
    kpis = compare(totals(db, [c.id], r.period_start, r.period_end), totals(db, [c.id], prev_end - timedelta(days=days - 1), prev_end))
    return {**report_out(r, c.company_name), "kpis": kpis, "keywords": [keyword_out(k, c.company_name) for k in db.scalars(select(Keyword).where(Keyword.client_id == c.id))]}


class DeliverIn(BaseModel):
    via: Literal["email", "whatsapp"]


@router.post("/{report_id}/deliver")
def deliver(report_id: int, body: DeliverIn, user: User = Depends(require("report.deliver")), db: Session = Depends(get_db)):
    """Marks the report delivered and returns a share link (mailto / wa.me) for the client app to open.
    Production: send through an email provider and the WhatsApp Business API from here instead."""
    r, c = _load(db, user, report_id)
    contact = c.contacts[0] if c.contacts else None
    text = f"{c.company_name} — Monthly marketing report ({r.period_start:%d %b} – {r.period_end:%d %b %Y})\n\n{r.summary}\n\n— Green Media Technology"
    if body.via == "email":
        url = f"mailto:{contact.email if contact else ''}?subject={quote(f'Your monthly marketing report — {c.company_name}')}&body={quote(text)}"
    else:
        phone = "".join(ch for ch in (contact.phone if contact else "") if ch.isdigit())
        url = f"https://wa.me/{phone}?text={quote(text)}"
    r.delivered_at, r.delivered_via = datetime.now(timezone.utc), body.via
    audit(db, user, f"delivered report via {body.via}", client_id=c.id, entity_type="report", entity_id=r.id)
    db.commit()
    return {**report_out(r, c.company_name), "share_url": url}
