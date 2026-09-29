import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal, engine
from app.models import Role, User

from .conftest import login


def test_permissions_come_from_roles_table_and_changes_apply_immediately(client, admin):
    writer = login(client, "sneha@greenmedia.in")
    assert client.get("/api/reviews", headers=writer).status_code == 200
    roles = client.get("/api/roles", headers=admin).json()
    content = next(r for r in roles["roles"] if r["name"] == "content")
    assert content["users"] == 1
    new_sections = [s for s in content["sections"] if s != "reviews"]
    assert client.patch("/api/roles/content", headers=admin, json={"sections": new_sections, "label": "Copywriter"}).status_code == 200
    # Same token, next request: access is re-read from the database.
    assert client.get("/api/reviews", headers=writer).status_code == 403
    me = client.get("/api/auth/me", headers=writer).json()
    assert "reviews" not in me["sections"] and me["role_label"] == "Copywriter"


def test_role_validation_and_admin_lockout(client, admin):
    assert client.patch("/api/roles/seo", headers=admin, json={"sections": ["dashboard", "nope"]}).status_code == 422
    assert client.patch("/api/roles/seo", headers=admin, json={"permissions": ["launch.rockets"]}).status_code == 422
    r = client.patch("/api/roles/admin", headers=admin, json={"permissions": ["client.edit"]})
    assert r.status_code == 409 and "Admin role must keep" in r.json()["detail"]
    assert client.patch("/api/roles/missing", headers=admin, json={"label": "Missing"}).status_code == 404
    manager = login(client, "priya@greenmedia.in")  # account managers can't edit roles
    assert client.patch("/api/roles/seo", headers=manager, json={"label": "SEO"}).status_code == 403


def test_create_user_and_sign_in(client, admin):
    body = {"name": "Meera Joshi", "email": "Meera@GreenMedia.in", "password": "s3cure-pass", "role": "seo"}
    u = client.post("/api/users", headers=admin, json=body).json()
    assert u["email"] == "meera@greenmedia.in" and u["role_label"] == "SEO Specialist"
    assert client.post("/api/users", headers=admin, json=body).status_code == 409  # duplicate email
    r = client.post("/api/auth/login", json={"email": "meera@greenmedia.in", "password": "s3cure-pass"})
    assert r.status_code == 200 and "seo" in r.json()["user"]["sections"] and "reviews" not in r.json()["user"]["sections"]


@pytest.mark.parametrize("body,status", [
    ({"role": "ghost"}, 422),                       # unknown role
    ({"role": "client"}, 422),                      # client portal user without a client
    ({"role": "seo", "client_id": 1}, 422),         # staff user tied to a client
    ({"role": "seo", "password": "short"}, 422),    # password too short
    ({"role": "seo", "email": "not-an-email"}, 422),
])
def test_create_user_validation(client, admin, body, status):
    base = {"name": "Test User", "email": "t@example.com", "password": "long-enough", "role": "seo"}
    assert client.post("/api/users", headers=admin, json={**base, **body}).status_code == status


def test_only_admins_manage_users(client):
    manager = login(client, "priya@greenmedia.in")
    assert client.get("/api/users", headers=manager).status_code == 403
    assert client.post("/api/users", headers=manager, json={"name": "X Y", "email": "x@y.io", "password": "long-enough", "role": "seo"}).status_code == 403


def test_disabling_a_user_revokes_access_immediately(client, admin):
    seo = login(client, "rohit@greenmedia.in")
    uid = client.get("/api/auth/me", headers=seo).json()["id"]
    assert client.patch(f"/api/users/{uid}", headers=admin, json={"status": "disabled"}).json()["status"] == "disabled"
    assert client.get("/api/dashboard", headers=seo).status_code == 401  # existing token stops working
    assert client.post("/api/auth/login", json={"email": "rohit@greenmedia.in", "password": "demo1234"}).status_code == 401


def test_admin_cannot_lock_themselves_out(client, admin):
    me = client.get("/api/auth/me", headers=admin).json()
    assert client.patch(f"/api/users/{me['id']}", headers=admin, json={"status": "disabled"}).status_code == 409
    assert client.patch(f"/api/users/{me['id']}", headers=admin, json={"role": "seo"}).status_code == 409


def test_role_change_and_password_reset(client, admin):
    users = {u["email"]: u for u in client.get("/api/users", headers=admin).json()}
    kabir = users["kabir@greenmedia.in"]
    out = client.patch(f"/api/users/{kabir['id']}", headers=admin, json={"role": "content", "password": "new-password-1"}).json()
    assert out["role"] == "content"
    assert client.post("/api/auth/login", json={"email": "kabir@greenmedia.in", "password": "demo1234"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "kabir@greenmedia.in", "password": "new-password-1"}).status_code == 200


@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="SQLite does not enforce foreign keys by default")
def test_database_rejects_users_with_unknown_roles(client):
    with SessionLocal() as db:
        tenant_id = db.scalar(select(User.tenant_id))
        db.add(User(tenant_id=tenant_id, name="Bad", email="bad@example.com", password_hash="x", role="ghost"))
        with pytest.raises(IntegrityError):
            db.commit()


def test_create_admin_command_on_empty_database(client):
    from app.db import Base
    from app.manage import create_admin

    Base.metadata.drop_all(engine)
    u = create_admin("owner@agency.com", "Agency Owner", "New Agency", "correct-horse")
    with SessionLocal() as db:
        assert {r.name for r in db.scalars(select(Role).where(Role.tenant_id == u.tenant_id))} >= {"admin", "client", "seo"}
    r = client.post("/api/auth/login", json={"email": "owner@agency.com", "password": "correct-horse"})
    assert r.status_code == 200 and "settings" in r.json()["user"]["sections"]
