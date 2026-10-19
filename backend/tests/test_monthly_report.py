"""The owner's monthly report: Performance Summary against the month before, Growth Action Report (achieved vs target by
week and by month), Performance Report (12-month trends with insights), and the PDF behind a signed link."""

import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app import content_service
from app import monthly_report as mr
from app.db import SessionLocal
from app.models import ContentItem, MetricDaily

from .test_google_media import _add, _sweep


def _sum(month: date, col: str) -> int:
    with SessionLocal() as db:
        rows = db.scalars(select(MetricDaily).where(MetricDaily.client_id == 1, MetricDaily.date.between(month, mr.month_end(month))))
        return sum(getattr(r, col) for r in rows)


def test_summary_growth_and_trends(client, portal):
    r = client.get("/api/clients/1/monthly-report", headers=portal).json()
    month = mr.default_month()
    assert r["month"] == month.isoformat()[:7] and r["month_label"] == month.strftime("%b %y")
    assert r["previous_label"] == mr.add_months(month, -1).strftime("%b %y")
    tiles = {s["key"]: s for s in r["summary"]}
    assert list(tiles) == ["views", "leads", "calls", "directions", "media", "engagement", "replies", "posts", "website"]
    views, prev = _sum(month, "gmb_views"), _sum(mr.add_months(month, -1), "gmb_views")
    assert tiles["views"]["value"] == views and tiles["views"]["previous"] == prev
    assert tiles["views"]["change_pct"] == round((views - prev) * 100 / prev, 1)
    eng = _sum(month, "gmb_calls") + _sum(month, "gmb_directions") + _sum(month, "web_clicks")
    assert tiles["engagement"]["value"] == round(eng * 100 / views, 1) and tiles["engagement"]["unit"] == "%"

    growth = {g["key"]: g for g in r["growth"]}
    assert list(growth) == ["posts", "media", "replies"]
    weeks = growth["posts"]["periods"]["last_month"]
    assert [w["label"] for w in weeks][:4] == ["W1", "W2", "W3", "W4"] and weeks[0]["target"] == 5
    assert sum(1 for _ in weeks) == (5 if mr.month_end(month).day > 28 else 4)
    assert [len(growth["media"]["periods"][p]) for p in ("3m", "6m", "12m")] == [3, 6, 12]
    assert growth["media"]["periods"]["6m"][-1]["label"] == r["month_label"]

    trends = {t["key"]: t for t in r["trends"]}
    assert list(trends) == ["score", "views", "engagements", "leads", "calls", "directions", "conversion"]
    assert all(len(t["points"]) == 12 for t in trends.values())
    assert trends["views"]["points"][-1]["value"] == views and trends["score"]["has_data"]  # the demo has a year of history
    assert "Smile Dental Studio saw a" in trends["views"]["insight"] or "held steady" in trends["views"]["insight"]


def test_this_months_actions_count_against_targets(client, portal):
    this = date.today().isoformat()[:7]

    def now():
        r = client.get("/api/clients/1/monthly-report", headers=portal, params={"month": this}).json()
        growth = {g["key"]: g for g in r["growth"]}
        return ({s["key"]: s["value"] for s in r["summary"]}, sum(w["achieved"] for w in growth["posts"]["periods"]["last_month"]),
                growth["media"]["periods"]["3m"][-1]["achieved"])

    before = now()
    _add(client, portal)  # a photo, uploaded now
    _sweep()
    gp = client.post("/api/clients/1/google-posts/generate", headers=portal, json={}).json()
    client.post(f"/api/clients/1/ai-posts/{gp['id']}/approve", headers=portal,
                json={"scheduled_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()})
    with SessionLocal() as db:  # due now: the scheduler publishes it
        db.get(ContentItem, gp["id"]).scheduled_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
        assert content_service.publish_due(db)["published"] == 1
    tiles, posts, media = now()
    assert tiles["media"] == before[0]["media"] + 1 and tiles["posts"] == before[0]["posts"] + 1
    assert posts == before[1] + 1 and media == before[2] + 1

def test_month_validation_and_access(client, portal):
    assert client.get("/api/clients/1/monthly-report", headers=portal, params={"month": "Sept"}).status_code == 422
    future = mr.add_months(date.today().replace(day=1), 1).isoformat()[:7]
    assert client.get("/api/clients/1/monthly-report", headers=portal, params={"month": future}).status_code == 422
    assert client.get("/api/clients/2/monthly-report", headers=portal).status_code == 404


def test_insights():
    m = date(2026, 9, 1)
    assert mr.insight("Acme", "Calls", 62, 100, m) == ("Acme saw a 38% drop in Calls in Sep 26 compared to Aug 26, but with ongoing improvements, "
                                                       "growth is expected in coming months.")
    assert "12.5% rise" in mr.insight("Acme", "Leads", 45, 40, m)
    assert "held steady" in mr.insight("Acme", "Leads", 40, 40, m)
    assert "2.5 points rise" in mr.insight("Acme", "Conversion", 18.5, 16.0, m, "%")
    assert "Not enough history" in mr.insight("Acme", "Marketing Score", None, 50, m)


def test_pdf_download_link(client, portal):
    link = client.post("/api/clients/1/monthly-report/link", headers=portal).json()
    assert link["filename"] == f"report_smile_dental_studio_{mr.default_month().isoformat()[:7]}.pdf"
    r = client.get(link["url"])
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF")
    assert link["filename"] in r.headers["content-disposition"]
    assert len(re.findall(rb"/Type\s*/Page\b", r.content)) == 6  # summary, growth, performance x3, what to do now
    bad = link["url"].replace("/clients/1/", "/clients/2/")
    assert client.get(bad).status_code == 401
    assert client.get(link["url"][:-6] + "xxxxxx").status_code == 401
