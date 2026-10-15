"""Business Score screen (mobile home for business owners): score, activity, stats, search keywords, competitors,
a printable report, and the competitor list behind the comparison."""

from datetime import date, datetime, timedelta, timezone
from html import escape

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import home
from .. import score as scoring
from ..config import settings
from ..db import get_db
from ..models import Client, Competitor, Keyword, KeywordSearchLog, User
from ..security import audit, get_client, require, require_section

router = APIRouter(prefix="/api/clients", tags=["score"])

REPORT_LINK_MINUTES = 15


@router.get("/{client_id}/score")
def business_score(client_id: int, user: User = Depends(require_section("dashboard")), db: Session = Depends(get_db)):
    """Everything on the owner's home screen in one call."""
    c = get_client(db, user, client_id)
    today = date.today()
    d = scoring.build(db, c, today)
    home.record_snapshot(db, c, d["score"]["value"], today)
    db.flush()
    track = home.tracker(db, c, today)
    kws = home.tracked(db, c)
    d.update(history=home.history(db, c, today), tracker=track, tracked_keywords=kws,
             actions=home.growth_actions(c, d, track, len(kws)), social=home.social(c), support=home.support(db, c),
             competitor_groups=home.competitor_groups(d["competitors"]))
    db.commit()
    return d


@router.get("/{client_id}/performance")
def google_performance(client_id: int, days: int = 30, user: User = Depends(require_section("dashboard")), db: Session = Depends(get_db)):
    if days not in (30, 60, 120):
        raise HTTPException(422, "days must be 30, 60 or 120")
    return home.performance(db, get_client(db, user, client_id), days, date.today())


@router.get("/{client_id}/calendar")
def social_calendar(client_id: int, month: str | None = None, user: User = Depends(require_section("dashboard")), db: Session = Depends(get_db)):
    try:
        first = date.fromisoformat(f"{month}-01") if month else date.today().replace(day=1)
    except ValueError:
        raise HTTPException(422, "month must look like 2026-10")
    return home.calendar(db, get_client(db, user, client_id), first)


# ---------- Keyword Planner ----------

@router.get("/{client_id}/keyword-planner")
def keyword_planner(client_id: int, user: User = Depends(require_section("dashboard")), db: Session = Depends(get_db)):
    c = get_client(db, user, client_id)
    return {"tracked": home.tracked(db, c), "credits": home.credits(db, c, date.today()), "country": "India", "city": c.city}


class KeywordSearchIn(BaseModel):
    keyword: str = Field(min_length=2, max_length=100)
    city: str = Field("", max_length=100)
    country: str = Field("India", max_length=60)


@router.post("/{client_id}/keyword-planner/search")
def keyword_search(client_id: int, body: KeywordSearchIn, user: User = Depends(require_section("dashboard")), db: Session = Depends(get_db)):
    c = get_client(db, user, client_id)
    cr = home.credits(db, c, date.today())
    if cr["used"] >= cr["limit"]:
        raise HTTPException(429, f"You've used all {cr['limit']} keyword searches for this month")
    db.add(KeywordSearchLog(tenant_id=c.tenant_id, client_id=c.id, user_id=user.id, keyword=body.keyword.strip(), city=body.city.strip()))
    db.commit()
    return {"keyword": body.keyword.strip(), "city": body.city.strip() or c.city, "results": home.ideas(db, c, body.keyword, body.city),
            "credits": home.credits(db, c, date.today())}


class TrackKeywordIn(BaseModel):
    keyword: str = Field(min_length=2, max_length=200)
    location: str = Field("", max_length=100)
    volume: int = Field(0, ge=0)


@router.post("/{client_id}/keyword-planner/keywords", status_code=201)
def track_keyword(client_id: int, body: TrackKeywordIn, user: User = Depends(require_section("dashboard")), db: Session = Depends(get_db)):
    c = get_client(db, user, client_id)
    kw = body.keyword.strip()
    if db.scalar(select(Keyword).where(Keyword.client_id == c.id, func.lower(Keyword.keyword) == kw.lower())):
        raise HTTPException(409, f'"{kw}" is already added')
    # Rank is filled in by the rank tracker; 100 = not ranked yet (same as the SEO screen)
    k = Keyword(tenant_id=c.tenant_id, client_id=c.id, keyword=kw, target_url=c.website, location=body.location.strip() or c.city,
                current_rank=100, previous_rank=100, volume=body.volume)
    db.add(k)
    db.flush()
    audit(db, user, f'tracking keyword "{kw}"', client_id=c.id, entity_type="seo_keyword", entity_id=k.id)
    db.commit()
    return {"id": k.id, "keyword": k.keyword, "location": k.location, "volume": k.volume}


@router.delete("/{client_id}/keyword-planner/keywords/{keyword_id}", status_code=204)
def untrack_keyword(client_id: int, keyword_id: int, user: User = Depends(require_section("dashboard")), db: Session = Depends(get_db)):
    c = get_client(db, user, client_id)
    k = db.scalar(select(Keyword).where(Keyword.id == keyword_id, Keyword.client_id == c.id))
    if not k:
        raise HTTPException(404, "Keyword not found")
    db.delete(k)
    audit(db, user, f'stopped tracking keyword "{k.keyword}"', client_id=c.id, entity_type="seo_keyword", entity_id=keyword_id)
    db.commit()


# ---------- printable report ----------

@router.post("/{client_id}/score/report-link")
def report_link(client_id: int, request: Request, user: User = Depends(require_section("dashboard")), db: Session = Depends(get_db)):
    """A short-lived link the phone can open in its browser (which can't send our bearer token) to view, print or
    save the report as PDF."""
    c = get_client(db, user, client_id)
    exp = datetime.now(timezone.utc) + timedelta(minutes=REPORT_LINK_MINUTES)
    token = jwt.encode({"purpose": "score_report", "cid": c.id, "tid": c.tenant_id, "exp": exp}, settings.jwt_secret, algorithm="HS256")
    return {"url": str(request.url_for("score_report", client_id=c.id).include_query_params(t=token)), "expires_at": exp.isoformat()}


@router.get("/{client_id}/score/report", response_class=HTMLResponse, name="score_report")
def score_report(client_id: int, t: str, db: Session = Depends(get_db)):
    try:
        claims = jwt.decode(t, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "This report link has expired — open the report again from the app")
    c = db.get(Client, client_id)
    if claims.get("purpose") != "score_report" or claims.get("cid") != client_id or not c or c.tenant_id != claims.get("tid"):
        raise HTTPException(401, "This report link is not valid")
    return HTMLResponse(render_report(scoring.build(db, c)))


def render_report(d: dict) -> str:
    c, s, st = d["client"], d["score"], d["stats"]
    colour = {"good": "#0f7a45", "ok": "#b7791f", "poor": "#c53030"}
    rows = "".join(
        f"<tr><td>{escape(i['label'])}<div class=muted>{escape(i['detail'])}</div></td>"
        f"<td class=num style='color:{colour[i['status']]}'>{i['points']}/{i['max']}</td><td class=tip>{escape(i['tip'])}</td></tr>"
        for i in s["items"])
    kws = "".join(f"<tr><td>{escape(k['keyword'])}</td><td class=num>{'<' if k['below_threshold'] else ''}{k['impressions']}</td></tr>"
                  for k in d["keywords"]["items"][:15]) or "<tr><td colspan=2 class=muted>No search data yet</td></tr>"
    rivals = "".join(f"<tr{' class=you' if x['is_you'] else ''}><td>{escape(x['name'])}{' (you)' if x['is_you'] else ''}</td>"
                     f"<td class=num>{x['rating']:.1f}★</td><td class=num>{x['review_count']}</td></tr>" for x in d["competitors"])
    today = date.today().strftime("%d %b %Y")
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Business Score — {escape(c['company_name'])}</title>
<style>
body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0;padding:16px;color:#14231b;background:#fff;max-width:820px;margin:auto}}
h1{{font-size:22px;margin:0}} h2{{font-size:16px;margin:24px 0 8px}} .muted{{color:#5b6b62;font-size:12px}}
.hero{{display:flex;gap:16px;align-items:center;border:1px solid #d9e3dd;border-radius:14px;padding:16px;margin-top:12px}}
.big{{font-size:44px;font-weight:800;color:#0f7a45}} .pill{{display:inline-block;background:#e3f2ea;color:#0f7a45;border-radius:99px;padding:2px 10px;font-size:12px;text-transform:capitalize}}
.grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}} .tile{{border:1px solid #d9e3dd;border-radius:12px;padding:10px}} .tile b{{font-size:20px;display:block}}
table{{width:100%;border-collapse:collapse;font-size:13px}} td,th{{border-bottom:1px solid #e6ece8;padding:7px 4px;text-align:left;vertical-align:top}}
.num{{text-align:right;white-space:nowrap;font-weight:600}} .tip{{color:#5b6b62;font-size:12px;width:45%}} tr.you td{{background:#eef7f2;font-weight:600}}
button{{background:#0f7a45;color:#fff;border:0;border-radius:10px;padding:10px 16px;font-size:14px;margin-top:16px}}
@media print{{button{{display:none}} body{{padding:0}}}}
</style></head><body>
<h1>{escape(c['company_name'])}</h1>
<div class=muted>{escape(' · '.join(filter(None, [c['industry'], c['city'], c['phone']])))} · Report date {today}</div>
<div class=hero><div class=big>{s['value']}%</div><div><span class=pill>{escape(s['label'])}</span>
<div class=muted style="margin-top:6px">Business Score out of 100, based on your Google rating, reviews, replies, posts and search visibility.</div></div></div>
<h2>Last 30 days</h2>
<div class=grid>
<div class=tile><span class=muted>Reply pending</span><b>{st['reply_pending']} / {st['reply_window']}</b></div>
<div class=tile><span class=muted>Reviews (lifetime)</span><b>{st['reviews_lifetime']} · {st['rating']:.1f}★</b></div>
<div class=tile><span class=muted>Profile views</span><b>{st['views_30d']:,}</b></div>
<div class=tile><span class=muted>Engagements</span><b>{st['engagements_30d']:,} ({st['engagement_rate']}%)</b></div>
</div>
<h2>Score breakdown and what to do</h2><table>{rows}</table>
<h2>Search keywords</h2><div class=muted>What people searched on Google before finding you</div>
<table><tr><th>Search keyword</th><th class=num>Appeared</th></tr>{kws}</table>
<h2>Competitor analysis</h2><table><tr><th>Business</th><th class=num>Rating</th><th class=num>Reviews</th></tr>{rivals}</table>
<button onclick="window.print()">Save as PDF / Print</button>
</body></html>"""


# ---------- competitors ----------

class CompetitorIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    rating: float = Field(0, ge=0, le=5)
    review_count: int = Field(0, ge=0)
    maps_uri: str = Field("", max_length=500)
    address: str = Field("", max_length=300)
    distance_km: float | None = Field(None, ge=0)


@router.post("/{client_id}/competitors", status_code=201)
def add_competitor(client_id: int, body: CompetitorIn, user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    c = get_client(db, user, client_id)
    db.execute(delete(Competitor).where(Competitor.client_id == c.id, Competitor.is_sample.is_(True)))  # real list replaces the demo one
    x = Competitor(tenant_id=c.tenant_id, client_id=c.id, name=body.name.strip(), rating=round(body.rating, 1), review_count=body.review_count,
                   maps_uri=body.maps_uri.strip(), address=body.address.strip(), distance_km=body.distance_km)
    db.add(x)
    db.flush()
    audit(db, user, f"added competitor {x.name}", client_id=c.id, entity_type="competitor", entity_id=x.id)
    db.commit()
    return {"id": x.id, "name": x.name, "rating": x.rating, "review_count": x.review_count, "maps_uri": x.maps_uri, "address": x.address,
            "distance_km": x.distance_km, "is_sample": False, "is_you": False}


@router.delete("/{client_id}/competitors/{competitor_id}", status_code=204)
def delete_competitor(client_id: int, competitor_id: int, user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    c = get_client(db, user, client_id)
    x = db.scalar(select(Competitor).where(Competitor.id == competitor_id, Competitor.client_id == c.id))
    if not x:
        raise HTTPException(404, "Competitor not found")
    db.delete(x)
    audit(db, user, f"removed competitor {x.name}", client_id=c.id, entity_type="competitor", entity_id=competitor_id)
    db.commit()
