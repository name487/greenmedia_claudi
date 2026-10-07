"""Live Google Business Profile integration, against a fake Google that speaks the real API shapes."""

import json
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

import httpx

from app.google import api
from app.jobs import publish_due
from app.db import SessionLocal

ACCOUNT, LOCATION = "accounts/111", "locations/222"


class FakeGoogle:
    def __init__(self):
        self.calls: list[tuple[str, str, object]] = []
        self.refresh_ok = True
        self.replies: dict[str, str] = {}
        self.posts: list[dict] = []
        yday = date.today() - timedelta(days=1)
        self.reviews = [
            {"reviewId": "r-new", "reviewer": {"displayName": "Meena K"}, "starRating": "TWO", "comment": "Waited an hour, staff were rude.",
             "createTime": "2026-09-20T10:00:00Z", "updateTime": "2026-09-20T10:00:00Z"},
            {"reviewId": "r-answered", "reviewer": {"displayName": "Arjun P"}, "starRating": "FIVE", "comment": "Excellent care!",
             "createTime": "2026-09-01T10:00:00Z", "reviewReply": {"comment": "Thank you Arjun!", "updateTime": "2026-09-02T10:00:00Z"}},
            {"reviewId": "r-rating-only", "reviewer": {"displayName": "Anonymous"}, "starRating": "FOUR", "createTime": "2026-08-01T10:00:00Z"},
        ]
        self.metric_day = yday
        self.email = "greenmediaseoteam2@gmail.com"
        self.scope = " ".join(api.SCOPES)
        self.issued = 0           # access tokens handed out
        self.valid: set[str] = set()  # access tokens Google currently accepts
        self.refreshes = 0
        self.revoked: list[str] = []
        self.extra_locations: list[dict] = []
        self.fail: dict[str, httpx.Response] = {}  # URL prefix -> forced error response

    def _issue(self) -> str:
        self.issued += 1
        tok = f"at-{self.issued}"
        self.valid.add(tok)
        return tok

    def __call__(self, req: httpx.Request) -> httpx.Response:
        url, m = str(req.url), req.method
        body = req.content.decode() if req.content else ""
        self.calls.append((m, url.split("?")[0], body))
        j = lambda obj, status=200: httpx.Response(status, json=obj)  # noqa: E731
        if url.startswith(api.REVOKE_URL):
            self.revoked.append(parse_qs(body)["token"][0])
            return j({})
        if url.startswith(api.TOKEN_URL):
            form = parse_qs(body)
            if form["grant_type"] == ["authorization_code"]:
                assert form["code"] == ["good-code"]
                return j({"access_token": self._issue(), "refresh_token": "rt-secret", "expires_in": 3599, "scope": self.scope})
            assert form["refresh_token"] == ["rt-secret"]
            if not self.refresh_ok:
                return j({"error": "invalid_grant", "error_description": "Token has been expired or revoked."}, 400)
            self.refreshes += 1
            return j({"access_token": self._issue(), "expires_in": 3599})
        if req.headers.get("Authorization", "").removeprefix("Bearer ") not in self.valid:
            return j({"error": {"code": 401, "message": "Request had invalid authentication credentials.", "status": "UNAUTHENTICATED"}}, 401)
        for prefix, resp in self.fail.items():
            if url.startswith(prefix):
                return resp
        if url.startswith(api.USERINFO_URL):
            return j({"email": self.email})
        if url.startswith(api.ACCOUNTS_URL):
            return j({"accounts": [{"name": ACCOUNT, "accountName": "Green Media SEO", "type": "PERSONAL"}]})
        if url.startswith(f"{api.INFO_BASE}/{ACCOUNT}/locations"):
            return j({"locations": [{"name": LOCATION, "title": "Smile Dental Studio - Baner", "websiteUri": "https://smile.example",
                                     "storefrontAddress": {"addressLines": ["12 Baner Rd"], "locality": "Pune"}, "metadata": {"mapsUri": "https://maps.google.com/?cid=1"}},
                                    *self.extra_locations]})
        if url.startswith(f"{api.V4_BASE}/{ACCOUNT}/{LOCATION}/reviews") and m == "GET":
            return j({"reviews": self.reviews, "averageRating": 4.6, "totalReviewCount": 212})
        if "/reviews/" in url and url.endswith("/reply") and m == "PUT":
            rid = url.split("/reviews/")[1].split("/")[0]
            self.replies[rid] = json.loads(body)["comment"]
            return j({"comment": self.replies[rid], "updateTime": "2026-09-28T10:00:00Z"})
        if url.startswith(f"{api.V4_BASE}/{ACCOUNT}/{LOCATION}/localPosts") and m == "POST":
            self.posts.append(json.loads(body))
            return j({"name": f"{ACCOUNT}/{LOCATION}/localPosts/p{len(self.posts)}", "state": "LIVE"})
        if ":fetchMultiDailyMetricsTimeSeries" in url:
            q = parse_qs(urlparse(url).query)
            assert "CALL_CLICKS" in q["dailyMetrics"]
            d = self.metric_day
            dv = lambda v: {"datedValues": [{"date": {"year": d.year, "month": d.month, "day": d.day}, "value": str(v)}]}  # noqa: E731
            return j({"multiDailyMetricTimeSeries": [{"dailyMetricTimeSeries": [
                {"dailyMetric": "BUSINESS_IMPRESSIONS_MOBILE_SEARCH", "timeSeries": dv(300)},
                {"dailyMetric": "BUSINESS_IMPRESSIONS_DESKTOP_MAPS", "timeSeries": dv(45)},
                {"dailyMetric": "CALL_CLICKS", "timeSeries": dv(7)},
                {"dailyMetric": "WEBSITE_CLICKS", "timeSeries": dv(12)},
                {"dailyMetric": "BUSINESS_DIRECTION_REQUESTS", "timeSeries": dv(9)},
            ]}]})
        return j({"error": {"code": 404, "message": f"unexpected {m} {url}"}}, 404)


def _connect(client, admin):
    auth_url = client.post("/api/google/connect", headers=admin).json()["auth_url"]
    q = parse_qs(urlparse(auth_url).query)
    assert q["scope"][0].endswith("business.manage") and q["access_type"] == ["offline"]
    r = client.get("/api/google/callback", params={"state": q["state"][0], "code": "good-code"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("http://web.test/gmb/google/?google=connected")
    return client.get("/api/google/status", headers=admin).json()["connections"][0]


def _link(client, admin, google):
    conn = _connect(client, admin)
    loc = client.get("/api/google/locations", headers=admin).json()["locations"][0]
    assert loc["title"] == "Smile Dental Studio - Baner" and loc["address"] == "12 Baner Rd, Pune"
    out = client.post("/api/google/link", headers=admin, json={"client_id": 1, "connection_id": conn["id"], "account": loc["account"],
                                                               "location": loc["location"], "title": loc["title"]}).json()
    return conn, out


def test_connect_stores_encrypted_refresh_token(client, admin, google):
    conn = _connect(client, admin)
    assert conn["email"] == "greenmediaseoteam2@gmail.com" and conn["status"] == "active"
    from app.models import GoogleConnection
    with SessionLocal() as db:
        stored = db.query(GoogleConnection).one().refresh_token_enc
    assert "rt-secret" not in stored  # encrypted at rest


def test_callback_rejects_forged_state(client, google):
    r = client.get("/api/google/callback", params={"state": "forged", "code": "good-code"}, follow_redirects=False)
    assert parse_qs(urlparse(r.headers["location"]).query)["google"] == ["error:invalid_or_expired_state"]


def test_only_managers_can_connect(client, google):
    from .conftest import login
    assert client.post("/api/google/connect", headers=login(client, "sneha@greenmedia.in")).status_code == 403


def test_link_imports_reviews_rating_and_insights(client, admin, google):
    _, out = _link(client, admin, google)
    assert out["sync"]["new_reviews"] == 3 and out["sync"]["total_on_google"] == 212
    c = client.get("/api/clients/1", headers=admin).json()
    assert c["gmb"]["is_live"] and c["gmb"]["rating"] == 4.6 and c["gmb"]["google_email"] == "greenmediaseoteam2@gmail.com"
    items = {r["author"]: r for r in client.get("/api/reviews?filter=all&client_id=1", headers=admin).json()["items"]}
    assert set(items) == {"Meena K", "Arjun P", "Anonymous"}  # demo reviews were removed on going live
    assert items["Arjun P"]["reply_status"] == "published" and items["Arjun P"]["reply"] == "Thank you Arjun!"  # answered on Google already
    assert items["Meena K"]["reply_status"] == "drafted" and items["Meena K"]["reply"] and items["Meena K"]["sentiment"] == "negative"  # AI draft waiting
    assert items["Anonymous"]["reply_status"] == "drafted" and not items["Meena K"]["is_sample"]
    assert items["Anonymous"]["text"] == ""  # rating-only review
    # Insights for yesterday replaced the demo numbers
    a = client.get("/api/clients/1/insights?days=7", headers=admin).json()
    y = next(d for d in a if d["date"] == google.metric_day.isoformat())
    assert (y["gmb_views"], y["gmb_calls"], y["web_clicks"], y["gmb_directions"]) == (345, 7, 12, 9)
    # Re-sync is idempotent
    assert client.post("/api/clients/1/gmb/sync", headers=admin).json()["sync"]["new_reviews"] == 0


def test_reply_publishes_to_google_after_approval(client, admin, google):
    _link(client, admin, google)
    r = next(x for x in client.get("/api/reviews?client_id=1", headers=admin).json()["items"] if x["author"] == "Meena K")
    client.post(f"/api/reviews/{r['id']}/draft", headers=admin)
    assert client.post(f"/api/reviews/{r['id']}/publish", headers=admin).status_code == 409  # 2★ must be approved
    client.patch(f"/api/reviews/{r['id']}", headers=admin, json={"reply": "Meena, we're sorry. Please call us so we can make it right."})
    client.post(f"/api/reviews/{r['id']}/approve", headers=admin)
    assert client.post(f"/api/reviews/{r['id']}/publish", headers=admin).json()["reply_status"] == "published"
    assert google.replies == {"r-new": "Meena, we're sorry. Please call us so we can make it right."}


def test_gmb_post_goes_live_and_scheduler_publishes_due_posts(client, admin, google):
    _link(client, admin, google)
    body = {"client_id": 1, "topic": "Free checkup week", "master_copy": "x", "variants": [{"platform": "gmb", "copy": "Free dental checkups all week!", "format": "4:3"}],
            "status": "scheduled", "scheduled_at": "2030-01-01T10:00:00Z"}
    item = client.post("/api/content", headers=admin, json=body).json()
    with SessionLocal() as db:
        from datetime import datetime, timezone
        from app.models import ContentItem
        db.get(ContentItem, item["id"]).scheduled_at = datetime(2020, 1, 1, tzinfo=timezone.utc)  # now due
        db.commit()
        assert publish_due(db)["published"] >= 1
    assert google.posts[0]["summary"] == "Free dental checkups all week!" and google.posts[0]["topicType"] == "STANDARD"
    got = next(i for i in client.get("/api/content?client_id=1", headers=admin).json() if i["id"] == item["id"])
    assert got["status"] == "published" and got["variants"][0]["external_post_id"].endswith("/localPosts/p1")


def test_revoked_google_access_is_reported_not_silent(client, admin, google):
    _link(client, admin, google)
    google.refresh_ok = False
    google.valid.clear()  # access token revoked too: the API answers 401, the refresh gets invalid_grant
    r = client.post("/api/clients/1/gmb/sync", headers=admin)
    assert r.status_code == 502 and "invalid_grant" in r.json()["detail"]
    c = client.get("/api/clients/1", headers=admin).json()
    assert c["gmb"]["status"] == "expired" and "invalid_grant" in c["gmb"]["last_error"]
    assert client.get("/api/google/status", headers=admin).json()["connections"][0]["status"] == "revoked"


def test_demo_clients_stay_simulated(client, admin, google):
    _link(client, admin, google)
    before = len(google.calls)
    body = {"client_id": 2, "topic": "t", "master_copy": "x", "variants": [{"platform": "gmb", "copy": "x", "format": "4:3"}], "status": "scheduled",
            "scheduled_at": "2030-01-01T10:00:00Z"}
    item = client.post("/api/content", headers=admin, json=body).json()
    assert client.post(f"/api/content/{item['id']}/publish", headers=admin).json()["status"] == "published"
    assert len(google.calls) == before  # no Google traffic for a demo client


def test_unlink_and_disconnect(client, admin, google):
    conn, _ = _link(client, admin, google)
    client.post("/api/google/unlink", headers=admin, json={"client_id": 1})
    assert client.get("/api/clients/1", headers=admin).json()["gmb"]["is_live"] is False
    assert client.delete(f"/api/google/connections/{conn['id']}", headers=admin).json()["ok"]
    assert client.get("/api/google/status", headers=admin).json()["connections"] == []
    assert google.revoked == ["rt-secret"]
