from app.importer import TEMPLATE

from .conftest import login

GOOD = """Company Name,Website,Industry,City,Plan,Status,Services,Contact Name,Contact Email,Contact Phone
Acme Dental,acmedental.in,Dental Clinic,Pune,pro,active,GMB Management;SEO,Dr. A,a@acmedental.in,+91 90000 00001
Beta Cafe,,Cafe,Goa,,,,,,
"""


def _names(client, h):
    return {c["company_name"] for c in client.get("/api/clients", headers=h).json()}


def test_import_creates_clients_with_normalised_fields(client, admin):
    out = client.post("/api/clients/import", headers=admin, json={"csv": GOOD}).json()
    assert out == {"created": 2, "skipped": [], "errors": []}
    acme = next(c for c in client.get("/api/clients?q=Acme", headers=admin).json())
    d = client.get(f"/api/clients/{acme['id']}", headers=admin).json()
    assert d["website"] == "https://acmedental.in" and d["plan"] == "Pro" and d["status"] == "active"
    assert d["services"] == ["GMB Management", "SEO"] and d["contacts"][0]["email"] == "a@acmedental.in"
    beta = next(c for c in client.get("/api/clients?q=Beta", headers=admin).json())
    assert beta["plan"] == "Starter" and beta["status"] == "active"  # defaults


def test_import_is_all_or_nothing_with_line_numbers(client, admin):
    before = _names(client, admin)
    bad = GOOD + "X,,,,Platinum,sleeping,,,not-an-email,\n"
    r = client.post("/api/clients/import", headers=admin, json={"csv": bad})
    assert r.status_code == 422
    errors = r.json()["detail"]["errors"]
    assert len(errors) == 1 and errors[0].startswith("Line 4:")
    assert "company_name is required" in errors[0] and "plan 'Platinum'" in errors[0] and "status 'sleeping'" in errors[0] and "not-an-email" in errors[0]
    assert _names(client, admin) == before  # nothing written


def test_import_skips_existing_and_rejects_duplicates_in_file(client, admin):
    client.post("/api/clients/import", headers=admin, json={"csv": GOOD})
    again = client.post("/api/clients/import", headers=admin, json={"csv": GOOD + "Gamma Gym,,,,,,,,,\n"}).json()
    assert again["created"] == 1 and set(again["skipped"]) == {"Acme Dental", "Beta Cafe"}
    dup = client.post("/api/clients/import", headers=admin, json={"csv": "company_name\nDelta\ndelta\n"})
    assert dup.status_code == 422 and "appears twice" in dup.json()["detail"]["errors"][0]


def test_import_handles_excel_bom_missing_header_and_empty_file(client, admin):
    assert client.post("/api/clients/import", headers=admin, json={"csv": "﻿company_name\nOmega Spa\n"}).json()["created"] == 1
    r = client.post("/api/clients/import", headers=admin, json={"csv": "name,city\nX,Y\n"})
    assert "Missing the required column 'company_name'" in r.json()["detail"]["errors"][0]
    assert client.post("/api/clients/import", headers=admin, json={"csv": "company_name\n"}).status_code == 422


def test_template_imports_cleanly_and_permissions(client, admin):
    assert client.get("/api/clients/import/template", headers=admin).text == TEMPLATE
    assert client.post("/api/clients/import", headers=admin, json={"csv": TEMPLATE}).json()["skipped"] == ["Smile Dental Studio", "Spice Route Kitchen"]
    seo = login(client, "rohit@greenmedia.in")
    assert client.post("/api/clients/import", headers=seo, json={"csv": GOOD}).status_code == 403
