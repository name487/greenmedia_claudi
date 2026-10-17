"""Review Replies in the app: post (approve + publish) in one step, edit a posted reply, delete it, keywords used,
the reviews summary, and Reply Settings feeding the AI prompt."""

from app import ai
from app.db import SessionLocal
from app.models import Review

from .conftest import login
from .test_google import _link


def _pending(client, headers, client_id=1, low=False):
    items = client.get("/api/reviews", headers=headers, params={"client_id": client_id, "filter": "pending", "limit": 200}).json()["items"]
    return next(r for r in items if (r["rating"] <= 2) == low)


def test_owner_posts_and_edits_a_reply(client, portal):
    r = _pending(client, portal)
    out = client.post(f"/api/reviews/{r['id']}/post", headers=portal, json={"reply": "Thanks for visiting our dental clinic in Pune!"}).json()
    assert out["posted"] and out["reply_status"] == "published" and out["message"] == "Reply posted" and out["approved_at"]
    again = client.post(f"/api/reviews/{r['id']}/post", headers=portal, json={"reply": "Thank you so much — see you soon!"}).json()
    assert again["message"] == "Reply updated successfully" and again["reply"] == "Thank you so much — see you soon!"
    # the Replied tab shows it, with the keywords the reply used
    item = next(x for x in client.get("/api/reviews", headers=portal, params={"client_id": 1, "filter": "published", "limit": 200}).json()["items"]
                if x["id"] == r["id"])
    assert item["keywords_used"] == []  # the edited reply no longer mentions the clinic
    client.post(f"/api/reviews/{r['id']}/post", headers=portal, json={"reply": "Glad you liked our dental clinic!"})
    item = next(x for x in client.get("/api/reviews", headers=portal, params={"client_id": 1, "filter": "published", "limit": 200}).json()["items"]
                if x["id"] == r["id"])
    # one row per set of words — the most-searched keyword wins; the business's own name never counts
    [kw] = item["keywords_used"]
    assert kw["words"] == ["dental", "clinic"] and kw["volume"] > 0 and "dental clinic" in kw["keyword"]
    client.post(f"/api/reviews/{r['id']}/post", headers=portal, json={"reply": "Thanks! — Team Smile Dental Studio"})
    item = next(x for x in client.get("/api/reviews", headers=portal, params={"client_id": 1, "filter": "published", "limit": 200}).json()["items"]
                if x["id"] == r["id"])
    assert item["keywords_used"] == []


def test_low_ratings_wait_for_the_account_manager(client, portal, admin):
    r = _pending(client, portal, low=True)
    out = client.post(f"/api/reviews/{r['id']}/post", headers=portal, json={"reply": "Sorry — please call us."}).json()
    assert out["posted"] is False and out["reply_status"] == "approved" and out["approval_rule"] == "owner"
    assert "account manager" in out["message"]
    assert client.post(f"/api/reviews/{r['id']}/publish", headers=admin).json()["reply_status"] == "published"


def test_permissions(client, portal):
    r = _pending(client, portal)
    seo = login(client, "kabir@greenmedia.in")  # no review.approve
    assert client.post(f"/api/reviews/{r['id']}/post", headers=seo, json={"reply": "x"}).status_code == 403
    assert client.delete(f"/api/reviews/{r['id']}/reply", headers=seo).status_code == 403
    other = _pending(client, login(client, "admin@greenmedia.in"), client_id=2)
    assert client.post(f"/api/reviews/{other['id']}/post", headers=portal, json={"reply": "x"}).status_code == 404


def test_delete_reply_from_google(client, admin, google):
    _link(client, admin, google)
    r = next(x for x in client.get("/api/reviews", headers=admin, params={"client_id": 1, "filter": "all", "limit": 200}).json()["items"]
             if not x["is_sample"] and x["reply_status"] != "published" and x["rating"] >= 3)
    client.post(f"/api/reviews/{r['id']}/post", headers=admin, json={"reply": "Thank you!"})
    with SessionLocal() as db:
        ext = db.get(Review, r["id"]).external_review_id
    assert google.replies[ext] == "Thank you!"
    out = client.delete(f"/api/reviews/{r['id']}/reply", headers=admin).json()
    assert out["reply_status"] == "new" and out["reply"] is None and ext not in google.replies
    assert ("DELETE", f"https://mybusiness.googleapis.com/v4/accounts/111/locations/222/reviews/{ext}/reply", "") in google.calls


def test_summary(client, portal):
    s = client.get("/api/reviews/summary", headers=portal, params={"client_id": 1}).json()
    assert s["trend"][0]["label"] == "W1" and 1 <= len(s["trend"]) <= 5
    assert s["counts"]["all"] >= s["counts"]["pending"] + s["counts"]["replied"] and s["counts"]["pending"] > 0
    assert s["rating"] > 0 and s["review_count"] >= s["counts"]["all"]
    q = client.get("/api/reviews/summary", headers=portal, params={"client_id": 1, "period": "quarter"}).json()
    assert len(q["trend"]) == 12 and sum(w["count"] for w in q["trend"]) >= sum(w["count"] for w in s["trend"])
    assert client.get("/api/reviews/summary", headers=portal, params={"client_id": 2}).status_code == 404


def test_reply_settings_drive_the_ai(client, portal, admin):
    d = client.get("/api/clients/1/reply-settings", headers=portal).json()
    assert set(d["settings"]) == {"positive", "negative"} and d["lengths"] == ["ultra", "short", "medium", "long"]
    assert d["samples"]["positive"]["text"] and d["account"]["name"] == "Smile Dental Studio"
    body = {"positive": {"length": "ultra", "language": "hi", "language_name": "Hindi"},
            "negative": {"length": "long", "language": "ta", "language_name": "Tamil"}}
    out = client.put("/api/clients/1/reply-settings", headers=portal, json=body).json()
    assert out["settings"]["positive"]["language"] == "hi" and "धन्यवाद" in out["samples"]["positive"]["text"]
    assert "Tamil" in out["samples"]["negative"]["note"] and len(out["samples"]["negative"]["text"].split(". ")) >= 4
    assert client.put("/api/clients/1/reply-settings", headers=portal, json={**body, "positive": {"length": "huge"}}).status_code == 422
    assert client.put("/api/clients/2/reply-settings", headers=portal, json=body).status_code == 404
    # the prompt follows the category of the review
    with SessionLocal() as db:
        from app.models import Client
        bv = db.get(Client, 1).brand_voice
    pos = ai.review_system_prompt(company="Smile", industry="Dental", city="Pune", phone="", brand_voice=bv, rating=5, keywords=["dentist near me"])
    neg = ai.review_system_prompt(company="Smile", industry="Dental", city="Pune", phone="", brand_voice=bv, rating=1)
    assert "one short sentence" in pos and "Reply in Hindi" in pos and "dentist near me" in pos
    assert "4-6 sentences" in neg and "Reply in Tamil" in neg
    # AI drafts (template here: no AI key) follow it too
    r = _pending(client, portal)
    drafted = client.post(f"/api/reviews/{r['id']}/draft", headers=admin).json()
    assert drafted["reply"].startswith("Thank you,") and len(drafted["reply"]) < 80
