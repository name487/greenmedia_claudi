"""My Plan (mobile app): the plans an owner can buy, coupons, and payment through Razorpay Payment Links (a hosted
Razorpay page opened from the app, so the app needs no payment SDK). A payment counts only when Razorpay confirms it —
a signed callback, a signed webhook, or Razorpay's own answer when we ask — never because the app says so.

Without Razorpay keys and with PAYMENTS_DEMO=1, a practice checkout page (clearly marked, no money) stands in for it."""

import calendar
import hashlib
import hmac
import logging
import re
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .ai_posts import TZ, _iso
from .config import settings
from .models import Client, PlanPayment

log = logging.getLogger(__name__)
API = "https://api.razorpay.com/v1"
http = httpx.Client(timeout=30)

# The plans on "Choose your plan" (amounts in paise)
PLANS = [
    {"key": "social_monthly", "name": "Social Media", "tag": "", "amount": 99900, "months": 1, "per": "/ month",
     "note": "Pay for a month at a time. Nothing renews automatically."},
    {"key": "pro_12", "name": "12 Months", "tag": "Guaranteed Growth + Savings", "amount": 1600000, "months": 12, "per": "for 12 months",
     "note": "One payment. Nothing renews automatically."},
    {"key": "pro_24", "name": "24 Months", "tag": "", "amount": 2700000, "months": 24, "per": "for 24 months",
     "note": "One payment. Nothing renews automatically."},
    {"key": "pro_36", "name": "36 Months", "tag": "Best value", "amount": 3600000, "months": 36, "per": "for 36 months",
     "note": "One payment. Nothing renews automatically."},
]
PLAN = {p["key"]: p for p in PLANS}
DEFAULT_PLAN = "pro_12"
OFFER = {"headline": "Unlock Your Growth!", "sub": "Activate AI-powered marketing", "start_amount": 99900, "was_amount": 199900,
         "line": "per month"}

# "Compare plans" (Starter / Pro / 3 Year), section by section
COMPARE = {
    "columns": [{"key": "starter", "name": "Starter", "price": "Rs. 999 / month"},
                {"key": "pro", "name": "Pro", "price": "Rs. 16,000 / year", "badge": "Bestseller"},
                {"key": "three_year", "name": "3 Year Plan", "price": "Rs. 36,000 / 3 years"}],
    "sections": [
        {"title": "Growth", "rows": [["Growth", "-", "2x Growth", "10x Growth"]]},
        {"title": "Content & Posts", "rows": [["Keywords", "Up to 20", "Unlimited", "Unlimited"], ["Posts per month", "10 posts", "25+ posts", "25+ posts"],
                                              ["Photo uploads", "20 / month", "Unlimited", "Unlimited"], ["Video uploads", "5 / month", "Unlimited", "Unlimited"],
                                              ["Website creation", "no", "Included", "Included"]]},
        {"title": "Platform", "rows": [["Instagram & Facebook", "no", "yes", "yes"], ["AI mode", "Basic", "Advanced", "Advanced"]]},
        {"title": "Account & Verification", "rows": [["Account verification", "no", "yes", "yes"], ["New account creation", "no", "yes", "yes"]]},
        {"title": "Analytics", "rows": [["Keyword analysis", "Basic", "Unlimited", "Unlimited"], ["Growth", "-", "2x Growth", "10x Growth"],
                                        ["Reports", "-", "Monthly", "Monthly and Yearly"]]},
        {"title": "Support", "rows": [["Expert support", "Email, 5 tickets / month", "Unlimited", "Unlimited"], ["Onboarding team", "no", "Dedicated", "Dedicated"],
                                      ["Review reply", "Within 24 hours", "Real-time", "Real-time"]]},
    ],
    "footnote": "Prices in Indian Rupees. All features subject to change.",
}


class PlanError(Exception):
    pass


def mode() -> str:
    if settings.razorpay_key_id and settings.razorpay_key_secret:
        return "live"
    return "demo" if settings.payments_demo else "off"


def test_mode() -> bool:
    """Razorpay test keys: real Razorpay pages, but only test cards / UPI and no money moves."""
    return mode() == "live" and settings.razorpay_key_id.startswith("rzp_test_")


def describe() -> str:
    """One line for the startup log: how payments run."""
    m = mode()
    if m == "live":
        return "Payments: Razorpay TEST mode (test key — no real money)" if test_mode() else "Payments: Razorpay LIVE (real money)"
    return "Payments: practice checkout (no Razorpay keys)" if m == "demo" else "Payments: off (no Razorpay keys, PAYMENTS_DEMO=0)"


def today() -> date:
    return datetime.now(TZ).date()


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 + n, 12)
    return date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1]))


def status(c: Client) -> dict:
    t = today()
    if c.plan_until and c.plan_until >= t:
        state = "active"
    elif c.plan_until:
        state = "expired"
    else:
        state = "not_activated"
    p = PLAN.get(c.plan_key)
    return {"state": state, "plan": {"key": p["key"], "name": "Social Media" if p["key"] == "social_monthly" else "Pro"} if p else None,
            "valid_until": c.plan_until.isoformat() if c.plan_until else None,
            "days_left": (c.plan_until - t).days if c.plan_until and c.plan_until >= t else 0}


# ---------- coupons ----------

def _coupons() -> dict[str, tuple[str, int]]:
    out = {}
    for part in filter(None, (x.strip() for x in settings.coupons.split(","))):
        m = re.fullmatch(r"([A-Za-z0-9_-]{3,40}):(\d+)(%?)", part)
        if m:
            out[m[1].upper()] = ("pct" if m[3] else "flat", int(m[2]))
    return out


def price(plan_key: str, coupon: str = "") -> dict:
    p = PLAN.get(plan_key)
    if not p:
        raise PlanError("Unknown plan")
    code = coupon.strip().upper()
    discount, message = 0, ""
    if code:
        rule = _coupons().get(code)
        if not rule:
            raise PlanError("That coupon code isn't valid")
        kind, n = rule
        discount = p["amount"] * min(n, 90) // 100 if kind == "pct" else min(n * 100, p["amount"] - 100)
        message = f"{code} applied — you save ₹{discount // 100:,}"
    return {"plan": plan_key, "list_amount": p["amount"], "discount": discount, "amount": p["amount"] - discount, "coupon": code, "message": message}


# ---------- checkout ----------

def checkout(db: Session, c: Client, user_id: int, plan_key: str, coupon: str, contact: dict, return_url: str) -> PlanPayment:
    m = mode()
    if m == "off":
        raise PlanError("Online payment isn't set up yet — please contact your account manager")
    q = price(plan_key, coupon)
    pay = PlanPayment(tenant_id=c.tenant_id, client_id=c.id, plan_key=plan_key, amount=q["amount"], list_amount=q["list_amount"], coupon=q["coupon"],
                      provider="razorpay" if m == "live" else "demo", created_by=user_id)
    db.add(pay)
    db.flush()
    if m == "live":
        body = {"amount": pay.amount, "currency": "INR", "accept_partial": False, "reference_id": f"gm-plan-{pay.id}",
                "description": f"{PLAN[plan_key]['name']} plan — {c.company_name}"[:2048],
                "customer": {k: v for k, v in contact.items() if v}, "notify": {"sms": False, "email": False}, "reminder_enable": False,
                "callback_url": return_url, "callback_method": "get", "notes": {"client_id": str(c.id), "plan": plan_key}}
        r = http.post(f"{API}/payment_links", json=body, auth=(settings.razorpay_key_id, settings.razorpay_key_secret))
        if r.status_code >= 400:
            log.warning("Razorpay payment link failed: %s %s", r.status_code, r.text[:300])
            raise PlanError("Couldn't start the payment — please try again in a minute")
        link = r.json()
        pay.link_id, pay.checkout_url = link["id"], link["short_url"]
    return pay


def mark_paid(db: Session, pay: PlanPayment, payment_ref: str) -> None:
    """Extend the plan from today, or from the end of the current one if it's still running. Safe to call twice."""
    if pay.status == "paid":
        return
    c = db.get(Client, pay.client_id)
    start = max(today(), (c.plan_until + timedelta(days=1)) if c.plan_until else today())
    end = add_months(start, PLAN[pay.plan_key]["months"]) - timedelta(days=1)
    pay.status, pay.payment_ref, pay.paid_at, pay.period_start, pay.period_end = "paid", payment_ref, datetime.now(timezone.utc), start, end
    c.plan_key, c.plan_until = pay.plan_key, end
    c.plan = "Social Media" if pay.plan_key == "social_monthly" else "Pro"


def refresh(db: Session, pay: PlanPayment) -> PlanPayment:
    """Ask Razorpay for the link's state (when the owner comes back to the app before the webhook lands)."""
    if pay.provider != "razorpay" or pay.status != "created" or not pay.link_id:
        return pay
    r = http.get(f"{API}/payment_links/{pay.link_id}", auth=(settings.razorpay_key_id, settings.razorpay_key_secret))
    if r.status_code >= 400:
        return pay
    link = r.json()
    if link.get("status") == "paid":
        ref = next((p.get("payment_id", "") for p in link.get("payments") or [] if p.get("status") == "captured"), "")
        mark_paid(db, pay, ref)
    elif link.get("status") in ("expired", "cancelled"):
        pay.status = "expired"
    return pay


def callback_ok(params: dict) -> bool:
    """Razorpay's redirect after paying: signature over link_id|reference_id|status|payment_id with the key secret."""
    msg = "|".join(params.get(k, "") for k in ("razorpay_payment_link_id", "razorpay_payment_link_reference_id",
                                               "razorpay_payment_link_status", "razorpay_payment_id"))
    sig = hmac.new(settings.razorpay_key_secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return bool(settings.razorpay_key_secret) and hmac.compare_digest(sig, params.get("razorpay_signature", ""))


def webhook_ok(body: bytes, signature: str) -> bool:
    if not settings.razorpay_webhook_secret:
        return False
    sig = hmac.new(settings.razorpay_webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, signature or "")


def by_link(db: Session, link_id: str) -> PlanPayment | None:
    return db.scalar(select(PlanPayment).where(PlanPayment.link_id == link_id, PlanPayment.provider == "razorpay"))


def payment_out(p: PlanPayment) -> dict:
    return {"id": p.id, "plan": p.plan_key, "plan_name": PLAN.get(p.plan_key, {}).get("name", p.plan_key), "amount": p.amount,
            "list_amount": p.list_amount, "coupon": p.coupon, "status": p.status, "demo": p.provider == "demo",
            "created_at": _iso(p.created_at), "paid_at": _iso(p.paid_at),
            "period_start": p.period_start.isoformat() if p.period_start else None, "period_end": p.period_end.isoformat() if p.period_end else None}
