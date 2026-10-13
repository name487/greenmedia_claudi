"""Master Dashboard KPIs."""

from .conftest import login


def test_master_kpis_shape_and_consistency(client, admin):
    d = client.get("/api/dashboard", headers=admin).json()
    m = d["master"]
    assert set(m) == {"clients", "reviews", "approvals", "content", "ai", "integrations", "leads"}
    assert m["clients"]["total"] == len(d["client_performance"]) == 24
    assert m["reviews"]["needs_reply"] == d["kpis"]["pending_reviews"] and m["reviews"]["negative_waiting"] == d["kpis"]["negative_reviews"]
    assert m["approvals"]["total"] == m["approvals"]["replies_waiting"] + m["approvals"]["posts_waiting"]
    assert m["content"]["failed"] == d["kpis"]["failed_posts"] and m["integrations"]["scheduler"] == "off"
    assert 0 <= m["reviews"]["response_rate_30d"] <= 100
    # health table: lowest first, reasons explain any deduction
    scores = [c["health"] for c in d["client_performance"]]
    assert scores == sorted(scores)
    assert all(c["health_reasons"] for c in d["client_performance"] if c["health"] < 100)
    assert {c["health_label"] for c in d["client_performance"]} <= {"Good", "Watch", "At risk"}
    # the mobile app's keys are unchanged
    assert {"active_clients", "pending_reviews", "negative_reviews", "scheduled_posts", "failed_posts", "leads", "seo_alerts"} <= set(d["kpis"])


def test_kpis_move_with_the_work(client, admin, openai):
    before = client.get("/api/dashboard", headers=admin).json()["master"]
    r = next(x for x in client.get("/api/reviews", headers=admin, params={"filter": "all", "limit": 200}).json()["items"] if x["reply_status"] == "new")
    client.post(f"/api/reviews/{r['id']}/draft", headers=admin)
    after = client.get("/api/dashboard", headers=admin).json()["master"]
    assert after["approvals"]["replies_waiting"] == before["approvals"]["replies_waiting"] + 1
    assert after["ai"]["ai_drafts_30d"] == before["ai"]["ai_drafts_30d"] + 1 and after["ai"]["tokens_30d"] == before["ai"]["tokens_30d"] + 450
    client.post(f"/api/reviews/{r['id']}/approve", headers=admin)
    client.post(f"/api/reviews/{r['id']}/publish", headers=admin)
    done = client.get("/api/dashboard", headers=admin).json()["master"]
    assert done["reviews"]["needs_reply"] == before["reviews"]["needs_reply"] - 1


def test_failed_post_shows_in_attention_and_health(client, admin):
    sunrise = client.get("/api/clients?q=Sunrise", headers=admin).json()[0]
    body = {"client_id": sunrise["id"], "topic": "Eye camp", "master_copy": "x", "image_url": "https://cdn.example.com/x.jpg", "status": "scheduled",
            "scheduled_at": "2030-01-01T10:00:00Z", "variants": [{"platform": "instagram", "copy": "x", "format": "4:5"}]}
    item = client.post("/api/content", headers=admin, json=body).json()
    client.post(f"/api/content/{item['id']}/publish", headers=admin)  # expired Instagram token → failed
    d = client.get("/api/dashboard", headers=admin).json()
    att = next(a for a in d["attention"] if a["kind"] == "failed_post")
    assert att["client_name"] == "Sunrise Eye Hospital" and att["link"].endswith(f"#c{item['id']}") and att["severity"] == "critical"
    row = next(c for c in d["client_performance"] if c["id"] == sunrise["id"])
    assert "1 failed post" in row["health_reasons"] and any("Instagram needs reconnecting" in x for x in row["health_reasons"])


def test_client_portal_sees_only_itself(client, portal):
    d = client.get("/api/dashboard", headers=portal).json()
    assert [c["id"] for c in d["client_performance"]] == [1] and d["master"]["clients"]["total"] == 1
    assert {a["client_id"] for a in d["attention"]} <= {1}
    assert client.get("/api/dashboard", headers=login(client, "kabir@greenmedia.in")).status_code == 200
