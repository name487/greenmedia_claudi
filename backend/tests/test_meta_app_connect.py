"""Connect Facebook / Instagram from the mobile app (owners and staff): open Facebook's login, then poll the attempt."""

from urllib.parse import parse_qs, urlparse

from app.config import settings

from .conftest import login


def _start(client, headers, platform="facebook"):
    r = client.post("/api/clients/1/meta/connect", headers=headers, json={"platform": platform})
    assert r.status_code == 201, r.text
    out = r.json()
    state = parse_qs(urlparse(out["auth_url"]).query)["state"][0]
    return out["id"], state


def _status(client, headers, aid):
    return client.get(f"/api/clients/1/meta/connect/{aid}", headers=headers).json()


def test_owner_connects_facebook_and_picks_a_page(client, portal, meta):
    aid, state = _start(client, portal)
    assert _status(client, portal, aid)["status"] == "pending"
    page = client.get("/api/meta/callback", params={"state": state, "code": "good-code"})
    assert page.status_code == 200 and "Go back to the app" in page.text  # an HTML page, not the web dashboard
    st = _status(client, portal, aid)
    assert st["status"] == "choose_page" and {c["page_id"] for c in st["candidates"]} == {"PAGE1", "PAGE2"}
    assert all("access_token" not in c for c in st["candidates"])  # tokens never reach the app
    assert client.post(f"/api/clients/1/meta/connect/{aid}/choose", headers=portal, json={"page_id": "NOPE"}).status_code == 409
    done = client.post(f"/api/clients/1/meta/connect/{aid}/choose", headers=portal, json={"page_id": "PAGE1"}).json()
    assert done["status"] == "connected"
    live = {a["platform"]: a for a in done["accounts"]}
    assert live["facebook"]["external_id"] == "PAGE1" and live["instagram"]["handle"] == "@smiledental.pune" and live["facebook"]["is_live"]
    home = client.get("/api/clients/1/score", headers=portal).json()
    assert all(s["connected"] for s in home["social"])


def test_instagram_links_the_only_page_with_instagram(client, portal, meta):
    aid, state = _start(client, portal, "instagram")
    page = client.get("/api/meta/callback", params={"state": state, "code": "good-code"})
    assert "Instagram connected" in page.text
    st = _status(client, portal, aid)
    assert st["status"] == "connected" and {a["platform"] for a in st["accounts"] if a["is_live"]} == {"facebook", "instagram"}


def test_failures_explain_what_to_fix(client, portal, meta):
    # the owner backed out of Facebook's screen
    aid, state = _start(client, portal)
    client.get("/api/meta/callback", params={"state": state, "error": "access_denied", "error_reason": "user_denied"})
    st = _status(client, portal, aid)
    assert st["status"] == "failed" and st["reason"] == "cancelled" and "closed before the connection was saved" in st["message"]
    # a permission toggle was switched off
    meta.granted = [s for s in meta.granted if s != "pages_manage_posts"]
    aid, state = _start(client, portal)
    client.get("/api/meta/callback", params={"state": state, "code": "good-code"})
    assert _status(client, portal, aid)["reason"] == "permissions"
    # came back to the app without finishing
    aid, _ = _start(client, portal)
    assert client.post(f"/api/clients/1/meta/connect/{aid}/cancel", headers=portal).json()["reason"] == "cancelled"


def test_page_already_linked_elsewhere(client, admin, portal, meta):
    from app.db import SessionLocal
    from app.models import SocialAccount

    with SessionLocal() as db:  # both Pages already belong to other clients
        for n, page in enumerate(["PAGE1", "PAGE2"], start=2):
            db.add(SocialAccount(tenant_id=1, client_id=n, platform="facebook", external_id=page, status="connected"))
        db.commit()
    aid, state = _start(client, portal)
    client.get("/api/meta/callback", params={"state": state, "code": "good-code"})
    assert _status(client, portal, aid)["reason"] == "page_taken"


def test_scope_and_configuration(client, portal, monkeypatch):
    monkeypatch.setattr(settings, "meta_app_id", "")
    r = client.post("/api/clients/1/meta/connect", headers=portal, json={"platform": "facebook"})
    assert r.status_code == 503 and "account manager" in r.json()["detail"]
    assert client.post("/api/clients/2/meta/connect", headers=portal, json={"platform": "facebook"}).status_code == 404
    seo = login(client, "kabir@greenmedia.in")  # staff without client.edit
    assert client.post("/api/clients/1/meta/connect", headers=seo, json={"platform": "facebook"}).status_code == 403
    assert client.post("/api/clients/1/meta/connect", headers=portal, json={"platform": "tiktok"}).status_code == 422


def test_attempts_are_private_to_their_business(client, portal, meta):
    aid, _ = _start(client, portal)
    other = login(client, "anjali@glowupsalon.in")  # same owner, other business
    assert client.get(f"/api/clients/1/meta/connect/{aid}", headers=other).status_code == 404
