"""Google Post in the app: the Content Agent's daily text posts built around the business's keywords, the daily job,
"write one now", edit, approve / reject, and "Post automatically" as a standing approval only an approver can give."""

from datetime import datetime, timedelta, timezone

import pytest

from app import content_service, google_posts, jobs, publishers
from app.ai_posts import TZ
from app.db import SessionLocal
from app.models import ContentItem

from .conftest import login


@pytest.fixture()
def sent(monkeypatch):
    calls = []
    real = publishers.publish_post

    def spy(c, platform, copy, **kw):
        calls.append((platform, copy))
        return real(c, platform, copy, **kw)

    monkeypatch.setattr(content_service, "publish_post", spy)
    return calls


def _due(cid):
    with SessionLocal() as db:
        db.get(ContentItem, cid).scheduled_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()


def _sweep():
    with SessionLocal() as db:
        return content_service.publish_due(db)


def test_write_posts_around_keywords_one_day_each(client, portal):
    ov = client.get("/api/clients/1/google-posts", headers=portal).json()
    assert ov["settings"] == {"daily": True, "auto": False, "time": "10:00", "auto_by": ""}
    assert ov["connected"] and ov["keyword_count"] > 3 and ov["items"] == []
    top = ov["keywords"][0]["keyword"]
    assert ov["next_keyword"] == top

    a = client.post("/api/clients/1/google-posts/generate", headers=portal, json={}).json()
    b = client.post("/api/clients/1/google-posts/generate", headers=portal, json={}).json()
    tomorrow = datetime.now(TZ).date() + timedelta(days=1)
    assert a["day"] == tomorrow.isoformat() and b["day"] == (tomorrow + timedelta(days=1)).isoformat()
    assert a["status"] == "in_review" and a["group"] == "pending" and not a["auto_approved"]
    assert a["keyword"] == top and b["keyword"] != top  # the next post picks the least-used keyword
    assert a["keyword"] in a["text"] and a["volume"] == ov["keywords"][0]["volume"]
    assert a["scheduled_at"].endswith("04:30:00+00:00")  # 10:00 India time
    assert "#" not in a["text"] and a["angle"] != b["angle"]
    # the business's own name is never the keyword a post is written around
    assert all(not set(google_posts.re.findall(r"\w+", p["keyword"])) <= {"smile", "dental", "studio"} for p in (a, b))

    ov = client.get("/api/clients/1/google-posts", headers=portal).json()
    assert [i["id"] for i in ov["items"]] == [b["id"], a["id"]] and ov["counts"]["pending"] == 2
    # they're Google posts, not AI Posts
    assert all(p["id"] not in (a["id"], b["id"]) for p in client.get("/api/clients/1/ai-posts", headers=portal).json()["items"])
    assert client.get("/api/clients/2/google-posts", headers=portal).status_code == 404


def test_daily_job_drafts_tomorrow_once(client, portal):
    with SessionLocal() as db:
        first = jobs.google_posts(db)
        again = jobs.google_posts(db)
    assert first["drafted"] >= 1 and again["drafted"] == 0
    items = client.get("/api/clients/1/google-posts", headers=portal).json()["items"]
    assert len(items) == 1 and items[0]["day"] == (datetime.now(TZ).date() + timedelta(days=1)).isoformat()
    # daily posts off: the job leaves this business alone
    client.put("/api/clients/1/google-posts/settings", headers=portal, json={"daily": False})
    client.post(f"/api/clients/1/ai-posts/{items[0]['id']}/reject", headers=portal)  # frees tomorrow
    with SessionLocal() as db:
        jobs.google_posts(db)
    assert len(client.get("/api/clients/1/google-posts", headers=portal).json()["items"]) == 1


def test_edit_approve_and_publish_to_google(client, portal, sent):
    p = client.post("/api/clients/1/google-posts/generate", headers=portal, json={"keyword": "teeth whitening"}).json()
    assert p["keyword"] == "teeth whitening"
    _due(p["id"])
    _sweep()
    assert sent == []  # waiting for approval
    assert client.patch(f"/api/clients/1/google-posts/{p['id']}", headers=portal, json={"text": "short"}).status_code == 422
    text = "Teeth whitening at Smile Dental Studio, Pune — a brighter smile in one visit. Call us to book."
    edited = client.patch(f"/api/clients/1/google-posts/{p['id']}", headers=portal, json={"text": text}).json()
    assert edited["text"] == text and edited["status"] == "in_review"
    when = (datetime.now(TZ) + timedelta(hours=2)).isoformat()
    ok = client.post(f"/api/clients/1/ai-posts/{p['id']}/approve", headers=portal, json={"scheduled_at": when}).json()
    assert ok["status"] == "scheduled"
    _due(p["id"])
    _sweep()
    assert sent == [("gmb", text)]
    out = client.get("/api/clients/1/google-posts", headers=portal).json()["items"][0]
    assert out["status"] == "published" and out["group"] == "posted"
    assert client.patch(f"/api/clients/1/google-posts/{p['id']}", headers=portal, json={"text": text + " Thanks!"}).status_code == 409


def test_post_automatically_is_a_standing_approval(client, portal, sent):
    seo = login(client, "kabir@greenmedia.in")  # can create content, can't approve
    assert client.put("/api/clients/1/google-posts/settings", headers=seo, json={"auto": True}).status_code == 403
    assert client.put("/api/clients/1/google-posts/settings", headers=portal, json={"time": "25:00"}).status_code == 422
    s = client.put("/api/clients/1/google-posts/settings", headers=portal, json={"auto": True, "time": "09:30"}).json()["settings"]
    assert s == {"daily": True, "auto": True, "time": "09:30", "auto_by": "Dr. Anjali Rao"}

    p = client.post("/api/clients/1/google-posts/generate", headers=portal, json={}).json()
    assert p["status"] == "scheduled" and p["auto_approved"] and p["scheduled_at"].endswith("04:00:00+00:00")
    with SessionLocal() as db:
        assert db.get(ContentItem, p["id"]).approval_rule == google_posts.RULE
    # editing the text clears the standing approval for that post
    edited = client.patch(f"/api/clients/1/google-posts/{p['id']}", headers=portal,
                          json={"text": "Edited by hand: affordable dental care in Pune. Call us today."}).json()
    assert edited["status"] == "in_review" and not edited["auto_approved"]
    _due(p["id"])
    _sweep()
    assert sent == []

    # turned off: new posts wait again
    client.put("/api/clients/1/google-posts/settings", headers=portal, json={"auto": False})
    q = client.post("/api/clients/1/google-posts/generate", headers=portal, json={}).json()
    assert q["status"] == "in_review" and not q["auto_approved"]
