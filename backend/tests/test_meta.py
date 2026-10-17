"""Meta (Facebook Pages + Instagram) against a fake Graph API, per-platform adaptation/checks, calendar endpoint."""

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx

from app.db import SessionLocal
from app.google.crypto import decrypt
from app.meta import api
from app.models import MetaConnection, SocialAccount

from .conftest import login

V = "https://graph.facebook.com/v23.0"
IMG = "https://cdn.example.com/monsoon.jpg"


class FakeMeta:
    """Speaks the Graph API shapes used by app.meta.api."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []
        self.granted = list(api.SCOPES)
        self.page_tokens = {"PAGE1": "page-tok-1", "PAGE2": "page-tok-2"}
        self.dead_tokens: set[str] = set()
        self.fail: dict[str, httpx.Response] = {}
        self.posts: list[dict] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        url = urlparse(str(req.url))
        path = url.path.replace("/v23.0/", "", 1)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        form = {k: v[0] for k, v in parse_qs(req.content.decode()).items()} if req.content else {}
        p = {**q, **form}
        self.calls.append((req.method, path, p))
        j = lambda obj, status=200: httpx.Response(status, json=obj)  # noqa: E731
        if path in self.fail:
            return self.fail.pop(path)
        tok = p.get("access_token")
        if tok in self.dead_tokens:
            return j({"error": {"message": "Error validating access token: The session has been invalidated because the user changed their password.",
                                "type": "OAuthException", "code": 190, "error_subcode": 460, "fbtrace_id": "Axyz"}}, 400)
        if path == "oauth/access_token":
            if p.get("grant_type") == "fb_exchange_token":
                assert p["fb_exchange_token"] == "short-tok" and p["client_secret"] == "meta-secret"
                return j({"access_token": "long-user-tok", "token_type": "bearer", "expires_in": 5184000})
            assert p["code"] == "good-code" and p["redirect_uri"] == "http://testserver/api/meta/callback"
            return j({"access_token": "short-tok", "token_type": "bearer", "expires_in": 5183})
        if path == "me" and req.method == "GET":
            return j({"id": "10001", "name": "Green Media SEO"})
        if path == "me/permissions":
            if req.method == "DELETE":
                return j({"success": True})
            return j({"data": [{"permission": s, "status": "granted"} for s in self.granted]})
        if path == "me/accounts":
            assert tok == "long-user-tok"
            return j({"data": [
                {"id": "PAGE1", "name": "Smile Dental Studio", "access_token": self.page_tokens["PAGE1"], "tasks": ["CREATE_CONTENT", "MANAGE"],
                 "picture": {"data": {"url": "https://fb.example/p1.jpg"}}, "instagram_business_account": {"id": "IG1", "username": "smiledental.pune"}},
                {"id": "PAGE2", "name": "Spice Route Kitchen", "access_token": self.page_tokens["PAGE2"], "tasks": ["CREATE_CONTENT"]},
            ], "paging": {"cursors": {"before": "a", "after": "b"}}})
        if path in ("PAGE1/feed", "PAGE1/photos", "PAGE2/feed", "PAGE2/photos") and req.method == "POST":
            page = path.split("/")[0]
            assert tok == self.page_tokens[page], "posted with the wrong token"
            self.posts.append({"path": path, **p})
            n = len(self.posts)
            return j({"id": f"{page}_{n}"} if path.endswith("feed") else {"id": f"photo{n}", "post_id": f"{page}_{n}"})
        if path == "PAGE1/videos" and req.method == "POST":
            assert tok == self.page_tokens["PAGE1"] and p["file_url"].startswith("https://")
            self.posts.append({"path": path, **p})
            return j({"id": "video1"})
        if path == "IG1/media" and req.method == "POST":
            assert tok == self.page_tokens["PAGE1"]
            assert (p.get("media_type") == "REELS" and p["video_url"].startswith("https://")) or p["image_url"].startswith("https://")
            self.posts.append({"path": path, **p})
            return j({"id": "container1"})
        if path == "IG1/media_publish" and req.method == "POST":
            assert p["creation_id"] == "container1"
            self.posts.append({"path": path, **p})
            return j({"id": "17890001"})
        return j({"error": {"message": f"Unsupported {req.method} {path}", "type": "GraphMethodException", "code": 100}}, 400)


def _connect(client, admin, meta):
    url = client.post("/api/meta/connect", headers=admin).json()["auth_url"]
    q = parse_qs(urlparse(url).query)
    assert url.startswith("https://www.facebook.com/v23.0/dialog/oauth") and "pages_manage_posts" in q["scope"][0] and "instagram_content_publish" in q["scope"][0]
    r = client.get("/api/meta/callback", params={"state": q["state"][0], "code": "good-code"}, follow_redirects=False)
    assert r.status_code == 303
    return parse_qs(urlparse(r.headers["location"]).query)["meta"][0]


def _link(client, admin, meta, cid=1, page="PAGE1", instagram=True):
    _connect(client, admin, meta)
    conn = client.get("/api/meta/status", headers=admin).json()["connections"][0]
    r = client.post(f"/api/clients/{cid}/meta/link", headers=admin, json={"connection_id": conn["id"], "page_id": page, "instagram": instagram})
    assert r.status_code == 200, r.text
    return conn, r.json()


def _schedule(client, admin, platforms, image="", cid=1, copy=None):
    body = {"client_id": cid, "topic": "Monsoon check-up", "master_copy": "Free dental check-up this monsoon! Book at https://smile.example",
            "hashtags": ["#Pune", "#Dentist"], "image_url": image, "status": "scheduled",
            "scheduled_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "variants": [{"platform": p, "copy": (copy or {}).get(p, f"{p}: free check-up this monsoon"), "format": "1:1"} for p in platforms]}
    r = client.post("/api/content", headers=admin, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_connect_stores_long_lived_token_encrypted(client, admin, meta):
    assert _connect(client, admin, meta) == "connected:Green Media SEO"
    st = client.get("/api/meta/status", headers=admin).json()
    c = st["connections"][0]
    assert st["configured"] and c["name"] == "Green Media SEO" and c["status"] == "active" and "pages_manage_posts" in c["scopes"]
    assert timedelta(days=59) < datetime.fromisoformat(c["token_expires_at"]) - datetime.now(timezone.utc) <= timedelta(days=60)
    with SessionLocal() as db:
        stored = db.query(MetaConnection).one().user_token_enc
    assert "long-user-tok" not in stored and decrypt(stored) == "long-user-tok"
    # short → long-lived exchange happened
    assert [c[2].get("grant_type") for c in meta.calls if c[1] == "oauth/access_token"] == [None, "fb_exchange_token"]


def test_missing_permissions_and_forged_state(client, admin, meta):
    meta.granted = ["pages_show_list", "instagram_basic"]
    assert _connect(client, admin, meta).startswith("error:these permissions were not granted: pages_manage_posts")
    r = client.get("/api/meta/callback", params={"state": "forged", "code": "good-code"}, follow_redirects=False)
    assert "invalid_or_expired_state" in r.headers["location"]
    assert client.post("/api/meta/connect", headers=login(client, "sneha@greenmedia.in")).status_code == 403


def test_pages_list_and_link_client(client, admin, meta):
    _connect(client, admin, meta)
    pages = client.get("/api/meta/pages", headers=admin).json()["pages"]
    assert [(p["page_id"], p["name"], (p["instagram"] or {}).get("username")) for p in pages] == [("PAGE1", "Smile Dental Studio", "smiledental.pune"), ("PAGE2", "Spice Route Kitchen", None)]
    assert "page-tok" not in json.dumps(pages)  # tokens never leave the server

    conn = client.get("/api/meta/status", headers=admin).json()["connections"][0]
    out = client.post("/api/clients/1/meta/link", headers=admin, json={"connection_id": conn["id"], "page_id": "PAGE1"}).json()
    assert out["linked"] == ["facebook", "instagram"]
    accts = {a["platform"]: a for a in client.get("/api/clients/1/meta", headers=admin).json()["accounts"]}
    assert accts["facebook"]["is_live"] and accts["facebook"]["external_id"] == "PAGE1" and accts["instagram"]["handle"] == "@smiledental.pune"
    with SessionLocal() as db:
        a = db.query(SocialAccount).filter_by(client_id=1, platform="instagram").one()
        assert decrypt(a.access_token_enc) == "page-tok-1" and "page-tok" not in a.access_token_enc
    assert client.get("/api/meta/pages", headers=admin).json()["pages"][0]["linked_client_name"] == "Smile Dental Studio"
    assert client.post("/api/clients/2/meta/link", headers=admin, json={"connection_id": conn["id"], "page_id": "PAGE1"}).status_code == 409
    assert client.post("/api/clients/2/meta/link", headers=admin, json={"connection_id": conn["id"], "page_id": "NOPE"}).status_code == 404
    # A Page without Instagram links only Facebook
    assert client.post("/api/clients/2/meta/link", headers=admin, json={"connection_id": conn["id"], "page_id": "PAGE2"}).json()["linked"] == ["facebook"]
    assert client.get("/api/meta/status", headers=admin).json()["connections"][0]["linked_accounts"] == 3


def test_publish_facebook_photo_and_instagram(client, admin, meta):
    _link(client, admin, meta)
    item = _schedule(client, admin, ["facebook", "instagram"], image=IMG)
    out = client.post(f"/api/content/{item['id']}/publish", headers=admin).json()
    assert out["status"] == "published"
    ids = {v["platform"]: v["external_post_id"] for v in out["variants"]}
    assert ids == {"facebook": "PAGE1_1", "instagram": "17890001"}
    assert meta.posts[0] == {"path": "PAGE1/photos", "url": IMG, "caption": "facebook: free check-up this monsoon", "access_token": "page-tok-1"}
    assert meta.posts[1]["path"] == "IG1/media" and meta.posts[1]["caption"] == "instagram: free check-up this monsoon"
    assert meta.posts[2]["path"] == "IG1/media_publish"
    # Text-only Facebook post goes to /feed
    item = _schedule(client, admin, ["facebook"])
    client.post(f"/api/content/{item['id']}/publish", headers=admin)
    assert meta.posts[-1]["path"] == "PAGE1/feed" and meta.posts[-1]["message"] == "facebook: free check-up this monsoon"


def test_expired_login_fails_post_flags_account_and_reconnect_heals(client, admin, meta):
    _link(client, admin, meta)
    meta.dead_tokens.add("page-tok-1")
    item = _schedule(client, admin, ["facebook"])
    r = client.post(f"/api/content/{item['id']}/publish", headers=admin)
    assert r.status_code == 502 and "code 190" in r.json()["detail"] and "reconnect Meta" in r.json()["detail"]
    got = next(i for i in client.get("/api/content", headers=admin).json() if i["id"] == item["id"])
    assert got["status"] == "failed" and got["attempts"] == 1  # permanent: not retried
    fb = {a["platform"]: a for a in client.get("/api/clients/1/meta", headers=admin).json()["accounts"]}["facebook"]
    assert fb["status"] == "expired" and "190" in fb["last_error"]
    # Reconnecting Meta refreshes the Page tokens of linked accounts
    meta.page_tokens["PAGE1"] = "page-tok-1b"
    _connect(client, admin, meta)
    fb = {a["platform"]: a for a in client.get("/api/clients/1/meta", headers=admin).json()["accounts"]}["facebook"]
    assert fb["status"] == "connected" and fb["last_error"] == ""
    assert client.post(f"/api/content/{item['id']}/retry", headers=admin).json()["status"] == "published"


def test_rate_limit_is_retried(client, admin, meta):
    _link(client, admin, meta)
    meta.fail["PAGE1/feed"] = httpx.Response(400, json={"error": {"message": "(#4) Application request limit reached", "type": "OAuthException", "code": 4, "is_transient": True}})
    item = _schedule(client, admin, ["facebook"])
    out = client.post(f"/api/content/{item['id']}/publish", headers=admin).json()
    assert out["status"] == "scheduled" and out["next_attempt_at"] and "rate limit" in out["last_error"]


def test_unlink_and_disconnect(client, admin, meta):
    conn, _ = _link(client, admin, meta)
    assert client.delete("/api/clients/1/meta", headers=admin).json()["unlinked"] == ["facebook", "instagram"]
    assert not any(a["is_live"] for a in client.get("/api/clients/1/meta", headers=admin).json()["accounts"])
    _link(client, admin, meta)
    assert client.delete(f"/api/meta/connections/{conn['id']}", headers=admin).json()["unlinked_accounts"] == 2
    assert ("DELETE", "me/permissions", {"access_token": "long-user-tok"}) in meta.calls
    assert client.get("/api/meta/status", headers=admin).json()["connections"] == []


def test_demo_accounts_stay_simulated(client, admin, meta):
    item = _schedule(client, admin, ["facebook"], cid=2)
    assert client.post(f"/api/content/{item['id']}/publish", headers=admin).json()["status"] == "published"
    assert meta.posts == []


# ---------- adapt per platform ----------

def _draft(client, admin, platforms, master, image=""):
    body = {"client_id": 1, "topic": "Monsoon check-up", "master_copy": master, "hashtags": ["#Pune", "#Dentist", "#SmileCare"], "image_url": image,
            "variants": [{"platform": p, "copy": "x", "format": "1:1"} for p in platforms]}
    return client.post("/api/content", headers=admin, json=body).json()


def test_adapt_without_ai_follows_platform_rules(client, admin, meta):
    item = _draft(client, admin, ["gmb"], "x")
    assert "Not connected for Smile Dental Studio: instagram" in client.post(f"/api/content/{item['id']}/adapt", headers=admin,
                                                                             json={"platforms": ["instagram"]}).json()["detail"]
    _link(client, admin, meta)  # Facebook Page + Instagram
    master = "Free dental check-up all monsoon at Smile Dental Studio, Baner. Book now at https://smile.example — limited slots! " * 3
    item = _draft(client, admin, ["gmb", "facebook"], master)
    out = client.post(f"/api/content/{item['id']}/adapt", headers=admin, json={"platforms": ["gmb", "facebook", "instagram"]}).json()
    v = {x["platform"]: x for x in out["variants"]}
    assert out["ai"]["source"] == "template" and set(v) == {"gmb", "facebook", "instagram"}
    assert "#" not in v["gmb"]["copy"] and len(v["gmb"]["copy"]) <= 1500
    assert "https://" not in v["instagram"]["copy"] and "link in bio" in v["instagram"]["copy"] and "#Pune" in v["instagram"]["copy"]
    assert v["facebook"]["copy"].count("#") <= 3
    # Instagram without an image: flagged, and scheduling is refused
    assert {"level": "error", "message": "Instagram needs an image — add an image URL to the post"} in v["instagram"]["checks"]
    client.patch(f"/api/content/{item['id']}", headers=admin, json={"scheduled_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()})
    r = client.post(f"/api/content/{item['id']}/schedule", headers=admin)
    assert r.status_code == 422 and "Instagram needs an image" in r.json()["detail"]
    assert client.patch(f"/api/content/{item['id']}", headers=admin, json={"image_url": "http://insecure.example/x.jpg"}).status_code == 422
    client.patch(f"/api/content/{item['id']}", headers=admin, json={"image_url": IMG})
    assert client.post(f"/api/content/{item['id']}/schedule", headers=admin).json()["status"] == "scheduled"
    assert client.post(f"/api/content/{item['id']}/adapt", headers=admin).status_code == 409  # locked while scheduled
    assert any(a["action"] == "adapted copy per platform (template): Monsoon check-up" and a["details"]["platforms"] == ["gmb", "facebook", "instagram"]
               for a in client.get("/api/audit", headers=admin).json())


def test_adapt_x_length_and_checks(client, admin):
    long = "Big monsoon news from Smile Dental Studio in Baner: free check-ups, whitening offers and a brand new kids corner. " * 4
    item = _draft(client, admin, ["gmb"], long)
    v = client.post(f"/api/content/{item['id']}/adapt", headers=admin, json={"platforms": ["gmb", "facebook"]}).json()["variants"]
    assert all(len(x["copy"]) <= {"gmb": 1500, "facebook": 63206}[x["platform"]] for x in v)
    # A too-long X version would be refused before scheduling
    from app import adapt
    assert any(c["level"] == "error" for c in adapt.check("x", "y" * 300))
    assert len(adapt.adapt("x", long, ["#Pune", "#Dentist", "#Kids"])) <= 280
    assert any("Links aren't clickable" in c["message"] for c in adapt.check("instagram", "See https://a.example", IMG))
    assert any(c["level"] == "error" for c in adapt.check("instagram", " ".join(f"#t{i}" for i in range(31)), IMG))


def test_adapt_with_ai(client, admin, openai, meta):
    _link(client, admin, meta)
    openai.reply = json.dumps({"variants": [
        {"platform": "facebook", "copy": "Rainy days, bright smiles! Free check-ups all monsoon at our Baner clinic. https://smile.example"},
        {"platform": "instagram", "copy": "Monsoon smiles ☔️ Free check-ups all month. Link in bio! #Pune #Dentist"}]})
    item = _draft(client, admin, ["facebook", "instagram"], "Free check-up all monsoon. https://smile.example", image=IMG)
    out = client.post(f"/api/content/{item['id']}/adapt", headers=admin).json()
    assert out["ai"]["source"] == "ai" and {v["platform"]: v["copy"] for v in out["variants"]}["instagram"].startswith("Monsoon smiles")
    assert "never include a URL" in openai.user and "Free check-up all monsoon." in openai.user
    assert all(not [c for c in v["checks"] if c["level"] == "error"] for v in out["variants"])


# ---------- calendar ----------

def test_calendar_range(client, admin):
    start = datetime.now(timezone.utc).date()
    item = _schedule(client, admin, ["facebook"])
    cal = client.get("/api/content/calendar", headers=admin, params={"start": start.isoformat(), "days": 7}).json()
    mine = next(x for x in cal["items"] if x["id"] == item["id"])
    assert mine["status"] == "scheduled" and mine["group"] == "scheduled" and mine["platforms"] == [{"platform": "facebook", "status": "pending"}]
    assert all(cal["start"] <= x["at"] < cal["end"] for x in cal["items"])
    assert item["id"] not in [x["id"] for x in client.get("/api/content/calendar", headers=admin, params={"start": (start + timedelta(days=3)).isoformat(), "days": 7}).json()["items"]]
    assert client.get("/api/content/calendar", headers=admin, params={"start": "nope"}).status_code == 422
    portal = login(client, "anjali@smiledental.in")
    assert {x["client_id"] for x in client.get("/api/content/calendar", headers=portal, params={"start": start.isoformat(), "days": 42}).json()["items"]} <= {1}
