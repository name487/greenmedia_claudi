"""Nothing publishes without approval: every way a review reply or a post could go out is tried here, and the fake
Google / Meta APIs must not receive anything unless the current text was approved."""

from datetime import datetime, timedelta, timezone

import pytest

from app import content_service, publishers, review_queue
from app.db import SessionLocal
from app.models import Client, ContentItem, Review

from .conftest import login
from .test_google_client import _client_connect

FUTURE = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()


def _review(client, admin, author):
    items = client.get("/api/reviews", headers=admin, params={"filter": "all", "client_id": 1, "limit": 200}).json()["items"]
    return next(r for r in items if r["author"] == author)


def _get(client, admin, rid):
    return next(r for r in client.get("/api/reviews", headers=admin, params={"filter": "all", "client_id": 1, "limit": 200}).json()["items"] if r["id"] == rid)


# ---------- review replies ----------

def test_review_reply_needs_approval_on_every_path(client, admin, google):
    _client_connect(client, admin)  # live Google location; Meena K (2★) and Anonymous (4★) arrive with AI drafts
    for author in ("Meena K", "Anonymous"):
        r = _review(client, admin, author)
        rid = r["id"]
        assert r["reply_status"] == "drafted" and r["approved_at"] is None
        assert client.post(f"/api/reviews/{rid}/publish", headers=admin).status_code == 409  # drafted
        client.post(f"/api/reviews/{rid}/approve", headers=admin)
        client.patch(f"/api/reviews/{rid}", headers=admin, json={"reply": "Changed after approval"})
        assert _get(client, admin, rid)["approved_at"] is None
        assert client.post(f"/api/reviews/{rid}/publish", headers=admin).status_code == 409  # edit cleared approval
        client.post(f"/api/reviews/{rid}/approve", headers=admin)
        client.post(f"/api/reviews/{rid}/draft", headers=admin, json={"instruction": "shorter"})
        assert client.post(f"/api/reviews/{rid}/publish", headers=admin).status_code == 409  # regenerate cleared it
        client.post(f"/api/reviews/{rid}/approve", headers=admin)
        client.post(f"/api/reviews/{rid}/reject", headers=admin)
        client.post(f"/api/reviews/{rid}/reopen", headers=admin)
        assert client.post(f"/api/reviews/{rid}/publish", headers=admin).status_code == 409  # reject/reopen cleared it
    assert client.post("/api/reviews/bulk", headers=admin, json={"ids": [_review(client, admin, "Meena K")["id"]], "action": "publish"}).json()["done"] == 0
    assert google.replies == {}  # nothing reached Google

    # Approved → published, with who approved it in the audit trail
    rid = _review(client, admin, "Meena K")["id"]
    client.post(f"/api/reviews/{rid}/approve", headers=admin)
    assert client.post(f"/api/reviews/{rid}/publish", headers=admin).json()["reply_status"] == "published"
    assert list(google.replies) == ["r-new"]
    entry = client.get(f"/api/reviews/{rid}/history", headers=admin).json()[0]
    assert entry["action"] == "published reply to Google" and entry["details"]["approved_by"] == 1


def test_roles_cannot_skip_approval(client, admin, portal):
    content = login(client, "sneha@greenmedia.in")  # reviews section, no approve / publish
    r = next(x for x in client.get("/api/reviews", headers=admin, params={"filter": "all", "client_id": 1, "limit": 200}).json()["items"] if x["reply_status"] == "new")
    client.post(f"/api/reviews/{r['id']}/draft", headers=content)
    assert client.post(f"/api/reviews/{r['id']}/approve", headers=content).status_code == 403
    assert client.post(f"/api/reviews/{r['id']}/publish", headers=content).status_code == 403
    # The client can approve its own replies but not publish them
    assert client.post(f"/api/reviews/{r['id']}/approve", headers=portal).json()["reply_status"] == "approved"
    assert client.post(f"/api/reviews/{r['id']}/publish", headers=portal).status_code == 403


def test_lowest_level_publish_refuses_unapproved(client):
    with SessionLocal() as db:
        r = db.query(Review).filter(Review.client_id == 1).first()
        c = db.get(Client, 1)
        r.reply, r.reply_status, r.approved_at = "Thanks!", "approved", None  # status forced, no approval recorded
        with pytest.raises(publishers.PublishError, match="hasn't been approved"):
            review_queue.publish(r, c)
        r.reply_status = "drafted"
        review_queue.approve(r, 1)
        with pytest.raises(publishers.PublishError):  # approval without the approved status is not enough either
            review_queue.publish(r, c)


def test_auto_publish_only_with_the_clients_opt_in(client, admin, google):
    _client_connect(client, admin)
    assert google.replies == {}  # opt-in is off by default: drafts only
    google.reviews.insert(0, {"reviewId": "r-happy", "reviewer": {"displayName": "Happy P"}, "starRating": "FIVE", "comment": "Excellent, friendly staff!",
                              "createTime": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "updateTime": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")})
    google.reviews.insert(0, {"reviewId": "r-angry", "reviewer": {"displayName": "Angry Q"}, "starRating": "ONE", "comment": "Terrible, rude, never again.",
                              "createTime": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "updateTime": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")})
    client.patch("/api/clients/1", headers=admin, json={"auto_publish": {"reviews": True}})
    client.post("/api/reviews/sync", headers=admin, json={"client_id": 1})
    assert list(google.replies) == ["r-happy"]  # positive 5★ only; the 1★ waits for a person
    happy, angry = _review(client, admin, "Happy P"), _review(client, admin, "Angry Q")
    assert happy["approval_rule"] == "auto_publish" and happy["approved_by"] is None
    assert angry["reply_status"] == "drafted" and angry["approved_at"] is None


# ---------- posts ----------

def _post(client, headers, status="draft", platforms=("gmb", "facebook")):
    body = {"client_id": 1, "topic": "Offer", "master_copy": "Free check-up", "status": status, "scheduled_at": FUTURE,
            "variants": [{"platform": p, "copy": f"{p} copy", "format": "1:1"} for p in platforms]}
    r = client.post("/api/content", headers=headers, json=body)
    return r


def _due(cid):
    with SessionLocal() as db:
        db.get(ContentItem, cid).scheduled_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()


def _sweep():
    with SessionLocal() as db:
        return content_service.publish_due(db)


@pytest.fixture()
def sent(monkeypatch):
    calls = []
    real = publishers.publish_post

    def spy(c, platform, copy, **kw):
        calls.append((platform, copy))
        return real(c, platform, copy, **kw)

    monkeypatch.setattr(content_service, "publish_post", spy)
    return calls


def test_posts_need_approval_on_every_path(client, admin, sent):
    content = login(client, "sneha@greenmedia.in")  # can create, can't approve
    assert _post(client, content, status="scheduled").status_code == 403
    item = _post(client, content).json()
    cid = item["id"]
    for action in ("publish", "retry", "schedule"):
        assert client.post(f"/api/content/{cid}/{action}", headers=content).status_code in (403, 409)
    client.post(f"/api/content/{cid}/submit", headers=content)
    assert client.post(f"/api/content/{cid}/approve", headers=content).status_code == 403
    assert client.post(f"/api/content/{cid}/publish", headers=admin).status_code == 409  # in review, not approved
    _due(cid)
    _sweep()
    assert sent == []

    s = client.post(f"/api/content/{cid}/approve", headers=admin).json()
    assert s["status"] == "scheduled" and s["approved_by"] == 1
    # Unschedule → back to draft, approval gone, the scheduler skips it
    assert client.post(f"/api/content/{cid}/unschedule", headers=admin).json()["approved_at"] is None
    _due(cid)
    _sweep()
    assert sent == []


def test_failed_post_edited_or_adapted_needs_approval_again(client, admin, sent, monkeypatch):
    item = _post(client, admin, status="scheduled").json()
    assert item["approved_at"]
    monkeypatch.setattr(content_service, "publish_post", lambda c, p, copy, **kw: (_ for _ in ()).throw(publishers.PublishError("Meta 400")))
    assert client.post(f"/api/content/{item['id']}/publish", headers=admin).status_code == 502
    edited = client.patch(f"/api/content/{item['id']}", headers=admin, json={"variants": [{"platform": "facebook", "copy": "New unapproved text"}]}).json()
    assert edited["status"] == "draft" and edited["approved_at"] is None
    assert client.post(f"/api/content/{item['id']}/retry", headers=admin).status_code == 409
    log = client.get("/api/audit", headers=admin).json()[0]
    assert log["details"]["approval"] == "cleared — the copy changed after approval"


def test_scheduler_refuses_unapproved_rows(client, admin, sent):
    item = _post(client, admin).json()  # draft, never approved
    with SessionLocal() as db:  # forced into the schedule behind the API's back
        row = db.get(ContentItem, item["id"])
        row.status, row.scheduled_at = "scheduled", datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    _sweep()
    with SessionLocal() as db:
        row = db.get(ContentItem, item["id"])
        assert row.status == "draft" and "Not approved" in row.last_error
    assert sent == []
    entry = client.get("/api/audit", headers=admin).json()[0]
    assert entry["action"] == "publish blocked (not approved): Offer" and entry["user_name"] is None
