"""content_items: AI post drafts, Draft/Scheduled/Published/Failed tracking, Celery + Redis scheduling, retries."""

import os
from datetime import datetime, timedelta, timezone

import pytest

from app import content_service, publishers
from app.config import settings
from app.db import SessionLocal
from app.models import ContentItem

from .conftest import login

FUTURE = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _post(client, admin, cid=1, platforms=("gmb", "facebook"), status="draft", when=FUTURE):
    body = {"client_id": cid, "topic": "Monsoon dental check-up offer", "master_copy": "Book your check-up",
            "variants": [{"platform": p, "copy": f"{p} copy", "format": "1:1"} for p in platforms], "status": status,
            "scheduled_at": _iso(when) if when else None, "image_url": "https://cdn.example.com/post.jpg" if "instagram" in platforms else ""}
    r = client.post("/api/content", headers=admin, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _make_due(cid: int, minutes_ago: int = 1):
    with SessionLocal() as db:
        item = db.get(ContentItem, cid)
        item.scheduled_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        if item.next_attempt_at:
            item.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()


def _get(client, admin, cid):
    return next(i for i in client.get("/api/content", headers=admin).json() if i["id"] == cid)


def _sweep():
    with SessionLocal() as db:
        return content_service.publish_due(db)


def test_ai_draft_is_saved_as_draft_with_model_and_audit(client, admin, openai):
    openai.reply = ('{"master_copy": "Monsoon smiles deserve care.", "hashtags": ["#PuneDentist"], "creative_brief": "Rainy window, bright smile",'
                    ' "variants": [{"platform": "gmb", "copy": "Free check-up this monsoon at Smile Dental."},'
                    ' {"platform": "facebook", "copy": "Rainy days, bright smiles! Book a free check-up."}]}')
    r = client.post("/api/content/draft", headers=admin, json={"client_id": 1, "topic": "Monsoon check-up", "platforms": ["gmb", "facebook"],
                                                              "notes": "Mention free parking", "scheduled_at": _iso(FUTURE)})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["status"] == "draft" and d["ai_source"] == "ai" and d["ai_model"].startswith("openai/gpt-4.1-mini")
    assert [(v["platform"], v["status"]) for v in d["variants"]] == [("gmb", "pending"), ("facebook", "pending")]
    assert d["variants"][0]["copy"] == "Free check-up this monsoon at Smile Dental." and d["scheduled_at"].startswith(FUTURE.date().isoformat())
    assert "Extra notes from the team: Mention free parking" in openai.user and "Warm and professional" in openai.system  # brand voice
    log = client.get("/api/audit", headers=admin).json()[0]
    assert log["action"] == "AI drafted post (ai): Monsoon check-up" and log["details"]["usage"]["input"] == 412


def test_ai_draft_without_key_uses_template(client, admin):
    d = client.post("/api/content/draft", headers=admin, json={"client_id": 1, "topic": "Diwali offer", "platforms": ["gmb"]}).json()
    assert d["status"] == "draft" and d["ai_source"] == "template" and d["ai"]["error"] == "No AI key configured" and d["variants"][0]["copy"]
    assert client.post("/api/content/draft", headers=admin, json={"client_id": 1, "topic": "x y", "platforms": ["youtube"]}).status_code == 422


def test_draft_review_schedule_unschedule_and_board(client, admin):
    content = login(client, "sneha@greenmedia.in")  # can create, can't approve
    item = _post(client, content, when=None)
    cid = item["id"]
    assert client.post(f"/api/content/{cid}/submit", headers=content).json()["status"] == "in_review"
    assert client.post(f"/api/content/{cid}/approve", headers=content).status_code == 403
    assert client.post(f"/api/content/{cid}/approve", headers=admin).json()["detail"] == "Pick a publish date and time first"
    client.patch(f"/api/content/{cid}", headers=admin, json={"scheduled_at": _iso(FUTURE)})
    s = client.post(f"/api/content/{cid}/approve", headers=admin).json()
    assert s["status"] == "scheduled" and s["attempts"] == 0

    # Approved copy is frozen while scheduled; time can move
    assert client.patch(f"/api/content/{cid}", headers=admin, json={"master_copy": "changed"}).status_code == 409
    later = FUTURE + timedelta(hours=3)
    assert client.patch(f"/api/content/{cid}", headers=admin, json={"scheduled_at": _iso(later)}).json()["scheduled_at"].startswith(later.isoformat()[:16])
    assert client.patch(f"/api/content/{cid}", headers=admin, json={"scheduled_at": "2020-01-01T00:00:00Z"}).status_code == 422
    assert client.get("/api/audit", headers=admin).json()[0]["details"]["scheduled_at"]["after"].startswith(later.isoformat()[:16])

    b = client.get("/api/content/board", headers=admin, params={"group": "scheduled"}).json()
    assert cid in [i["id"] for i in b["items"]] and set(b["counts"]) == {"draft", "scheduled", "published", "failed", "all"}
    assert b["scheduler"]["mode"] == "off"  # tests run without Redis or the in-process loop
    assert client.post(f"/api/content/{cid}/unschedule", headers=admin).json()["status"] == "draft"
    assert client.patch(f"/api/content/{cid}", headers=admin, json={"variants": [{"platform": "gmb", "copy": "New GMB copy"}]}).json()["variants"][0]["copy"] == "New GMB copy"
    assert client.patch(f"/api/content/{cid}", headers=admin, json={"variants": [{"platform": "x", "copy": "?"}]}).status_code == 422
    assert client.post(f"/api/content/{cid}/schedule", headers=admin).json()["status"] == "scheduled"


def test_due_posts_are_published_once_by_the_sweep(client, admin):
    item = _post(client, admin, status="scheduled")
    assert _sweep()["published"] == 0  # not due yet
    _make_due(item["id"])
    assert _sweep()["published"] == 1
    got = _get(client, admin, item["id"])
    assert got["status"] == "published" and got["published_at"] and got["attempts"] == 1
    assert all(v["status"] == "published" and v["external_post_id"] and v["published_at"] for v in got["variants"])
    assert _sweep()["published"] == 0  # nothing published twice
    log = client.get("/api/audit", headers=admin).json()[0]
    assert log["action"] == "[scheduler] published: Monsoon dental check-up offer" and log["user_name"] is None
    assert log["details"]["variants"]["gmb"]["status"] == "published"
    assert client.get("/api/content/board", headers=admin, params={"group": "published"}).json()["counts"]["published"] >= 1


def test_claim_is_single_winner(client, admin):
    item = _post(client, admin, status="scheduled")
    with SessionLocal() as db:
        assert content_service.claim(db, item["id"]) is False  # not due
    _make_due(item["id"])
    with SessionLocal() as db:
        assert content_service.claim(db, item["id"]) is True
        assert content_service.claim(db, item["id"]) is False  # second worker / duplicate delivery loses
        assert content_service.run_publish(db, item["id"])["status"] == "skipped"


def test_temporary_errors_retry_with_backoff_then_succeed(client, admin, monkeypatch):
    calls = []
    real = publishers.publish_post

    def flaky(client_, platform, copy, **kw):
        calls.append(platform)
        if platform == "facebook" and calls.count("facebook") == 1:
            raise publishers.PublishError("Meta 503: try later", transient=True)
        return real(client_, platform, copy, **kw)

    monkeypatch.setattr(content_service, "publish_post", flaky)
    item = _post(client, admin, status="scheduled")
    _make_due(item["id"])
    assert _sweep()["retrying"] == 1
    got = _get(client, admin, item["id"])
    assert got["status"] == "scheduled" and got["attempts"] == 1 and "Meta 503" in got["last_error"] and got["next_attempt_at"]
    assert {v["platform"]: v["status"] for v in got["variants"]} == {"gmb": "published", "facebook": "failed"}
    retry_at = datetime.fromisoformat(got["next_attempt_at"])
    assert timedelta(minutes=1) < retry_at - datetime.now(timezone.utc) <= timedelta(minutes=settings.content_retry_minutes)
    assert _sweep()["retrying"] == 0 and _sweep()["published"] == 0  # waits for the retry time
    _make_due(item["id"])
    assert _sweep()["published"] == 1
    got = _get(client, admin, item["id"])
    assert got["status"] == "published" and got["attempts"] == 2 and got["last_error"] == ""
    assert calls == ["gmb", "facebook", "facebook"]  # GMB was not posted twice


def test_out_of_attempts_or_permanent_errors_fail_and_retry_works(client, admin, monkeypatch):
    monkeypatch.setattr(content_service, "publish_post", lambda c, p, copy, **kw: (_ for _ in ()).throw(publishers.PublishError("Meta 500", transient=True)))
    item = _post(client, admin, status="scheduled", platforms=("facebook",))
    for _ in range(settings.content_max_attempts):
        _make_due(item["id"])
        _sweep()
    got = _get(client, admin, item["id"])
    assert got["status"] == "failed" and got["attempts"] == settings.content_max_attempts and got["next_attempt_at"] is None

    # Permanent: fails on the first attempt
    monkeypatch.setattr(content_service, "publish_post", lambda c, p, copy, **kw: (_ for _ in ()).throw(publishers.PublishError("facebook token expired — reconnect the account")))
    item2 = _post(client, admin, status="scheduled", platforms=("facebook",))
    _make_due(item2["id"])
    _sweep()
    got = _get(client, admin, item2["id"])
    assert got["status"] == "failed" and got["attempts"] == 1 and "reconnect" in got["variants"][0]["error"]
    b = client.get("/api/content/board", headers=admin, params={"group": "failed"}).json()
    assert {item["id"], item2["id"]} <= {i["id"] for i in b["items"]}

    # Fixed → Retry publishes now
    monkeypatch.setattr(content_service, "publish_post", publishers.publish_post)
    r = client.post(f"/api/content/{item2['id']}/retry", headers=admin).json()
    assert r["status"] == "published" and r["dispatch"] == "published" and r["attempts"] == 1


def test_publish_now_failure_returns_502_and_is_tracked(client, admin):
    clients = client.get("/api/clients", headers=admin).json()
    cid = next(c["id"] for c in clients if any(s["platform"] == "instagram" and s["status"] == "expired" for s in client.get(f"/api/clients/{c['id']}", headers=admin).json()["social_accounts"]))
    item = _post(client, admin, cid=cid, platforms=("instagram",), status="scheduled")
    r = client.post(f"/api/content/{item['id']}/publish", headers=admin)
    assert r.status_code == 502 and "token expired" in r.json()["detail"]
    assert _get(client, admin, item["id"])["status"] == "failed"
    assert client.post(f"/api/content/{item['id']}/publish", headers=login(client, "sneha@greenmedia.in")).status_code == 403


def test_stuck_publishing_rows_are_recovered(client, admin):
    item = _post(client, admin, status="scheduled")
    with SessionLocal() as db:
        row = db.get(ContentItem, item["id"])
        row.status, row.updated_at = "publishing", datetime.now(timezone.utc) - timedelta(hours=1)
        row.scheduled_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()
    assert _sweep()["published"] == 1  # recovered, then published in the same sweep
    assert _get(client, admin, item["id"])["status"] == "published"


def test_delete_rules(client, admin):
    d = _post(client, admin, when=None)
    s = _post(client, admin, status="scheduled")
    assert client.delete(f"/api/content/{s['id']}", headers=admin).status_code == 409
    assert client.delete(f"/api/content/{d['id']}", headers=admin).json()["ok"]


def test_with_redis_work_goes_to_celery(client, admin, monkeypatch):
    from app import celery_app

    queued = []
    monkeypatch.setattr(settings, "redis_url", "redis://127.0.0.1:6379/15")
    monkeypatch.setattr(celery_app.publish_content, "delay", lambda cid, uid=None: queued.append((cid, uid)))
    item = _post(client, admin, status="scheduled")
    r = client.post(f"/api/content/{item['id']}/publish", headers=admin).json()
    assert r["dispatch"] == "queued" and r["status"] == "scheduled" and queued == [(item["id"], 1)]
    item2 = _post(client, admin, status="scheduled")
    _make_due(item2["id"])
    out = _sweep()
    assert out["queued"] == 2 and {q[0] for q in queued} == {item["id"], item2["id"]}
    assert client.get("/api/content/board", headers=admin).json()["scheduler"]["mode"] == "celery"
    # The worker task itself: claim + publish (run synchronously here)
    monkeypatch.setattr(settings, "redis_url", "")
    assert celery_app.publish_content.run(item["id"], 1)["status"] == "published"
    assert celery_app.publish_content.run(item["id"], 1)["status"] == "skipped"  # redelivery is harmless
    beat = celery_app.celery.conf.beat_schedule
    assert beat["dispatch-due-content"]["task"] == "greenmedia.dispatch_due" and beat["dispatch-due-content"]["schedule"] == 60.0
    assert celery_app.celery.conf.task_acks_late is True


@pytest.mark.skipif(not os.environ.get("REDIS_TEST_URL"), reason="set REDIS_TEST_URL=redis://… to run against a real Redis + Celery worker")
def test_real_redis_and_celery_worker(client, admin, monkeypatch):
    from celery.contrib.testing.worker import start_worker

    from app import celery_app

    url = os.environ["REDIS_TEST_URL"]
    monkeypatch.setattr(settings, "redis_url", url)
    celery_app.celery.conf.update(broker_url=url, result_backend=url)
    item = _post(client, admin, status="scheduled")
    _make_due(item["id"])
    with start_worker(celery_app.celery, perform_ping_check=False, pool="solo", loglevel="WARNING"):
        res = celery_app.dispatch_due.delay()
        assert res.get(timeout=30)["queued"] == 1
        for _ in range(60):
            if _get(client, admin, item["id"])["status"] == "published":
                break
            import time
            time.sleep(0.5)
    assert _get(client, admin, item["id"])["status"] == "published"
