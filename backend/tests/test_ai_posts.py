"""AI Post in the app: product items, AI posters, viral videos rendered in the background, the owner's lists,
approve & schedule / reject, free slots, and video publishing to Facebook and Instagram."""

import io
from datetime import datetime, timedelta, timezone

from PIL import Image

from app import media
from app.config import settings

from .conftest import login
from .test_meta import _link


def _png(colour=(200, 80, 60)) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (400, 300), colour).save(b, "PNG")
    return b.getvalue()


def _item(client, headers, name="Teeth Whitening", price="1499", cid=1):
    r = client.post(f"/api/clients/{cid}/items", headers=headers, files={"image": ("p.png", _png(), "image/png")},
                    data={"name": name, "description": "Brighter smile in one visit", "price": price})
    assert r.status_code == 201, r.text
    return r.json()


def test_items_upload_and_validation(client, portal):
    it = _item(client, portal)
    assert it["price_label"] == "Rs 1,499" and it["image_url"].startswith("https://api.test/media/c1/") and it["image_url"].endswith(".jpg")
    rel = it["image_url"].split("/media/")[1]
    assert media.path_of(rel).read_bytes()[:2] == b"\xff\xd8"  # re-encoded as JPEG
    bad = client.post("/api/clients/1/items", headers=portal, files={"image": ("x.png", b"not an image", "image/png")}, data={"name": "Bad"})
    assert bad.status_code == 422 and "isn't a photo" in bad.json()["detail"]
    assert client.post("/api/clients/2/items", headers=portal, files={"image": ("p.png", _png(), "image/png")}, data={"name": "x y"}).status_code == 404
    assert [i["name"] for i in client.get("/api/clients/1/items", headers=portal).json()["items"]] == ["Teeth Whitening"]
    assert client.delete(f"/api/clients/1/items/{it['id']}", headers=portal).status_code == 204


def test_poster_post_waits_for_approval(client, portal, monkeypatch):
    it = _item(client, portal)
    post = client.post("/api/clients/1/ai-posts/poster", headers=portal, json={"item_id": it["id"]}).json()
    assert post["status"] == "in_review" and post["group"] == "pending" and post["media_type"] == "image"
    assert post["image_url"].startswith("https://api.test/media/") and post["caption"]
    assert {p["platform"] for p in post["platforms"]} >= {"gmb"}
    ov = client.get("/api/clients/1/ai-posts/overview", headers=portal).json()
    assert ov["quota"]["posts"]["used"] == 1 and ov["counts"]["pending"] >= 1 and ov["can_approve"]
    monkeypatch.setattr(settings, "ai_posts_monthly", 1)
    assert client.post("/api/clients/1/ai-posts/poster", headers=portal, json={"item_id": it["id"]}).status_code == 429


def test_viral_video_renders_in_the_background(client, portal):
    assert client.post("/api/clients/1/ai-posts/video", headers=portal, json={"template": "deal_alert"}).status_code == 422  # no products yet
    _item(client, portal)
    _item(client, portal, name="Braces", price="")
    assert client.post("/api/clients/1/ai-posts/video", headers=portal, json={"template": "nope"}).status_code == 422
    created = client.post("/api/clients/1/ai-posts/video", headers=portal, json={"template": "deal_alert"}).json()
    assert created["status"] == "generating" and created["gen_progress"] == 0 and len(created["gen_steps"]) == 5
    done = client.get(f"/api/clients/1/ai-posts/{created['id']}", headers=portal).json()  # TestClient ran the background job
    assert done["status"] == "in_review" and done["gen_progress"] == 5 and done["video_url"].endswith(".mp4") and done["image_url"].endswith(".jpg")
    assert b"ftyp" in media.path_of(done["video_url"].split("/media/")[1]).read_bytes()[:16]
    templates = client.get("/api/video-templates", headers=portal).json()["templates"]
    assert len(templates) == 8 and all({"key", "name", "intro", "bg", "accent"} <= set(t) for t in templates)


def test_approve_schedule_reject_and_tabs(client, portal):
    it = _item(client, portal)
    a = client.post("/api/clients/1/ai-posts/poster", headers=portal, json={"item_id": it["id"]}).json()
    b = client.post("/api/clients/1/ai-posts/poster", headers=portal, json={"item_id": it["id"]}).json()
    slot = client.get("/api/clients/1/ai-posts/free-slot", headers=portal).json()
    assert slot["suggested"].endswith("07:00:00+05:30") and slot["suggested"][:10] not in slot["scheduled_dates"]
    out = client.post(f"/api/clients/1/ai-posts/{a['id']}/approve", headers=portal, json={"scheduled_at": slot["suggested"]}).json()
    assert out["status"] == "scheduled" and out["group"] == "approved" and out["approved_at"]
    nxt = client.get("/api/clients/1/ai-posts/free-slot", headers=portal).json()
    assert nxt["suggested"] > slot["suggested"]  # that day is taken now
    rej = client.post(f"/api/clients/1/ai-posts/{b['id']}/reject", headers=portal).json()
    assert rej["status"] == "rejected" and rej["group"] == "rejected"
    tabs = {t: [x["id"] for x in client.get("/api/clients/1/ai-posts", headers=portal, params={"tab": t}).json()["items"]]
            for t in ("pending", "approved", "rejected")}
    assert a["id"] in tabs["approved"] and b["id"] in tabs["rejected"] and a["id"] not in tabs["pending"]
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert client.post(f"/api/clients/1/ai-posts/{b['id']}/approve", headers=portal, json={"scheduled_at": past}).status_code == 422
    # someone who can create but not approve
    seo = login(client, "kabir@greenmedia.in")
    assert client.post(f"/api/clients/1/ai-posts/{b['id']}/approve", headers=seo, json={"scheduled_at": slot["suggested"]}).status_code == 403
    assert client.get("/api/clients/2/ai-posts", headers=portal).status_code == 404


def test_video_publishes_to_facebook_and_instagram_reels(client, admin, meta):
    _link(client, admin, meta)
    _item(client, admin)
    v = client.post("/api/clients/1/ai-posts/video", headers=admin, json={"template": "top_picks"}).json()
    when = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    client.post(f"/api/clients/1/ai-posts/{v['id']}/approve", headers=admin, json={"scheduled_at": when})
    assert client.post(f"/api/content/{v['id']}/publish", headers=admin).json()["status"] == "published"
    out = client.get(f"/api/clients/1/ai-posts/{v['id']}", headers=admin).json()
    assert out["status"] == "published" and out["group"] == "posted"
    fb = next(p for p in meta.posts if p["path"] == "PAGE1/videos")
    reel = next(p for p in meta.posts if p["path"] == "IG1/media")
    assert fb["file_url"] == out["video_url"] and reel["media_type"] == "REELS" and reel["video_url"] == out["video_url"]
    posted = client.get("/api/clients/1/ai-posts", headers=admin, params={"tab": "posted", "period": "week"}).json()["items"]
    assert [p["id"] for p in posted] == [v["id"]]
