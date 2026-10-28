"""Per-client Google sign-in: tokens encrypted on gmb_accounts, persisted refresh, profile + locations, diagnostics."""

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.db import SessionLocal
from app.google import api
from app.google.crypto import decrypt
from app.models import GmbAccount, GoogleConnection

from .conftest import login
from .test_google import ACCOUNT, LOCATION

SECOND = {"name": "locations/333", "title": "Smile Dental Studio - Wakad", "storefrontAddress": {"addressLines": ["4 Wakad Rd"], "locality": "Pune"},
          "metadata": {"mapsUri": "https://maps.google.com/?cid=2"}}


def _client_connect(client, headers, cid=1, code="good-code"):
    r = client.post(f"/api/clients/{cid}/google/connect", headers=headers)
    assert r.status_code == 200, r.text
    state = parse_qs(urlparse(r.json()["auth_url"]).query)["state"][0]
    r = client.get("/api/google/callback", params={"state": state, "code": code}, follow_redirects=False)
    assert r.status_code == 303
    loc = urlparse(r.headers["location"])
    return loc.path, parse_qs(loc.query)["google"][0]


def _gmb(cid=1) -> GmbAccount:
    with SessionLocal() as db:
        g = db.query(GmbAccount).filter_by(client_id=cid).one()
        db.expunge(g)
        return g


def test_client_connect_saves_encrypted_tokens_and_links_the_only_location(client, admin, google):
    path, result = _client_connect(client, admin)
    assert path == "/clients/1/" and result == "linked:Smile Dental Studio - Baner"
    g = _gmb()
    # Encrypted at rest, readable with the server key
    assert "rt-secret" not in g.refresh_token_enc and decrypt(g.refresh_token_enc) == "rt-secret"
    assert not g.access_token_enc.startswith("at-") and decrypt(g.access_token_enc) == "at-1"
    exp = g.token_expires_at if g.token_expires_at.tzinfo else g.token_expires_at.replace(tzinfo=timezone.utc)
    assert timedelta(minutes=55) < exp - datetime.now(timezone.utc) <= timedelta(hours=1)
    assert g.google_email == "greenmediaseoteam2@gmail.com" and g.connection_id is None

    p = client.get("/api/clients/1/google", headers=admin).json()["profile"]
    assert p["is_live"] and p["via"] == "client" and p["google_email"] == "greenmediaseoteam2@gmail.com"
    assert (p["title"], p["address"], p["maps_uri"]) == ("Smile Dental Studio - Baner", "12 Baner Rd, Pune", "https://maps.google.com/?cid=1")
    assert p["own_google"]["status"] == "active" and p["own_google"]["access_token_expires_at"]
    assert p["rating"] == 4.6 and p["review_count"] == 212 and p["last_sync"]  # first sync ran
    assert "token" not in str({k: v for k, v in p.items() if k != "own_google"}) and "rt-secret" not in str(p) and "at-1" not in str(p)
    assert google.refreshes == 0  # the fresh access token from the code exchange was reused


def test_expired_access_token_is_refreshed_and_persisted(client, admin, google):
    _client_connect(client, admin)
    with SessionLocal() as db:  # pretend an hour went by
        db.query(GmbAccount).filter_by(client_id=1).one().token_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    assert client.post("/api/clients/1/gmb/sync", headers=admin).status_code == 200
    assert google.refreshes == 1
    g = _gmb()
    assert decrypt(g.access_token_enc) == "at-2" and g.refresh_token_enc  # new token stored, refresh token kept
    # Stored token is reused by the next request (and by other workers / after a restart) instead of refreshing again
    client.post("/api/clients/1/gmb/sync", headers=admin)
    assert google.refreshes == 1


def test_token_rejected_early_is_refreshed_once_and_retried(client, admin, google):
    _client_connect(client, admin)
    google.valid.clear()  # Google stops accepting the stored (unexpired) access token
    r = client.post("/api/clients/1/gmb/sync", headers=admin)
    assert r.status_code == 200 and google.refreshes == 1


def test_manual_refresh_and_revoked_access(client, admin, google):
    _client_connect(client, admin)
    r = client.post("/api/clients/1/google/refresh", headers=admin).json()
    assert r["ok"] and google.refreshes == 1 and decrypt(_gmb().access_token_enc) == "at-2"
    google.refresh_ok = False
    r = client.post("/api/clients/1/google/refresh", headers=admin)
    assert r.status_code == 502 and "invalid_grant" in r.json()["detail"]
    p = client.get("/api/clients/1/google", headers=admin).json()["profile"]
    assert p["own_google"]["status"] == "revoked" and p["status"] == "expired" and "invalid_grant" in p["last_error"]
    # Reconnecting heals it
    google.refresh_ok = True
    _client_connect(client, admin)
    p = client.get("/api/clients/1/google", headers=admin).json()["profile"]
    assert p["own_google"]["status"] == "active" and p["is_live"]


def test_several_locations_are_listed_for_the_client_to_choose(client, admin, google):
    google.extra_locations = [SECOND]
    _, result = _client_connect(client, admin)
    assert result == "connected:greenmediaseoteam2@gmail.com"
    assert _gmb().is_live is False  # nothing linked yet, demo data untouched
    locs = client.get("/api/clients/1/google/locations", headers=admin).json()
    assert [x["title"] for x in locs["locations"]] == ["Smile Dental Studio - Baner", "Smile Dental Studio - Wakad"]
    assert all(x["connection_id"] is None and x["email"] == "greenmediaseoteam2@gmail.com" for x in locs["locations"])

    bad = client.post("/api/clients/1/google/link", headers=admin, json={"account": ACCOUNT, "location": "locations/999"})
    assert bad.status_code == 404  # the client's Google account doesn't manage it
    out = client.post("/api/clients/1/google/link", headers=admin, json={"account": ACCOUNT, "location": "locations/333", "sync_now": False}).json()
    assert out["gmb"]["title"] == "Smile Dental Studio - Wakad" and out["gmb"]["address"] == "4 Wakad Rd, Pune"
    assert (out["gmb"]["rating"], out["gmb"]["review_count"], out["gmb"]["last_sync"]) == (0, 0, None)  # demo figures cleared

    # Another client can't take the same location
    # Client 2 signs in with the same Google account: only one location is still free, so it's linked automatically
    assert _client_connect(client, admin, cid=2)[1] == "linked:Smile Dental Studio - Baner"
    taken = client.post("/api/clients/2/google/link", headers=admin, json={"account": ACCOUNT, "location": "locations/333"})
    assert taken.status_code == 409
    owners = {x["location"]: x["linked_client_id"] for x in client.get("/api/clients/2/google/locations", headers=admin).json()["locations"]}
    assert owners == {LOCATION: 2, "locations/333": 1}


def test_client_can_also_use_an_agency_connection(client, admin, google):
    # Agency account connected on the Google page; the client workspace offers its locations too
    st = parse_qs(urlparse(client.post("/api/google/connect", headers=admin).json()["auth_url"]).query)["state"][0]
    client.get("/api/google/callback", params={"state": st, "code": "good-code"}, follow_redirects=False)
    conn = client.get("/api/google/status", headers=admin).json()["connections"][0]
    locs = client.get("/api/clients/3/google/locations", headers=admin).json()["locations"]
    assert [x["connection_id"] for x in locs] == [conn["id"]]
    out = client.post("/api/clients/3/google/link", headers=admin, json={"connection_id": conn["id"], "account": ACCOUNT, "location": LOCATION}).json()
    assert out["gmb"]["via"] == "agency" and out["gmb"]["google_email"] == "greenmediaseoteam2@gmail.com"
    with SessionLocal() as db:
        c = db.query(GoogleConnection).one()
        assert decrypt(c.access_token_enc).startswith("at-") and c.token_expires_at is not None  # agency tokens persisted the same way
    # Without its own sign-in, linking "as the client" is refused
    assert client.post("/api/clients/4/google/link", headers=admin, json={"account": ACCOUNT, "location": "locations/x"}).status_code == 400


def test_disconnect_revokes_unless_the_grant_is_shared(client, admin, google):
    _client_connect(client, admin)
    assert client.delete("/api/clients/1/google", headers=admin).json()["ok"]
    g = _gmb()
    assert google.revoked == ["rt-secret"] and not g.refresh_token_enc and not g.access_token_enc and not g.is_live
    assert client.get("/api/clients/1/google", headers=admin).json()["profile"]["own_google"] is None

    # Same Google account also connected for the agency: revoking would cut the agency off too, so don't
    st = parse_qs(urlparse(client.post("/api/google/connect", headers=admin).json()["auth_url"]).query)["state"][0]
    client.get("/api/google/callback", params={"state": st, "code": "good-code"}, follow_redirects=False)
    _client_connect(client, admin)
    client.delete("/api/clients/1/google", headers=admin)
    assert google.revoked == ["rt-secret"]


def test_missing_business_permission_is_reported(client, admin, google):
    google.scope = "openid email"  # user unticked the Business Profile box on Google's consent screen
    path, result = _client_connect(client, admin)
    assert path == "/clients/1/" and result.startswith("error:the Business Profile permission was not granted")
    assert not _gmb().refresh_token_enc


def test_permissions(client, admin, portal, google):
    viewer = login(client, "sneha@greenmedia.in")  # no client.edit
    assert client.post("/api/clients/1/google/connect", headers=viewer).status_code == 403
    assert client.post("/api/clients/1/google/connect", headers=portal).status_code == 403
    _client_connect(client, admin)
    p = client.get("/api/clients/1/google", headers=portal).json()  # the client sees its own profile state, never tokens
    assert p["can_manage"] is False and p["profile"]["is_live"] and "rt-secret" not in str(p)
    assert client.get("/api/clients/2/google", headers=portal).status_code == 404


def test_diagnostics_offline(client, admin):
    d = client.get("/api/google/diagnostics", headers=admin).json()
    checks = {c["key"]: c for c in d["checks"]}
    assert checks["client_id"]["status"] == "ok" and checks["client_secret"]["status"] == "ok"
    assert checks["redirect_uri"]["status"] == "ok" and checks["hosts"]["status"] == "fail"  # testserver vs web.test
    assert [a["api"] for a in d["apis"]][0] == "mybusinessaccountmanagement.googleapis.com" and d["live"] is None


def test_diagnostics_project_number_and_links(client, admin, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "google_client_id", "437254480587-abc.apps.googleusercontent.com")
    d = client.get("/api/google/diagnostics", headers=admin).json()
    assert d["project_number"] == "437254480587"
    assert d["apis"][2]["enable_url"] == "https://console.cloud.google.com/apis/api/mybusiness.googleapis.com/overview?project=437254480587"


@pytest.mark.parametrize("failure,expect", [
    (None, "ok"),
    (httpx.Response(429, json={"error": {"code": 429, "message": "Quota exceeded for quota metric 'Requests' ... limit 0", "status": "RESOURCE_EXHAUSTED"}}), "quota"),
    (httpx.Response(403, json={"error": {"code": 403, "status": "PERMISSION_DENIED",
                                         "message": "My Business API has not been used in project 437254480587 before or it is disabled. SERVICE_DISABLED"}}), "disabled"),
])
def test_diagnostics_live(client, admin, google, failure, expect):
    assert client.get("/api/google/diagnostics?live=1", headers=admin).json()["live"]["status"] == "skipped"
    _client_connect(client, admin)
    if failure is not None:
        google.fail[f"{api.V4_BASE}/"] = failure
    d = client.get("/api/google/diagnostics?live=1", headers=admin).json()
    status = {a["api"]: a["status"] for a in d["apis"]}
    assert d["live"]["status"] == "ok" and d["live"]["email"] == "greenmediaseoteam2@gmail.com"
    assert status["mybusinessaccountmanagement.googleapis.com"] == "ok" and status["mybusinessbusinessinformation.googleapis.com"] == "ok"
    assert status["mybusiness.googleapis.com"] == expect and status["businessprofileperformance.googleapis.com"] == "ok"
    if expect == "disabled":  # the v4 API isn't in the public Library: say where to enable it and what "not found" means
        v4 = next(a for a in d["apis"] if a["api"] == "mybusiness.googleapis.com")
        assert "owns project" in v4["detail"] and "Request Business Profile API access" in v4["detail"]


def test_new_client_without_profile_row_gets_one_on_connect(client, admin, google):
    cid = client.post("/api/clients", headers=admin, json={"company_name": "Fresh Bakery", "plan": "Starter"}).json()["id"]
    assert client.get(f"/api/clients/{cid}/google", headers=admin).json()["profile"] is None
    path, result = _client_connect(client, admin, cid=cid)
    assert path == f"/clients/{cid}/" and result == "linked:Smile Dental Studio - Baner"
    p = client.get(f"/api/clients/{cid}/google", headers=admin).json()["profile"]
    assert p["is_live"] and p["via"] == "client" and p["review_count"] == 212
