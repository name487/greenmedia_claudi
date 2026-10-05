"""AI Review Queue: Google fetch into gmb_reviews, sample-data fallback while API approval is pending, queue API."""

import httpx

from app.db import SessionLocal
from app.google import api
from app.jobs import sync_google

from .conftest import login
from .test_google import ACCOUNT, LOCATION
from .test_google_client import _client_connect

QUOTA_0 = httpx.Response(429, json={"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                                              "message": "Quota exceeded for quota metric 'Requests' and limit 'Requests per minute' of service 'mybusiness.googleapis.com'"}})
REVIEWS_URL = f"{api.V4_BASE}/{ACCOUNT}/{LOCATION}/reviews"


def _queue(client, headers, **params):
    r = client.get("/api/reviews", headers=headers, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _items(client, headers, cid=1):
    return {r["author"]: r for r in _queue(client, headers, filter="all", client_id=cid, limit=200)["items"]}


def test_new_google_reviews_are_fetched_drafted_and_edits_tracked(client, admin, google):
    _client_connect(client, admin)  # links the location and imports 3 reviews
    google.reviews[0]["reviewer"]["profilePhotoUrl"] = "https://lh3.googleusercontent.com/a/meena"
    google.reviews.insert(0, {"reviewId": "r-fresh", "reviewer": {"displayName": "Farah Q"}, "starRating": "FIVE",
                              "comment": "Great team, very friendly! (Translated by Google) x (Original) Great team, very friendly!",
                              "createTime": "2026-10-04T09:00:00Z", "updateTime": "2026-10-04T09:00:00Z"})
    out = client.post("/api/reviews/sync", headers=admin, json={"client_id": 1}).json()
    assert out["mode"] == "live" and out["profiles"] == 1 and out["new_reviews"] == 1 and out["drafted"] == 1 and out["sample_reviews"] == 0
    items = _items(client, admin)
    fresh = items["Farah Q"]
    assert fresh["text"] == "Great team, very friendly!" and fresh["reply_status"] == "drafted" and fresh["reply"] and not fresh["is_sample"]
    assert items["Meena K"]["reviewer_photo"] == "https://lh3.googleusercontent.com/a/meena"

    # Reviewer edits a review whose reply was already approved: it must be looked at again
    meena = items["Meena K"]
    client.post(f"/api/reviews/{meena['id']}/approve", headers=admin)
    google.reviews[1].update(starRating="FOUR", comment="They called me back and sorted it out. Much better now, thanks!", updateTime="2026-10-04T10:00:00Z")
    out = client.post("/api/clients/1/gmb/sync", headers=admin).json()["sync"]
    assert out["incremental"] and out["updated_reviews"] == 1
    meena = _items(client, admin)["Meena K"]
    assert (meena["rating"], meena["sentiment"], meena["reply_status"], meena["edited"]) == (4, "positive", "drafted", True)

    # Replied directly on Google: mirrored, leaves the queue
    google.reviews[0]["reviewReply"] = {"comment": "Thanks Farah!", "updateTime": "2026-10-04T11:00:00Z"}
    google.reviews[0]["updateTime"] = "2026-10-04T11:00:00Z"
    client.post("/api/reviews/sync", headers=admin, json={"client_id": 1})
    fresh = _items(client, admin)["Farah Q"]
    assert fresh["reply_status"] == "published" and fresh["reply"] == "Thanks Farah!"


def test_sample_reviews_while_api_approval_is_pending_then_real_ones_replace_them(client, admin, google):
    _client_connect(client, admin)
    google.fail[REVIEWS_URL] = QUOTA_0  # Google hasn't approved API access: quota 0
    out = client.post("/api/reviews/sync", headers=admin, json={"client_id": 1}).json()
    assert out["mode"] == "sample" and out["approval_pending"] == ["Smile Dental Studio"] and out["sample_reviews"] == 6 and out["drafted"] == 6
    q = _queue(client, admin, client_id=1, filter="all", limit=200)
    assert q["sources"]["approval_pending"] and q["sources"]["clients"][0]["state"] == "approval_pending"
    assert sum(r["is_sample"] for r in q["items"]) == 6 and q["counts"]["all"] == 9  # 3 real (imported at link) + 6 samples
    assert len(_queue(client, admin, client_id=1, filter="all", source="sample")["items"]) == 6

    # Working the queue on a sample never touches Google
    sample = next(r for r in q["items"] if r["is_sample"] and r["rating"] >= 3)
    before = len(google.calls)
    assert client.post(f"/api/reviews/{sample['id']}/publish", headers=admin).json()["reply_status"] == "published"
    assert len(google.calls) == before and google.replies == {}

    # Each further sync brings one more sample review, like a new one arriving
    assert client.post("/api/reviews/sync", headers=admin, json={"client_id": 1}).json()["sample_reviews"] == 1

    # Google approves: the next sync fetches real reviews and the samples disappear
    del google.fail[REVIEWS_URL]
    out = client.post("/api/reviews/sync", headers=admin, json={"client_id": 1}).json()
    assert out["mode"] == "live" and out["clients"][0]["removed_samples"] == 7
    q = _queue(client, admin, client_id=1, filter="all")
    assert not any(r["is_sample"] for r in q["items"]) and q["sources"]["clients"][0]["state"] == "live" and not q["sources"]["approval_pending"]


def test_sample_data_can_be_turned_off(client, admin, google, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "review_sample_data", False)
    assert client.post("/api/reviews/sync", headers=admin, json={"client_id": 3}).status_code == 409  # not linked, nothing to do
    _client_connect(client, admin)
    google.fail[REVIEWS_URL] = QUOTA_0
    out = client.post("/api/reviews/sync", headers=admin, json={"client_id": 1}).json()
    assert out["sample_reviews"] == 0 and out["approval_pending"] == ["Smile Dental Studio"]
    assert "quota" in client.get("/api/clients/1/google", headers=admin).json()["profile"]["last_error"].lower()


def test_new_clients_without_reviews_get_a_first_sample_batch(client, admin):
    cid = client.post("/api/clients", headers=admin, json={"company_name": "Fresh Bakery", "city": "Pune"}).json()["id"]
    out = client.post("/api/reviews/sync", headers=admin, json={}).json()
    fresh = next(x for x in out["clients"] if x["client_id"] == cid)
    assert fresh["mode"] == "sample" and fresh["new"] == 6 and fresh["drafted"] == 6
    q = _queue(client, admin, client_id=cid, filter="all")
    assert q["counts"]["all"] == 6 and all(r["is_sample"] for r in q["items"]) and q["sources"]["clients"][0]["state"] == "sample"


def test_queue_filters_sort_stats_and_paging(client, admin):
    q = _queue(client, admin)
    assert q["items"] and q["total"] == q["counts"]["pending"]
    first_pending = q["items"][0]
    assert first_pending["sentiment"] == "negative" or first_pending["rating"] <= 2  # escalations first
    assert all(r["waiting_hours"] is not None for r in q["items"])
    s = q["stats"]
    assert s["needs_reply"] == q["counts"]["pending"] and 0 <= s["response_rate"] <= 100 and 1 <= s["avg_rating"] <= 5
    assert q["sources"]["summary"]["sample"] >= 20  # seeded demo clients run on sample data

    assert {r["rating"] for r in _queue(client, admin, filter="all", rating=5)["items"]} == {5}
    assert {r["sentiment"] for r in _queue(client, admin, filter="all", sentiment="negative")["items"]} == {"negative"}
    assert _queue(client, admin, filter="all", source="google")["items"] == []
    name = q["items"][0]["author"]
    assert all(name.lower() in f"{r['author']} {r['text']} {r['reply'] or ''} {r['client_name']}".lower()
               for r in _queue(client, admin, filter="all", q=name)["items"])
    oldest = _queue(client, admin, filter="all", sort="oldest", limit=5)
    assert oldest["items"][0]["created_at"] <= oldest["items"][-1]["created_at"] and len(oldest["items"]) == 5
    page2 = _queue(client, admin, filter="all", sort="oldest", limit=5, offset=5)
    assert {r["id"] for r in page2["items"]}.isdisjoint({r["id"] for r in oldest["items"]})
    assert client.get("/api/reviews?rating=9", headers=admin).status_code == 422


def test_bulk_actions_follow_the_same_rules(client, admin):
    new = [r for r in _queue(client, admin, client_id=1, filter="all", limit=200)["items"] if r["reply_status"] == "new"]
    ids = [r["id"] for r in new]
    assert ids
    out = client.post("/api/reviews/bulk", headers=admin, json={"ids": ids, "action": "draft"}).json()
    assert out == {"done": len(ids), "failed": []}
    out = client.post("/api/reviews/bulk", headers=admin, json={"ids": ids + [999999], "action": "publish"}).json()
    failed = {f["id"]: f["error"] for f in out["failed"]}
    low = {r["id"] for r in new if r["rating"] <= 2}  # 2★ escalation still applies in bulk
    assert set(failed) == low | {999999} and failed[999999] == "Review not found"
    assert all("approved first" in failed[i] for i in low) and out["done"] == len(ids) - len(low)
    # A role without approve permission gets per-review errors, nothing changes
    content = login(client, "sneha@greenmedia.in")
    drafted = [r["id"] for r in _queue(client, admin, filter="all", limit=200)["items"] if r["reply_status"] == "drafted"][:3]
    if drafted:
        out = client.post("/api/reviews/bulk", headers=content, json={"ids": drafted, "action": "approve"}).json()
        assert out["done"] == 0 and all(f["error"] == "Your role cannot approve replies" for f in out["failed"])
    assert client.post("/api/reviews/bulk", headers=admin, json={"ids": [], "action": "draft"}).status_code == 422


def test_client_portal_sees_only_its_queue(client, portal):
    q = _queue(client, portal, filter="all")
    assert {r["client_id"] for r in q["items"]} == {1} and [c["client_id"] for c in q["sources"]["clients"]] == [1]
    other = _queue(client, login(client, "admin@greenmedia.in"), client_id=2, filter="all")["items"][0]
    out = client.post("/api/reviews/bulk", headers=portal, json={"ids": [other["id"]], "action": "reject"}).json()
    assert out["done"] == 0 and out["failed"][0]["error"] == "Client not found"


def test_scheduler_fetches_and_drafts(client, admin, google):
    _client_connect(client, admin)
    google.reviews.insert(0, {"reviewId": "r-night", "reviewer": {"displayName": "Nikhil T"}, "starRating": "ONE", "comment": "Terrible, never again.",
                              "createTime": "2026-10-04T23:00:00Z", "updateTime": "2026-10-04T23:00:00Z"})
    with SessionLocal() as db:
        assert sync_google(db)["synced"] == 1
    r = _items(client, admin)["Nikhil T"]
    assert r["reply_status"] == "drafted" and r["needs_escalation"]  # drafted, waits for approval (never auto-published)
