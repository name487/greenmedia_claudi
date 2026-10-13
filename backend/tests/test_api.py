from .conftest import login


def test_login_rejects_bad_password(client):
    assert client.post("/api/auth/login", json={"email": "admin@greenmedia.in", "password": "nope"}).status_code == 401
    assert client.get("/api/dashboard").status_code == 401


def test_me_exposes_role_capabilities(client, admin, portal):
    me = client.get("/api/auth/me", headers=admin).json()
    assert "settings" in me["sections"] and "review.publish" in me["permissions"]
    me = client.get("/api/auth/me", headers=portal).json()
    assert me["client_name"] == "Smile Dental Studio" and "clients" not in me["sections"]


def test_client_portal_is_isolated(client, portal):
    own = client.get("/api/auth/me", headers=portal).json()["client_id"]
    reviews = client.get("/api/reviews?filter=all", headers=portal).json()["items"]
    assert reviews and {r["client_id"] for r in reviews} == {own}
    assert client.get(f"/api/clients/{own + 1}", headers=portal).status_code == 404
    assert client.get(f"/api/reviews?client_id={own + 1}", headers=portal).status_code == 404
    assert client.get("/api/settings", headers=portal).status_code == 403
    dash = client.get("/api/dashboard", headers=portal).json()
    assert [c["id"] for c in dash["client_performance"]] == [own]


def _first(client, h, pred):
    return next(r for r in client.get("/api/reviews?filter=all", headers=h).json()["items"] if pred(r))


def test_review_flow_and_low_rating_escalation(client, admin):
    r = _first(client, admin, lambda r: r["reply_status"] == "new" and r["rating"] <= 2)
    d = client.post(f"/api/reviews/{r['id']}/draft", headers=admin).json()
    assert d["reply_status"] == "drafted" and d["source"] == "template" and "sorry" in d["reply"]
    # 2★ or less cannot be published until approved
    assert client.post(f"/api/reviews/{r['id']}/publish", headers=admin).status_code == 409
    assert client.post(f"/api/reviews/{r['id']}/approve", headers=admin).json()["reply_status"] == "approved"
    # editing an approved reply sends it back to drafted
    assert client.patch(f"/api/reviews/{r['id']}", json={"reply": "Edited reply"}, headers=admin).json()["reply_status"] == "drafted"
    client.post(f"/api/reviews/{r['id']}/approve", headers=admin)
    pub = client.post(f"/api/reviews/{r['id']}/publish", headers=admin).json()
    assert pub["reply_status"] == "published" and pub["published_at"]
    actions = [a["action"] for a in client.get("/api/audit", headers=admin).json()]
    assert "published reply (sample — not sent to Google)" in actions and "approved reply" in actions  # seeded reviews are samples


def test_roles_cannot_exceed_permissions(client, admin):
    writer = login(client, "sneha@greenmedia.in")
    r = _first(client, admin, lambda r: r["reply_status"] == "new" and r["rating"] >= 4)
    client.post(f"/api/reviews/{r['id']}/draft", headers=writer)
    assert client.post(f"/api/reviews/{r['id']}/publish", headers=writer).status_code == 403
    seo = login(client, "rohit@greenmedia.in")
    assert client.get("/api/reviews", headers=seo).status_code == 403


def test_sample_reviews_publish_without_google_even_when_disconnected(client, admin):
    clients = client.get("/api/clients", headers=admin).json()
    offline = next(c for c in clients if not c["gmb_connected"])
    r = _first(client, admin, lambda r: r["client_id"] == offline["id"] and r["reply_status"] == "new" and r["rating"] >= 3)
    assert r["is_sample"]
    client.post(f"/api/reviews/{r['id']}/draft", headers=admin)
    assert client.post(f"/api/reviews/{r['id']}/publish", headers=admin).status_code == 409  # not approved yet
    client.post(f"/api/reviews/{r['id']}/approve", headers=admin)
    res = client.post(f"/api/reviews/{r['id']}/publish", headers=admin)
    assert res.status_code == 200 and res.json()["reply_status"] == "published"
    assert client.get("/api/audit", headers=admin).json()[0]["action"] == "published reply (sample — not sent to Google)"


def test_content_generate_approve_publish(client, admin):
    gen = client.post("/api/content/generate", headers=admin, json={"client_id": 1, "topic": "Diwali offer", "platforms": ["gmb", "facebook", "youtube"]}).json()
    # youtube is not connected for this client, so it is dropped
    assert [v["platform"] for v in gen["variants"]] == ["gmb", "facebook"]
    body = {"client_id": 1, "topic": "Diwali offer", "master_copy": gen["master_copy"], "hashtags": gen["hashtags"], "variants": gen["variants"],
            "scheduled_at": "2030-01-01T10:00:00Z", "status": "in_review"}
    item = client.post("/api/content", headers=admin, json=body).json()
    assert client.post(f"/api/content/{item['id']}/publish", headers=admin).status_code == 409  # must be approved first
    assert client.post(f"/api/content/{item['id']}/approve", headers=admin).json()["status"] == "scheduled"
    pub = client.post(f"/api/content/{item['id']}/publish", headers=admin).json()
    assert pub["status"] == "published" and all(v["external_post_id"] for v in pub["variants"])


def test_content_publish_fails_on_expired_token_then_retries(client, admin):
    sunrise = next(c for c in client.get("/api/clients?q=Sunrise", headers=admin).json())
    body = {"client_id": sunrise["id"], "topic": "Eye camp", "master_copy": "x", "variants": [{"platform": "instagram", "copy": "x", "format": "4:5"}],
            "scheduled_at": "2030-01-01T10:00:00Z", "status": "scheduled"}
    assert "Instagram needs an image" in client.post("/api/content", headers=admin, json=body).json()["detail"]  # refused before scheduling
    item = client.post("/api/content", headers=admin, json={**body, "image_url": "https://cdn.example.com/eye-camp.jpg"}).json()
    res = client.post(f"/api/content/{item['id']}/publish", headers=admin)
    assert res.status_code == 502 and "expired" in res.json()["detail"]
    client.post(f"/api/clients/{sunrise['id']}/social/instagram/reconnect", headers=admin)
    assert client.post(f"/api/content/{item['id']}/publish", headers=admin).json()["status"] == "published"


def test_client_approval_mode(client, admin, portal):
    client.patch("/api/settings", headers=admin, json={"require_client_approval": True})
    body = {"client_id": 1, "topic": "t", "master_copy": "x", "variants": [{"platform": "gmb", "copy": "x", "format": "4:3"}], "status": "in_review",
            "scheduled_at": "2030-01-01T10:00:00Z"}
    item = client.post("/api/content", headers=admin, json=body).json()
    assert client.post(f"/api/content/{item['id']}/approve", headers=admin).status_code == 403
    assert client.post(f"/api/content/{item['id']}/approve", headers=portal).json()["status"] == "scheduled"


def test_auto_publish_is_opt_in(client, admin):
    client.patch("/api/clients/1", headers=admin, json={"auto_publish": {"reviews": True}})
    ids = []
    for _ in range(12):
        out = client.post("/api/reviews/sync", headers=admin, json={"client_id": 1}).json()
        assert out["mode"] == "sample" and out["sample_reviews"] == 1
        ids += out["clients"][0]["review_ids"]
    got = {r["id"]: r for r in client.get("/api/reviews?filter=all&client_id=1&limit=200", headers=admin).json()["items"]}
    for i in ids:
        r = got[i]
        assert r["reply_status"] == ("published" if r["sentiment"] == "positive" and r["rating"] >= 4 else "drafted"), r
    # Off by default: another client's sync only drafts
    out = client.post("/api/reviews/sync", headers=admin, json={"client_id": 2}).json()
    assert out["auto_published"] == 0 and out["drafted"] == 1


def test_report_generate_and_deliver(client, admin):
    rep = client.post("/api/reports/generate", headers=admin, json={"client_id": 1}).json()
    assert rep["source"] == "template" and "Performance summary" in rep["summary"]
    detail = client.get(f"/api/reports/{rep['id']}", headers=admin).json()
    assert set(detail["kpis"]) >= {"leads", "gmb_views"}
    out = client.post(f"/api/reports/{rep['id']}/deliver", headers=admin, json={"via": "whatsapp"}).json()
    assert out["share_url"].startswith("https://wa.me/") and out["delivered_via"] == "whatsapp"


def test_tasks_and_analytics(client, admin):
    users = client.get("/api/auth/users", headers=admin).json()
    t = client.post("/api/tasks", headers=admin, json={"title": "Fix schema", "client_id": 2, "assigned_to": users[0]["id"], "priority": "high"}).json()
    assert client.patch(f"/api/tasks/{t['id']}", headers=admin, json={"status": "done"}).json()["status"] == "done"
    a = client.get("/api/analytics?days=7", headers=admin).json()
    assert len(a["series"]) == 7 and a["top_clients"]


def test_datetimes_are_utc_with_offset(client, admin):
    items = client.get("/api/content", headers=admin).json()
    assert all(i["scheduled_at"].endswith("+00:00") for i in items if i["scheduled_at"])


def test_gmb_insights_for_content_role(client):
    writer = login(client, "sneha@greenmedia.in")
    assert client.get("/api/analytics", headers=writer).status_code == 403
    assert len(client.get("/api/clients/1/insights?days=45", headers=writer).json()) == 45
