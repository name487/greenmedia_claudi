"""Business Score (mobile home for owners): score parts, stats, heatmap, chart, search keywords, competitors, report link."""

from datetime import date

from app.config import settings
from app.db import SessionLocal
from app.models import Competitor, Keyword, ScoreSnapshot, SearchKeyword

from .conftest import login
from .test_google import _link


def test_score_shape_and_consistency(client, portal):
    d = client.get("/api/clients/1/score", headers=portal).json()
    s = d["score"]
    assert s["value"] == sum(i["points"] for i in s["items"]) and 0 <= s["value"] <= 100
    assert sum(i["max"] for i in s["items"]) == 100
    assert s["label"] in {"poor", "average", "good", "excellent"} and all(i["tip"] for i in s["items"])
    st = d["stats"]
    assert 0 <= st["reply_pending"] <= st["reply_window"] <= 50 and st["reviews_lifetime"] > 0
    assert st["engagement_rate"] == round(100 * st["engagements_30d"] / st["views_30d"], 1)
    h = d["heatmap"]
    assert len(h["counts"]) == h["weeks"] * 7 and h["today_index"] < len(h["counts"]) and sum(h["counts"]) > 0
    assert len(d["chart"]["daily"]) == 30 and 1 <= len(d["chart"]["monthly"]) <= 6
    assert d["keywords"]["source"] == "sample" and d["keywords"]["items"][0]["impressions"] >= d["keywords"]["items"][-1]["impressions"]
    you = [x for x in d["competitors"] if x["is_you"]]
    assert len(you) == 1 and you[0]["name"] == "Smile Dental Studio" and len(d["competitors"]) == 8
    assert d["client"]["review_uri"].startswith("https://search.google.com/local/writereview")


def test_owner_sees_only_their_business(client, portal):
    assert client.get("/api/clients/2/score", headers=portal).status_code == 404
    seo = login(client, "kabir@greenmedia.in")
    assert client.get("/api/clients/2/score", headers=seo).status_code == 200


def test_replying_raises_the_score(client, admin, openai):
    before = client.get("/api/clients/1/score", headers=admin).json()
    pending = [r for r in client.get("/api/reviews", headers=admin, params={"client_id": 1, "filter": "all", "limit": 200}).json()["items"]
               if r["reply_status"] == "new"]
    for r in pending:
        client.post(f"/api/reviews/{r['id']}/draft", headers=admin)
        client.post(f"/api/reviews/{r['id']}/approve", headers=admin)
        client.post(f"/api/reviews/{r['id']}/publish", headers=admin)
    after = client.get("/api/clients/1/score", headers=admin).json()
    replies = lambda d: next(i for i in d["score"]["items"] if i["key"] == "replies")  # noqa: E731
    assert after["stats"]["reply_pending"] < before["stats"]["reply_pending"]
    assert replies(after)["points"] > replies(before)["points"] and after["score"]["value"] > before["score"]["value"]


def test_report_link_is_signed_and_scoped(client, portal):
    url = client.post("/api/clients/1/score/report-link", headers=portal).json()["url"]
    r = client.get(url)
    assert r.status_code == 200 and "Smile Dental Studio" in r.text and "Competitor analysis" in r.text
    assert client.get(url.replace("/clients/1/", "/clients/2/")).status_code == 401  # token is for client 1 only
    assert client.get("/api/clients/1/score/report?t=forged").status_code == 401


def test_competitors_replace_samples(client, admin, portal):
    x = client.post("/api/clients/1/competitors", headers=admin, json={"name": "Bright Smiles Baner", "rating": 4.8, "review_count": 950})
    assert x.status_code == 201
    names = [c["name"] for c in client.get("/api/clients/1/score", headers=admin).json()["competitors"]]
    assert sorted(names) == ["Bright Smiles Baner", "Smile Dental Studio"]  # demo rivals are dropped once a real one is added
    assert client.post("/api/clients/1/competitors", headers=portal, json={"name": "Nope"}).status_code == 403
    assert client.delete(f"/api/clients/1/competitors/{x.json()['id']}", headers=admin).status_code == 204
    with SessionLocal() as db:
        assert db.query(Competitor).filter_by(client_id=1).count() == 0


def test_live_google_sync_replaces_sample_keywords(client, admin, google):
    _link(client, admin, google)
    d = client.get("/api/clients/1/score", headers=admin).json()
    assert d["keywords"]["source"] == "google"
    assert [(k["keyword"], k["impressions"], k["below_threshold"]) for k in d["keywords"]["items"]] == [
        ("dentist near me", 161, False), ("dental clinic baner", 86, False), ("root canal pune", 15, True)]
    assert d["client"]["review_uri"] == "https://search.google.com/local/writereview?placeid=PID1"
    with SessionLocal() as db:
        assert not db.query(SearchKeyword).filter_by(client_id=1, is_sample=True).count()


# ---------- owner home screen ----------

def test_home_extras(client, portal):
    d = client.get("/api/clients/1/score", headers=portal).json()
    # today's score is recorded for the "Growth in Marketing Score" chart; the week is Monday first
    week = d["history"]
    assert len(week) == 7 and date.fromisoformat(week[0]["date"]).weekday() == 0
    today = next(h for h in week if h["date"] == date.today().isoformat())
    assert today["value"] == d["score"]["value"]
    assert all(h["value"] is None for h in week if h["date"] > date.today().isoformat())
    with SessionLocal() as db:
        assert db.query(ScoreSnapshot).filter_by(client_id=1, date=date.today()).count() == 1
    client.get("/api/clients/1/score", headers=portal)
    with SessionLocal() as db:  # one row per day, however often the screen is opened
        assert db.query(ScoreSnapshot).filter_by(client_id=1, date=date.today()).count() == 1
    # tracker and checklist
    tasks = {t["key"]: t for t in d["tracker"]["tasks"]}
    assert set(tasks) == {"posts_approved", "posts_published", "review_replies"}
    assert all(t["pending"] == max(0, t["target"] - t["achieved"]) for t in tasks.values())
    assert "more to achieve the target" in d["tracker"]["headline"] or "done" in d["tracker"]["headline"]
    assert len(d["actions"]) == 10 and all({"title", "done", "action", "target"} <= set(a) for a in d["actions"])
    # competitors split by distance; you are always in the local list
    g = d["competitor_groups"]
    assert any(x["is_you"] for x in g["local"]) and all(x["distance_km"] > g["local_km"] for x in g["surrounding"])
    assert len(g["local"]) + len(g["surrounding"]) == len(d["competitors"])
    assert {s["platform"] for s in d["social"]} == {"facebook", "instagram"}
    assert d["support"]["phone"].startswith("+91")


def test_performance_and_calendar(client, portal, admin):
    p30 = client.get("/api/clients/1/performance", headers=portal).json()
    p120 = client.get("/api/clients/1/performance", headers=portal, params={"days": 120}).json()
    assert len(p30["series"]) == 30 and len(p120["series"]) == 120  # the first demo businesses have 13 months of metrics
    assert p30["totals"]["views"] == sum(x["views"] for x in p30["series"]) and set(p30["totals"]) == {"views", "leads", "calls", "directions", "website"}
    assert client.get("/api/clients/1/performance", headers=portal, params={"days": 45}).status_code == 422
    body = {"client_id": 1, "topic": "Diwali offer", "master_copy": "x", "status": "draft", "variants": [{"platform": "gmb", "copy": "x", "format": "4:3"}]}
    client.post("/api/content", headers=admin, json=body)
    cal = client.get("/api/clients/1/calendar", headers=portal).json()
    assert cal["month"] == date.today().isoformat()[:7] and cal["days"].get(date.today().isoformat()) in ("generated", "approved", "posted")
    assert client.get("/api/clients/1/calendar", headers=portal, params={"month": "2026-13"}).status_code == 422


def test_keyword_planner(client, portal, monkeypatch):
    monkeypatch.setattr(settings, "keyword_search_monthly_limit", 2)
    kp = client.get("/api/clients/1/keyword-planner", headers=portal).json()
    assert kp["credits"] == {"used": 0, "limit": 2} and kp["city"] == "Pune"
    r = client.post("/api/clients/1/keyword-planner/search", headers=portal, json={"keyword": "dental clinic", "city": "Pune"}).json()
    assert r["credits"]["used"] == 1 and len(r["results"]) >= 15
    first = r["results"][0]
    assert first["source"] == "google" and "dental clinic" in first["keyword"]  # real Google terms come first
    assert {x["source"] for x in r["results"]} == {"google", "estimate"}
    assert all(x["competition"] in ("low", "medium", "high") for x in r["results"] if x["source"] == "estimate")
    again = client.post("/api/clients/1/keyword-planner/search", headers=portal, json={"keyword": "dental clinic", "city": "Pune"}).json()
    assert [x["searches"] for x in again["results"]] == [x["searches"] for x in r["results"]]  # stable estimates
    assert client.post("/api/clients/1/keyword-planner/search", headers=portal, json={"keyword": "implants"}).status_code == 429
    # add and remove a keyword to track
    k = client.post("/api/clients/1/keyword-planner/keywords", headers=portal, json={"keyword": "Dental implants Pune", "volume": 880})
    assert k.status_code == 201 and k.json()["location"] == "Pune"
    assert client.post("/api/clients/1/keyword-planner/keywords", headers=portal, json={"keyword": "dental implants pune"}).status_code == 409
    assert any(x["keyword"] == "Dental implants Pune" for x in client.get("/api/clients/1/score", headers=portal).json()["tracked_keywords"])
    assert client.delete(f"/api/clients/1/keyword-planner/keywords/{k.json()['id']}", headers=portal).status_code == 204
    with SessionLocal() as db:
        assert not db.query(Keyword).filter_by(client_id=1, keyword="Dental implants Pune").count()
    other = client.get("/api/clients/2/keyword-planner", headers=portal)
    assert other.status_code == 404
