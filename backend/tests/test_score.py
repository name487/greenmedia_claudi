"""Business Score (mobile home for owners): score parts, stats, heatmap, chart, search keywords, competitors, report link."""

from app.db import SessionLocal
from app.models import Competitor, SearchKeyword

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
    assert len(you) == 1 and you[0]["name"] == "Smile Dental Studio" and len(d["competitors"]) == 5
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
