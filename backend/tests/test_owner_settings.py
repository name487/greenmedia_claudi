"""The app's Settings: summary, Preference, My QRs (trackable review QR codes and the printable standee), QR standees,
Change Profile, the privacy choice, Delete Account, Refund Request and the legal pages."""

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from sqlalchemy import select

from app.db import SessionLocal
from app.models import PlanPayment, ReviewQr, Task, User

from .conftest import login


def test_summary(client, portal):
    s = client.get("/api/clients/1/settings", headers=portal).json()
    assert s["client"]["company_name"] == "Smile Dental Studio" and s["client"]["code"] == "#0001"
    assert s["plan"]["state"] == "not_activated" and s["google_connected"] and s["qrs"] == 0
    seo = login(client, "kabir@greenmedia.in")
    assert client.patch("/api/clients/1/preference", headers=seo, json={}).status_code == 403  # Preference: see test_preference


def test_my_qrs_count_scans_and_download(client, portal):
    q = client.post("/api/clients/1/qrs", headers=portal, json={"label": "Front desk"}).json()
    assert len(q["code"]) == 7 and q["url"] == f"https://api.test/q/{q['code']}" and q["scans"] == 0
    r = client.get(f"/q/{q['code']}", follow_redirects=False)
    assert r.status_code == 302 and "google" in r.headers["location"]
    lst = client.get("/api/clients/1/qrs", headers=portal).json()
    assert lst["used"] == 1 and lst["limit"] == 50 and lst["items"][0]["scans"] == 1 and lst["items"][0]["last_scan_at"]
    assert client.get("/q/nope123").status_code == 404

    link = client.post(f"/api/clients/1/qrs/{q['id']}/link", headers=portal).json()
    assert link["filename"] == f"review_qr_{q['code']}.png"
    u = urlparse(link["url"])
    png = client.get(u.path, params=parse_qs(u.query))
    assert png.status_code == 200 and png.headers["content-type"] == "image/png" and png.content[:4] == b"\x89PNG"
    assert client.get(u.path, params={"t": "bad"}).status_code == 401
    assert client.get(f"/q/{q['code']}.png").content[:4] == b"\x89PNG"
    assert client.post("/api/clients/2/qrs", headers=portal, json={}).status_code == 404


def test_qr_standee_claim(client, admin, portal):
    made = client.post("/api/qr-standees", headers=admin, json={"count": 2}).json()["items"]
    assert client.post("/api/qr-standees", headers=portal, json={"count": 1}).status_code == 403
    code = made[0]["code"]
    assert "isn't set up yet" in client.get(f"/q/{code}").text
    out = client.post("/api/clients/1/qrs/claim", headers=portal, json={"code": made[0]["url"]}).json()  # the scanned link
    assert out["code"] == code and out["kind"] == "standee"
    assert client.get(f"/q/{code}", follow_redirects=False).status_code == 302
    assert client.post("/api/clients/1/qrs/claim", headers=portal, json={"code": code.upper()}).status_code == 200  # again: fine
    assert client.post("/api/clients/1/qrs/claim", headers=portal, json={"code": "zzzzzzz"}).status_code == 404
    with SessionLocal() as db:
        db.scalar(select(ReviewQr).where(ReviewQr.code == made[1]["code"])).client_id = 2
        db.commit()
    assert client.post("/api/clients/1/qrs/claim", headers=portal, json={"code": made[1]["code"]}).status_code == 409
    lst = client.get("/api/clients/1/qrs", headers=portal).json()
    assert [i["code"] for i in lst["items"]] == [code] and lst["used"] == 0  # standees don't count against the 50


def test_change_profile_prefs_and_delete_account(client, portal):
    me = client.get("/api/auth/me", headers=portal).json()
    assert me["prefs"] == {"analytics": False}
    assert client.put("/api/auth/prefs", headers=portal, json={"analytics": True}).json()["prefs"] == {"analytics": True}
    profiles = client.get("/api/auth/profiles", headers=portal).json()
    assert profiles["current"] == me["id"] and any(p["user_id"] == me["id"] for p in profiles["profiles"])
    other = next((p for p in profiles["profiles"] if p["user_id"] != me["id"]), None)
    if other:  # the demo owner has a second business on the same number
        sw = client.post("/api/auth/switch", headers=portal, json={"user_id": other["user_id"]}).json()
        assert sw["user"]["id"] == other["user_id"] and sw["access_token"]
    admin_id = 1
    assert client.post("/api/auth/switch", headers=portal, json={"user_id": admin_id}).status_code == 403

    assert client.post("/api/auth/delete-account", headers=portal, json={"confirm": "yes"}).status_code == 422
    assert client.post("/api/auth/delete-account", headers=portal, json={"confirm": "delete"}).json() == {"deleted": True}
    assert client.get("/api/auth/me", headers=portal).status_code == 401  # the login stops working at once
    with SessionLocal() as db:
        u = db.get(User, me["id"])
        assert u.status == "deleted" and u.phone == "" and u.email.endswith("@deleted.invalid")
        assert db.scalar(select(Task).where(Task.client_id == 1, Task.title.like("Account deleted in the app%")))


def _paid(client, portal, plan="pro_12", days_ago=0):
    out = client.post("/api/clients/1/plan/checkout", headers=portal, json={"plan": plan}).json()
    u = urlparse(out["url"])
    client.post(u.path, data={"t": parse_qs(u.query)["t"][0]})
    if days_ago:
        with SessionLocal() as db:
            db.get(PlanPayment, out["id"]).paid_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
            db.commit()
    return out["id"]


def test_refund_requests(client, portal):
    year, old, month = _paid(client, portal), _paid(client, portal, days_ago=9), _paid(client, portal, "social_monthly")
    r = client.get("/api/clients/1/refunds", headers=portal).json()
    assert [p["key"] for p in r["policy"]["plans"]] == ["pro_12", "pro_24", "pro_36", "social_monthly"] and r["policy"]["days"] == 7
    pays = {p["id"]: p for p in r["payments"]}
    assert pays[year]["refundable"] and not pays[old]["refundable"] and "More than 7 days" in pays[old]["why_not"]
    assert not pays[month]["refundable"]
    out = client.post("/api/clients/1/refunds", headers=portal, json={"payment_id": year, "reason": "Changed my mind"})
    assert out.status_code == 201 and out.json()["status"] == "open"
    assert client.post("/api/clients/1/refunds", headers=portal, json={"payment_id": year}).status_code == 409
    assert client.post("/api/clients/1/refunds", headers=portal, json={"payment_id": old}).status_code == 409
    with SessionLocal() as db:
        assert db.scalar(select(Task).where(Task.client_id == 1, Task.title.like("Refund request:%")))


def test_legal_pages(client):
    p = client.get("/api/legal/privacy").json()
    assert p["title"] == "Privacy Policy" and any("Digital Personal Data Protection" in x for s in p["sections"] for x in s["paragraphs"])
    assert client.get("/api/legal/terms").json()["title"] == "Terms of Service"
    assert client.get("/api/legal/refund").json()["plans"][0]["refundable"]
    assert client.get("/api/legal/cookies").status_code == 404
    page = client.get("/legal/privacy")
    assert page.status_code == 200 and "<h1>Privacy Policy</h1>" in page.text
