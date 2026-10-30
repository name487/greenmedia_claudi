"""My Plan (mobile app): plan status, billing details, coupons, checkout and payment history; plus the pages Razorpay
sends the owner back to, its webhook, and the practice checkout used when payments run in demo mode."""

import json
import re
from datetime import datetime, timedelta, timezone
from html import escape

import jwt
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import plans
from ..config import settings
from ..db import get_db
from ..models import Client, PlanPayment, User
from ..security import audit, can, get_client, require_section

router = APIRouter(prefix="/api/clients", tags=["my plan"])
public = APIRouter(prefix="/api/plan", tags=["my plan"])
GSTIN = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


def _may_buy(user: User, c: Client) -> None:
    if user.client_id != c.id and not can(user, "client.edit"):
        raise HTTPException(403, "Only the business owner can manage the plan")


@router.get("/{client_id}/plan")
def my_plan(client_id: int, user: User = Depends(require_section("dashboard")), db: Session = Depends(get_db)):
    c = get_client(db, user, client_id)
    for p in db.scalars(select(PlanPayment).where(PlanPayment.client_id == c.id, PlanPayment.status == "created")):
        plans.refresh(db, p)
    db.commit()
    pays = db.scalars(select(PlanPayment).where(PlanPayment.client_id == c.id, PlanPayment.status != "created").order_by(PlanPayment.id.desc()))
    return {"status": plans.status(c), "offer": plans.OFFER, "plans": plans.PLANS, "default_plan": plans.DEFAULT_PLAN, "compare": plans.COMPARE,
            "billing": {"gstin": "", "billing_address": "", "shipping_same": True, "shipping_address": "", **(c.billing or {})},
            "payments": [plans.payment_out(p) for p in pays], "mandates": [], "payments_mode": plans.mode(), "payments_test": plans.test_mode(),
            "can_buy": user.client_id == c.id or can(user, "client.edit")}


class BillingIn(BaseModel):
    gstin: str = Field("", max_length=15)
    billing_address: str = Field("", max_length=500)
    shipping_same: bool = True
    shipping_address: str = Field("", max_length=500)

    @field_validator("gstin")
    @classmethod
    def _gstin(cls, v: str) -> str:
        v = v.strip().upper()
        if v and not GSTIN.match(v):
            raise ValueError("That GSTIN doesn't look right — it's 15 characters, like 27ABCDE1234F1Z5")
        return v


@router.put("/{client_id}/plan/billing")
def save_billing(client_id: int, body: BillingIn, user: User = Depends(require_section("dashboard")), db: Session = Depends(get_db)):
    c = get_client(db, user, client_id)
    _may_buy(user, c)
    b = body.model_dump()
    b["billing_address"], b["shipping_address"] = b["billing_address"].strip(), b["shipping_address"].strip()
    if b["shipping_same"]:
        b["shipping_address"] = b["billing_address"]
    c.billing = b
    audit(db, user, "updated billing details", client_id=c.id, entity_type="client", entity_id=c.id)
    db.commit()
    return c.billing


class QuoteIn(BaseModel):
    plan: str
    coupon: str = Field("", max_length=40)


@router.post("/{client_id}/plan/quote")
def quote(client_id: int, body: QuoteIn, user: User = Depends(require_section("dashboard")), db: Session = Depends(get_db)):
    get_client(db, user, client_id)
    try:
        return plans.price(body.plan, body.coupon)
    except plans.PlanError as e:
        raise HTTPException(422, str(e))


@router.post("/{client_id}/plan/checkout", status_code=201)
def checkout(client_id: int, body: QuoteIn, user: User = Depends(require_section("dashboard")), db: Session = Depends(get_db)):
    c = get_client(db, user, client_id)
    _may_buy(user, c)
    contact = c.contacts[0] if c.contacts else None
    info = {"name": (contact.name if contact else "") or c.company_name, "email": (contact.email if contact else "") or user.email,
            "contact": re.sub(r"[^\d+]", "", (contact.phone if contact else "") or user.phone or "")}
    try:
        pay = plans.checkout(db, c, user.id, body.plan, body.coupon, info, f"{settings.public_base_url}/api/plan/razorpay/callback")
    except plans.PlanError as e:
        raise HTTPException(422, str(e))
    if pay.provider == "demo":
        token = jwt.encode({"purpose": "demo_checkout", "pid": pay.id, "exp": datetime.now(timezone.utc) + timedelta(minutes=30)},
                           settings.jwt_secret, algorithm="HS256")
        pay.checkout_url = f"{settings.public_base_url}/api/plan/demo-checkout/{pay.id}?t={token}"
    audit(db, user, f"started plan checkout: {body.plan} (₹{pay.amount // 100:,})", client_id=c.id, entity_type="plan_payment", entity_id=pay.id)
    db.commit()
    return {**plans.payment_out(pay), "url": pay.checkout_url}


@router.get("/{client_id}/plan/payments/{payment_id}")
def payment_status(client_id: int, payment_id: int, user: User = Depends(require_section("dashboard")), db: Session = Depends(get_db)):
    """The app asks this when the owner comes back from the payment page."""
    c = get_client(db, user, client_id)
    pay = db.scalar(select(PlanPayment).where(PlanPayment.id == payment_id, PlanPayment.client_id == c.id))
    if not pay:
        raise HTTPException(404, "Payment not found")
    plans.refresh(db, pay)
    db.commit()
    return {**plans.payment_out(pay), "plan_status": plans.status(c)}


# ---------- pages the owner's browser lands on, and Razorpay's webhook ----------

def _page(title: str, text: str, ok: bool, extra: str = "") -> HTMLResponse:
    colour = "#2e9e5b" if ok else "#c53030"
    return HTMLResponse(f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>{escape(title)}</title><style>body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0;padding:24px;color:#14231b;max-width:520px;margin:auto}}
.card{{border:1px solid #e3e8ef;border-radius:16px;padding:22px;margin-top:24px;text-align:center}} h1{{color:{colour};font-size:22px}}
.muted{{color:#5b6b62}} button{{background:#0e1a3a;color:#fff;border:0;border-radius:12px;padding:14px 18px;font-size:16px;width:100%;margin-top:16px}}
.demo{{background:#fff4e5;color:#8a4b00;border-radius:10px;padding:10px;font-weight:600}}</style></head><body>
<div class=card><h1>{escape(title)}</h1><p class=muted>{escape(text)}</p>{extra}</div></body></html>""")


@public.get("/razorpay/callback")
def razorpay_callback(request: Request, db: Session = Depends(get_db)):
    params = dict(request.query_params)
    pay = plans.by_link(db, params.get("razorpay_payment_link_id", ""))
    if pay and plans.callback_ok(params) and params.get("razorpay_payment_link_status") == "paid":
        plans.mark_paid(db, pay, params.get("razorpay_payment_id", ""))
    elif pay:
        plans.refresh(db, pay)  # Razorpay's own answer decides
    db.commit()
    if pay and pay.status == "paid":
        return _page("Payment successful", "Your plan is active. Go back to the app to see it.", True)
    return _page("We couldn't confirm the payment yet", "If money was taken, your plan shows as active in the app within a few minutes.", False)


@public.post("/razorpay/webhook")
async def razorpay_webhook(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    if not plans.webhook_ok(raw, request.headers.get("X-Razorpay-Signature", "")):
        raise HTTPException(400, "Bad signature")
    event = json.loads(raw)
    if event.get("event") == "payment_link.paid":
        link = event["payload"]["payment_link"]["entity"]
        pay = plans.by_link(db, link["id"])
        if pay:
            plans.mark_paid(db, pay, event["payload"].get("payment", {}).get("entity", {}).get("id", ""))
            db.commit()
    return {"ok": True}


def _demo_payment(db: Session, payment_id: int, t: str) -> PlanPayment:
    try:
        claims = jwt.decode(t, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "This checkout link has expired — start again from the app")
    pay = db.get(PlanPayment, payment_id)
    if claims.get("purpose") != "demo_checkout" or claims.get("pid") != payment_id or not pay or pay.provider != "demo":
        raise HTTPException(401, "This checkout link is not valid")
    if plans.mode() != "demo":
        raise HTTPException(409, "Practice payments are switched off")
    return pay


@public.get("/demo-checkout/{payment_id}", response_class=HTMLResponse)
def demo_checkout(payment_id: int, t: str, db: Session = Depends(get_db)):
    pay = _demo_payment(db, payment_id, t)
    if pay.status == "paid":
        return _page("Already paid", "This plan is active. Go back to the app.", True)
    p = plans.PLAN[pay.plan_key]
    off = f"<p class=muted>Coupon {escape(pay.coupon)}: −₹{(pay.list_amount - pay.amount) // 100:,}</p>" if pay.coupon else ""
    form = (f"<p class=demo>PRACTICE CHECKOUT — no money moves. Live payments use Razorpay once its keys are set.</p>{off}"
            f"<form method=post><input type=hidden name=t value='{escape(t)}'><button>Pay ₹{pay.amount // 100:,} (practice)</button></form>")
    return _page(f"{p['name']} plan", f"₹{pay.amount // 100:,} {p['per']}", True, form)


@public.post("/demo-checkout/{payment_id}", response_class=HTMLResponse)
def demo_pay(payment_id: int, t: str = Form(...), db: Session = Depends(get_db)):
    pay = _demo_payment(db, payment_id, t)
    plans.mark_paid(db, pay, f"demo_{pay.id}")
    db.commit()
    return _page("Payment successful", "Practice payment done — your plan is active. Go back to the app.", True)
