from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import AuditLog, ClientContact, ContentItem, MetricDaily, Review, User

from .conftest import login


def _new(client, h, **kw):
    body = {"company_name": "Nova Physio", "website": "novaphysio.in", "industry": "Healthcare", "city": "Pune", "plan": "Pro", **kw}
    r = client.post("/api/clients", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_create_client_full_and_duplicates(client, admin):
    staff = {u["email"]: u["id"] for u in client.get("/api/auth/users", headers=admin).json()}
    c = _new(client, admin, status="active", services=["SEO", " "], account_manager_id=staff["priya@greenmedia.in"],
             contacts=[{"name": "Dr. Nair", "email": "NAIR@novaphysio.in", "phone": "+91 1"}, {"name": "Front Desk", "is_primary": True}])
    assert c["website"] == "https://novaphysio.in" and c["status"] == "active" and c["services"] == ["SEO"]
    assert c["account_manager_id"] == staff["priya@greenmedia.in"]
    assert [x["name"] for x in c["contacts"]] == ["Front Desk", "Dr. Nair"] and c["contacts"][0]["is_primary"]  # primary first
    assert c["contacts"][1]["email"] == "nair@novaphysio.in"
    assert client.post("/api/clients", headers=admin, json={"company_name": "nova physio"}).status_code == 409  # case-insensitive
    assert client.post("/api/clients", headers=admin, json={"company_name": "X"}).status_code == 422
    assert client.post("/api/clients", headers=admin, json={"company_name": "Bad Mgr", "account_manager_id": 999999}).status_code == 422
    assert client.post("/api/clients", headers=admin, json={"company_name": "Bad Mail", "contact_name": "A B", "contact_email": "nope"}).status_code == 422


def test_edit_every_field(client, admin):
    c = _new(client, admin)
    staff = {u["email"]: u["id"] for u in client.get("/api/auth/users", headers=admin).json()}
    patch = {"company_name": "Nova Physio & Rehab", "website": "https://nova.in", "industry": "Physiotherapy", "city": "Mumbai", "plan": "Agency",
             "status": "paused", "services": ["SEO", "Monthly Reports"], "account_manager_id": staff["rohit@greenmedia.in"], "notes": "VIP"}
    out = client.patch(f"/api/clients/{c['id']}", headers=admin, json=patch).json()
    for k, v in patch.items():
        assert out[k] == v, k
    assert client.patch(f"/api/clients/{c['id']}", headers=admin, json={"company_name": "Smile Dental Studio"}).status_code == 409
    assert client.patch(f"/api/clients/{c['id']}", headers=admin, json={"plan": "Gold"}).status_code == 422
    assert client.patch(f"/api/clients/{c['id']}", headers=admin, json={"account_manager_id": None}).json()["account_manager_id"] is None


def test_list_search_filters_and_sort(client, admin):
    _new(client, admin, contacts=[{"name": "Zed Contact", "email": "zed@nova.in", "phone": "+91 55555"}])
    by = lambda **p: [c["company_name"] for c in client.get("/api/clients", headers=admin, params=p).json()]  # noqa: E731
    assert by(q="55555") == ["Nova Physio"] and by(q="zed@nova") == ["Nova Physio"] and by(q="novaphysio.in") == ["Nova Physio"]
    assert all(n for n in by(plan="Pro")) and "Nova Physio" in by(plan="Pro") and "Nova Physio" not in by(plan="Starter")
    names = by(sort="name")
    assert names == sorted(names, key=str.lower)
    assert by(sort="newest")[0] == "Nova Physio"
    rows = client.get("/api/clients", headers=admin, params={"sort": "pending"}).json()
    assert [r["pending_reviews"] for r in rows] == sorted((r["pending_reviews"] for r in rows), reverse=True)
    priya = next(u["id"] for u in client.get("/api/auth/users", headers=admin).json() if u["email"] == "priya@greenmedia.in")
    assert all(r["account_manager_id"] == priya for r in client.get("/api/clients", headers=admin, params={"manager_id": priya}).json())
    f = client.get("/api/clients/facets", headers=admin).json()
    assert f["plans"] == ["Starter", "Growth", "Pro", "Agency"] and any(m["id"] == priya for m in f["managers"])


def test_contacts_crud_and_primary(client, admin):
    c = _new(client, admin)
    base = f"/api/clients/{c['id']}/contacts"
    a = client.post(base, headers=admin, json={"name": "Asha", "email": "asha@x.in"}).json()
    assert a["is_primary"]  # first contact becomes primary
    b = client.post(base, headers=admin, json={"name": "Bala", "is_primary": True}).json()
    lst = client.get(base, headers=admin).json()
    assert [x["name"] for x in lst] == ["Bala", "Asha"] and [x["is_primary"] for x in lst] == [True, False]
    assert client.patch(f"{base}/{a['id']}", headers=admin, json={"phone": " +91 9 ", "is_primary": True}).json()["phone"] == "+91 9"
    assert client.get(base, headers=admin).json()[0]["name"] == "Asha"
    assert client.patch(f"{base}/{a['id']}", headers=admin, json={"email": "bad"}).status_code == 422
    client.delete(f"{base}/{a['id']}", headers=admin)
    lst = client.get(base, headers=admin).json()
    assert [x["name"] for x in lst] == ["Bala"] and lst[0]["is_primary"]  # next contact promoted
    other = _new(client, admin, company_name="Other Co")
    assert client.patch(f"/api/clients/{other['id']}/contacts/{b['id']}", headers=admin, json={"name": "Hijack"}).status_code == 404


def test_delete_client_removes_everything_and_disables_portal(client, admin, portal):
    cid = client.get("/api/auth/me", headers=portal).json()["client_id"]
    name = client.get(f"/api/clients/{cid}", headers=admin).json()["company_name"]
    assert client.delete(f"/api/clients/{cid}", headers=admin, params={"confirm_name": "wrong"}).status_code == 422
    out = client.delete(f"/api/clients/{cid}", headers=admin, params={"confirm_name": name.upper()}).json()
    assert out["deleted"] and out["removed"]["reviews"] > 0 and out["removed"]["metric_days"] == 395  # the first demo businesses have 13 months
    assert out["disabled_portal_users"] == ["anjali@smiledental.in"]
    assert client.get(f"/api/clients/{cid}", headers=admin).status_code == 404
    with SessionLocal() as db:
        for model in (Review, ContentItem, MetricDaily, ClientContact):
            assert db.scalar(select(func.count()).select_from(model).where(model.client_id == cid)) == 0, model.__name__
        assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action.like(f"deleted client {name}%"))) == 1
        u = db.scalar(select(User).where(User.email == "anjali@smiledental.in"))
        assert u.status == "disabled" and u.client_id is None
    assert client.get("/api/dashboard", headers=portal).status_code == 401  # portal session ends


def test_orphaned_portal_user_sees_nothing(client, admin):
    """Defence in depth: a Client-role user without a client must never see the whole agency."""
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == "anjali@smiledental.in"))
        u.client_id = None
        db.commit()
    portal = login(client, "anjali@smiledental.in")
    assert client.get("/api/clients", headers=portal).json() == []
    assert client.get("/api/clients/1", headers=portal).status_code == 404
    assert client.get("/api/reviews?filter=all", headers=portal).json()["items"] == []


def test_permissions(client, admin):
    c = _new(client, admin)
    seo = login(client, "rohit@greenmedia.in")
    assert client.patch(f"/api/clients/{c['id']}", headers=seo, json={"city": "X"}).status_code == 403
    assert client.post(f"/api/clients/{c['id']}/contacts", headers=seo, json={"name": "Nope"}).status_code == 403
    assert client.delete(f"/api/clients/{c['id']}", headers=seo, params={"confirm_name": "Nova Physio"}).status_code == 403
    assert client.get(f"/api/clients/{c['id']}/contacts", headers=seo).status_code == 200  # can read
