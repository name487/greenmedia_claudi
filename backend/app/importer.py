"""Bulk client import from CSV (web upload and `python -m app.manage import-clients`).

All-or-nothing: every row is validated first; if any row has an error nothing is written and the
errors are returned with their CSV line numbers. Clients whose name already exists are skipped."""

import csv
import io
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import AuditLog, Client, ClientContact

COLUMNS = ["company_name", "website", "industry", "city", "plan", "status", "services",
           "contact_name", "contact_email", "contact_phone"]
PLANS = {"starter": "Starter", "growth": "Growth", "pro": "Pro", "agency": "Agency"}
STATUSES = {"active", "onboarding", "paused"}
DEFAULT_SERVICES = ["GMB Management", "Review Management"]
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

TEMPLATE = (
    ",".join(COLUMNS) + "\n"
    "Smile Dental Studio,https://www.smiledental.in,Dental Clinic,Pune,Pro,active,GMB Management;Review Management;SEO,"
    "Dr. Anjali Rao,anjali@smiledental.in,+91 98765 43210\n"
    "Spice Route Kitchen,https://spiceroute.in,Restaurant,Bengaluru,Growth,onboarding,,Ravi Kumar,ravi@spiceroute.in,\n"
)


def _norm_website(v: str) -> str:
    v = v.strip()
    if v and not re.match(r"^https?://", v, re.I):
        v = "https://" + v
    return v


def parse(text: str) -> tuple[list[dict], list[str]]:
    """Returns (rows, errors). Header names are case/space-insensitive; unknown columns are ignored."""
    text = text.lstrip("﻿")  # Excel's UTF-8 BOM
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return [], ["The file is empty."]
    header = {h: h.strip().lower().replace(" ", "_") for h in reader.fieldnames if h}
    if "company_name" not in header.values():
        return [], [f"Missing the required column 'company_name'. Expected columns: {', '.join(COLUMNS)}"]
    rows, errors, seen = [], [], set()
    for line, raw in enumerate(reader, start=2):
        r = {header[k]: (v or "").strip() for k, v in raw.items() if k in header}
        if not any(r.values()):
            continue  # blank line
        name = r.get("company_name", "")
        problems = []
        if len(name) < 2:
            problems.append("company_name is required")
        elif name.lower() in seen:
            problems.append(f"'{name}' appears twice in the file")
        plan = PLANS.get((r.get("plan") or "starter").lower())
        if not plan:
            problems.append(f"plan '{r.get('plan')}' must be one of Starter, Growth, Pro, Agency")
        status = (r.get("status") or "active").lower()
        if status not in STATUSES:
            problems.append(f"status '{r.get('status')}' must be active, onboarding or paused")
        email = r.get("contact_email", "")
        if email and not EMAIL.match(email):
            problems.append(f"contact_email '{email}' is not a valid email")
        if problems:
            errors.append(f"Line {line}: " + "; ".join(problems))
            continue
        seen.add(name.lower())
        services = [s.strip() for s in re.split(r"[;|]", r.get("services", "")) if s.strip()] or DEFAULT_SERVICES
        rows.append({"company_name": name, "website": _norm_website(r.get("website", "")), "industry": r.get("industry", ""),
                     "city": r.get("city", ""), "plan": plan, "status": status, "services": services,
                     "contact_name": r.get("contact_name", ""), "contact_email": email.lower(), "contact_phone": r.get("contact_phone", "")})
    if not rows and not errors:
        errors.append("The file has a header but no client rows.")
    return rows, errors


def import_clients(db: Session, tenant_id: int, user_id: int | None, text: str) -> dict:
    rows, errors = parse(text)
    if errors:
        return {"created": 0, "skipped": [], "errors": errors}
    existing = {n.lower() for n in db.scalars(select(func.lower(Client.company_name)).where(Client.tenant_id == tenant_id))}
    created, skipped = 0, []
    for r in rows:
        if r["company_name"].lower() in existing:
            skipped.append(r["company_name"])
            continue
        c = Client(tenant_id=tenant_id, company_name=r["company_name"], website=r["website"], industry=r["industry"], city=r["city"],
                   plan=r["plan"], status=r["status"], services=r["services"], account_manager_id=user_id,
                   brand_voice={"tone": "Warm and professional", "preferred_phrases": [], "prohibited_claims": [], "cta_style": "Contact us",
                                "languages": ["en"], "escalation_rule": "Ratings of 2 or less go to the account manager before any reply is published."})
        if r["contact_name"]:
            c.contacts.append(ClientContact(tenant_id=tenant_id, name=r["contact_name"], email=r["contact_email"], phone=r["contact_phone"], designation="Owner"))
        db.add(c)
        created += 1
    db.add(AuditLog(tenant_id=tenant_id, user_id=user_id, action=f"imported {created} clients from CSV ({len(skipped)} already existed)", entity_type="client"))
    db.commit()
    return {"created": created, "skipped": skipped, "errors": []}
