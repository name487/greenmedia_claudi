"""Google Media in the app: photos and videos for the Google profile — validation, now or one a day, approval for people
who can't approve, the scheduler's upload (simulated for demo profiles, the real media API for live ones), retry, remove."""

import io
import subprocess
from datetime import datetime, timedelta, timezone

import httpx
from imageio_ffmpeg import get_ffmpeg_exe
from PIL import Image

from app import google_media, jobs
from app.ai_posts import TZ
from app.db import SessionLocal
from app.google import api
from app.models import GoogleMedia

from .conftest import login
from .test_google import ACCOUNT, LOCATION, _link


def _png(size=(800, 600)) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", size, (40, 140, 90)).save(b, "PNG")
    return b.getvalue()


def _mp4(seconds: float) -> bytes:
    r = subprocess.run([get_ffmpeg_exe(), "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size=160x120:rate=10:duration={seconds}",
                        "-pix_fmt", "yuv420p", "-f", "mp4", "-movflags", "frag_keyframe+empty_moov", "-"], capture_output=True, check=True)
    return r.stdout


def _add(client, headers, data=None, name="shop.png", ctype="image/png", category="EXTERIOR", when="now", cid=1):
    return client.post(f"/api/clients/{cid}/google-media", headers=headers, files={"file": (name, data or _png(), ctype)},
                       data={"category": category, "when": when})


def _sweep():
    with SessionLocal() as db:
        return jobs.google_media(db)


def test_photo_uploads_now_and_shows_under_uploaded(client, portal):
    cats = client.get("/api/google-media/categories", headers=portal).json()["categories"]
    assert [c["label"] for c in cats][:4] == ["Exterior Photos", "Interior Photos", "Product Photos", "Staff in Action"]
    r = _add(client, portal)
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["status"] == "scheduled" and m["group"] == "scheduled" and m["kind"] == "photo" and m["category_label"] == "Exterior Photos"
    assert m["url"].startswith("https://api.test/media/c1/") and not m["needs_approval"]
    ov = client.get("/api/clients/1/google-media", headers=portal).json()
    assert ov["counts"] == {"scheduled": 1, "uploaded": 0, "not_posted": 0} and ov["connected"] and ov["can_approve"]
    assert _sweep()["uploaded"] == 1 and _sweep()["uploaded"] == 0  # once
    up = client.get("/api/clients/1/google-media", headers=portal, params={"tab": "uploaded"}).json()
    assert [i["id"] for i in up["items"]] == [m["id"]] and up["items"][0]["uploaded_at"] and up["counts"]["scheduled"] == 0
    with SessionLocal() as db:
        assert db.get(GoogleMedia, m["id"]).external_name.startswith("demo-media-")
    assert client.delete(f"/api/clients/1/google-media/{m['id']}", headers=portal).status_code == 409  # it's on Google now


def test_validation(client, portal):
    assert "too small" in _add(client, portal, _png((200, 600))).json()["detail"]
    assert "isn't a photo" in _add(client, portal, b"nope").json()["detail"]
    assert _add(client, portal, category="SELFIE").status_code == 422
    assert "isn't a video" in _add(client, portal, b"nope", "clip.mp4", "video/mp4").json()["detail"]
    assert "Use an MP4" in _add(client, portal, b"nope", "clip.avi", "video/x-msvideo").json()["detail"]
    assert _add(client, portal, cid=2).status_code == 404


def test_video_gets_a_thumbnail_and_the_30_second_limit(client, portal):
    v = _add(client, portal, _mp4(2), "clip.mp4", "video/mp4", category="AT_WORK").json()
    assert v["kind"] == "video" and v["url"].endswith(".mp4") and v["thumb_url"].endswith(".jpg")
    long = _add(client, portal, _mp4(31), "long.mp4", "video/mp4")
    assert long.status_code == 422 and "up to 30 seconds" in long.json()["detail"]


def test_one_a_day_from_tomorrow(client, portal):
    ids = [_add(client, portal, when="spread").json()["id"] for _ in range(3)]
    items = client.get("/api/clients/1/google-media", headers=portal).json()["items"]
    assert [i["id"] for i in items] == ids
    tomorrow = datetime.now(TZ).date() + timedelta(days=1)
    days = [datetime.fromisoformat(i["scheduled_at"]).astimezone(TZ) for i in items]
    assert [d.date() for d in days] == [tomorrow + timedelta(days=n) for n in range(3)] and all(d.hour == 11 for d in days)
    assert _sweep()["uploaded"] == 0  # not due yet
    assert client.delete(f"/api/clients/1/google-media/{ids[1]}", headers=portal).status_code == 204
    assert len(client.get("/api/clients/1/google-media", headers=portal).json()["items"]) == 2


def test_someone_who_cant_approve_waits_for_approval(client, portal):
    seo = login(client, "kabir@greenmedia.in")  # can add content, can't approve
    m = _add(client, seo).json()
    assert m["status"] == "pending" and m["needs_approval"]
    assert _sweep()["uploaded"] == 0
    assert client.post(f"/api/clients/1/google-media/{m['id']}/approve", headers=seo).status_code == 403
    ok = client.post(f"/api/clients/1/google-media/{m['id']}/approve", headers=portal).json()
    assert ok["status"] == "scheduled"
    assert client.post(f"/api/clients/1/google-media/{m['id']}/approve", headers=portal).status_code == 409
    assert _sweep()["uploaded"] == 1


def test_live_profile_gets_the_photo_through_the_media_api_and_failures_can_be_retried(client, admin, google):
    _link(client, admin, google)
    google.fail[f"{api.V4_BASE}/{ACCOUNT}/{LOCATION}/media"] = httpx.Response(400, json={"error": {"code": 400, "message": "Image too blurry", "status": "INVALID_ARGUMENT"}})
    m = _add(client, admin, category="INTERIOR").json()
    assert _sweep()["failed"] == 1
    failed = client.get("/api/clients/1/google-media", headers=admin, params={"tab": "not_posted"}).json()["items"][0]
    assert failed["id"] == m["id"] and "blurry" in failed["error"]

    google.fail.clear()
    assert client.post(f"/api/clients/1/google-media/{m['id']}/retry", headers=admin).json()["status"] == "scheduled"
    assert _sweep()["uploaded"] == 1
    assert google.media[-1] == {"mediaFormat": "PHOTO", "locationAssociation": {"category": "INTERIOR"}, "sourceUrl": m["url"]}
    with SessionLocal() as db:
        assert db.get(GoogleMedia, m["id"]).external_name == f"{ACCOUNT}/{LOCATION}/media/m1"


def test_interrupted_upload_is_not_retried_blindly(client, portal):
    m = _add(client, portal).json()
    with SessionLocal() as db:
        row = db.get(GoogleMedia, m["id"])
        row.status, row.scheduled_at = "publishing", datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()
    _sweep()
    got = client.get("/api/clients/1/google-media", headers=portal, params={"tab": "not_posted"}).json()["items"]
    assert got[0]["id"] == m["id"] and "interrupted" in got[0]["error"]
    assert google_media.GROUP["failed"] == "not_posted"
