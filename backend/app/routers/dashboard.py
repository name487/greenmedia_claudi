from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai import pct
from ..db import get_db
from ..metrics import periods, series, totals
from ..models import Client, ContentItem, Keyword, Review, User
from ..security import require_section, visible_client_ids
from ..serializers import client_brief, review_out
from .common import client_names

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

PENDING = ("new", "drafted", "approved")


@router.get("")
def dashboard(user: User = Depends(require_section("dashboard")), db: Session = Depends(get_db)):
    ids = visible_client_ids(db, user)
    names = client_names(db, user.tenant_id)
    clients = list(db.scalars(select(Client).where(Client.id.in_(ids)).order_by(Client.company_name)))
    (cs, ce), (ps, pe) = periods(30)
    cur, prev = totals(db, ids, cs, ce), totals(db, ids, ps, pe)

    pending = list(db.scalars(select(Review).where(Review.client_id.in_(ids), Review.reply_status.in_(PENDING)).order_by(Review.created_at.desc())))
    negative = [r for r in pending if r.sentiment == "negative"]
    content = list(db.scalars(select(ContentItem).where(ContentItem.client_id.in_(ids))))
    seo_alerts = list(db.scalars(select(Keyword).where(Keyword.client_id.in_(ids), Keyword.current_rank - Keyword.previous_rank >= 3)))

    perf = []
    for c in clients:
        cc, pp = totals(db, [c.id], cs, ce), totals(db, [c.id], ps, pe)
        perf.append({**client_brief(c), "gmb_views": cc["gmb_views"], "leads": cc["leads"], "leads_change_pct": pct(cc["leads"], pp["leads"]),
                     "pending_reviews": sum(1 for r in pending if r.client_id == c.id)})
    perf.sort(key=lambda x: (-x["pending_reviews"], -x["leads"]))

    return {
        "kpis": {
            "active_clients": sum(c.status == "active" for c in clients),
            "onboarding_clients": sum(c.status == "onboarding" for c in clients),
            "gmb_connected": sum(bool(c.gmb and c.gmb.status == "connected") for c in clients),
            "gmb_disconnected": sum(not (c.gmb and c.gmb.status == "connected") for c in clients),
            "pending_reviews": len(pending),
            "negative_reviews": len(negative),
            "scheduled_posts": sum(c.status == "scheduled" for c in content),
            "failed_posts": sum(c.status == "failed" for c in content),
            "leads": cur["leads"], "leads_change_pct": pct(cur["leads"], prev["leads"]),
            "seo_alerts": len(seo_alerts),
        },
        "growth": [{"date": d["date"], "gmb_views": d["gmb_views"], "social_reach": d["social_reach"], "leads": d["leads"]} for d in series(db, ids, cs, ce)],
        "negative_reviews": [review_out(r, names[r.client_id]) for r in negative[:5]],
        "seo_alerts": [{"keyword": k.keyword, "client_name": names[k.client_id], "previous_rank": k.previous_rank, "current_rank": k.current_rank} for k in seo_alerts[:5]],
        "client_performance": perf,
        "lead_sources": {"calls": cur["gmb_calls"], "directions": cur["gmb_directions"], "website_clicks": cur["web_clicks"], "social_engagement": cur["engagement"]},
    }
