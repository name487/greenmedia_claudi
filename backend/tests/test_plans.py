"""My Plan: status, billing details, coupons, and payment — Razorpay Payment Links (signed callback, signed webhook,
Razorpay's own answer) or, in demo mode, the practice checkout. Nothing activates a plan on the app's word."""

import hashlib
import hmac
import json
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app import plans
from app.config import settings

from .conftest import login


def _parts(url: str) -> tuple[str, str]:
    u = urlparse(url)
    return u.path, parse_qs(u.query)["t"][0]


def test_plan_status_billing_and_coupons(client, portal):
    p = client.get("/api/clients/1/plan", headers=portal).json()
    assert p["status"] == {"state": "not_activated", "plan": None, "valid_until": None, "days_left": 0}
    assert [x["key"] for x in p["plans"]] == ["social_monthly", "pro_12", "pro_24", "pro_36"] and p["default_plan"] == "pro_12"
    assert [c["name"] for c in p["compare"]["columns"]] == ["Starter", "Pro", "3 Year Plan"]
    assert p["payments"] == [] and p["mandates"] == [] and p["payments_mode"] == "demo" and p["can_buy"]

    bad = client.put("/api/clients/1/plan/billing", headers=portal, json={"gstin": "12345"})
    assert bad.status_code == 422 and "GSTIN" in json.dumps(bad.json())
    b = client.put("/api/clients/1/plan/billing", headers=portal,
                   json={"gstin": "27abcde1234f1z5", "billing_address": " 12 Baner Rd, Pune ", "shipping_same": True}).json()
    assert b == {"gstin": "27ABCDE1234F1Z5", "billing_address": "12 Baner Rd, Pune", "shipping_same": True, "shipping_address": "12 Baner Rd, Pune"}
    assert client.get("/api/clients/1/plan", headers=portal).json()["billing"]["gstin"] == "27ABCDE1234F1Z5"

    q = client.post("/api/clients/1/plan/quote", headers=portal, json={"plan": "pro_12", "coupon": "welcome10"}).json()
    assert q["list_amount"] == 1600000 and q["discount"] == 160000 and q["amount"] == 1440000 and "you save ₹1,600" in q["message"]
    assert client.post("/api/clients/1/plan/quote", headers=portal, json={"plan": "pro_12", "coupon": "FREE"}).status_code == 422
    assert client.post("/api/clients/1/plan/quote", headers=portal, json={"plan": "gold"}).status_code == 422
    assert client.get("/api/clients/2/plan", headers=portal).status_code == 404


def test_practice_checkout_activates_and_extends(client, portal):
    out = client.post("/api/clients/1/plan/checkout", headers=portal, json={"plan": "pro_12", "coupon": "WELCOME10"}).json()
    assert out["status"] == "created" and out["demo"] and out["amount"] == 1440000
    path, token = _parts(out["url"])
    page = client.get(path, params={"t": token})
    assert page.status_code == 200 and "PRACTICE CHECKOUT" in page.text and "₹14,400" in page.text
    assert client.get(path, params={"t": token + "x"}).status_code == 401
    assert client.post(path.replace(str(out["id"]), str(out["id"] + 1)), data={"t": token}).status_code == 401
    assert client.get(f"/api/clients/1/plan/payments/{out['id']}", headers=portal).json()["status"] == "created"  # not until paid

    assert "Payment successful" in client.post(path, data={"t": token}).text
    st = client.get(f"/api/clients/1/plan/payments/{out['id']}", headers=portal).json()
    start = plans.today()
    assert st["status"] == "paid" and st["plan_status"]["state"] == "active" and st["plan_status"]["plan"]["name"] == "Pro"
    assert st["plan_status"]["valid_until"] == (plans.add_months(start, 12) - timedelta(days=1)).isoformat()
    client.post(path, data={"t": token})  # twice: still one year

    # a month more, from the end of the year
    m = client.post("/api/clients/1/plan/checkout", headers=portal, json={"plan": "social_monthly"}).json()
    p2, t2 = _parts(m["url"])
    client.post(p2, data={"t": t2})
    p = client.get("/api/clients/1/plan", headers=portal).json()
    year_end = plans.add_months(start, 12) - timedelta(days=1)
    assert p["status"]["valid_until"] == (plans.add_months(year_end + timedelta(days=1), 1) - timedelta(days=1)).isoformat()
    assert [x["plan"] for x in p["payments"]] == ["social_monthly", "pro_12"] and all(x["status"] == "paid" for x in p["payments"])


def test_who_can_buy_and_payments_off(client, portal, monkeypatch):
    seo = login(client, "kabir@greenmedia.in")
    assert client.post("/api/clients/1/plan/checkout", headers=seo, json={"plan": "pro_12"}).status_code == 403
    monkeypatch.setattr(settings, "payments_demo", False)
    r = client.post("/api/clients/1/plan/checkout", headers=portal, json={"plan": "pro_12"})
    assert r.status_code == 422 and "isn't set up" in r.json()["detail"]


class FakeRazorpay:
    def __init__(self):
        self.links: dict[str, dict] = {}

    def __call__(self, req: httpx.Request) -> httpx.Response:
        assert req.headers["Authorization"].startswith("Basic ")
        if req.method == "POST" and req.url.path == "/v1/payment_links":
            body = json.loads(req.content)
            lid = f"plink_{len(self.links) + 1}"
            self.links[lid] = {"id": lid, "short_url": f"https://rzp.io/i/{lid}", "status": "created", "payments": None, **body}
            return httpx.Response(200, json=self.links[lid])
        lid = req.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=self.links[lid])


@pytest.fixture()
def razorpay(monkeypatch):
    fake = FakeRazorpay()
    monkeypatch.setattr(settings, "razorpay_key_id", "rzp_test_key")
    monkeypatch.setattr(settings, "razorpay_key_secret", "rzp-secret")
    monkeypatch.setattr(settings, "razorpay_webhook_secret", "hook-secret")
    monkeypatch.setattr(plans, "http", httpx.Client(transport=httpx.MockTransport(fake)))
    return fake


def _sign(secret: str, msg: bytes) -> str:
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def test_razorpay_link_callback_and_forgery(client, portal, razorpay):
    out = client.post("/api/clients/1/plan/checkout", headers=portal, json={"plan": "pro_24"}).json()
    assert out["url"] == "https://rzp.io/i/plink_1" and not out["demo"]
    link = razorpay.links["plink_1"]
    assert link["amount"] == 2700000 and link["currency"] == "INR" and link["callback_url"] == "https://api.test/api/plan/razorpay/callback"
    assert link["reference_id"] == f"gm-plan-{out['id']}" and link["customer"]["email"]

    forged = {"razorpay_payment_id": "pay_X", "razorpay_payment_link_id": "plink_1", "razorpay_payment_link_reference_id": link["reference_id"],
              "razorpay_payment_link_status": "paid", "razorpay_signature": "0" * 64}
    assert "confirm the payment yet" in client.get("/api/plan/razorpay/callback", params=forged).text
    assert client.get("/api/clients/1/plan", headers=portal).json()["status"]["state"] == "not_activated"

    signed = {**forged, "razorpay_signature": _sign("rzp-secret", f"plink_1|{link['reference_id']}|paid|pay_X".encode())}
    assert "Payment successful" in client.get("/api/plan/razorpay/callback", params=signed).text
    p = client.get("/api/clients/1/plan", headers=portal).json()
    assert p["status"]["state"] == "active" and p["payments"][0]["status"] == "paid" and p["payments_mode"] == "live"
    assert p["payments_test"] is True  # rzp_test_ key: the app says no real money moves


def test_razorpay_webhook_and_status_refresh(client, portal, razorpay):
    a = client.post("/api/clients/1/plan/checkout", headers=portal, json={"plan": "social_monthly"}).json()
    body = json.dumps({"event": "payment_link.paid", "payload": {"payment_link": {"entity": {"id": "plink_1"}},
                                                                 "payment": {"entity": {"id": "pay_W"}}}}).encode()
    assert client.post("/api/plan/razorpay/webhook", content=body, headers={"X-Razorpay-Signature": "bad"}).status_code == 400
    assert client.post("/api/plan/razorpay/webhook", content=body, headers={"X-Razorpay-Signature": _sign("hook-secret", body)}).json() == {"ok": True}
    assert client.get(f"/api/clients/1/plan/payments/{a['id']}", headers=portal).json()["status"] == "paid"

    # the owner is back before any webhook: the app asks, we ask Razorpay
    b = client.post("/api/clients/1/plan/checkout", headers=portal, json={"plan": "pro_12"}).json()
    razorpay.links["plink_2"].update(status="paid", payments=[{"payment_id": "pay_Z", "status": "captured"}])
    st = client.get(f"/api/clients/1/plan/payments/{b['id']}", headers=portal).json()
    assert st["status"] == "paid" and st["plan_status"]["plan"]["name"] == "Pro"


def test_razorpay_key_names_and_test_or_live(monkeypatch):
    from app.config import first_set
    # RAZORPAY_KEY / RAZORPAY_SECRET work as well as RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET
    assert first_set({"RAZORPAY_KEY": " rzp_test_abc "}, "RAZORPAY_KEY_ID", "RAZORPAY_KEY") == "rzp_test_abc"
    assert first_set({"RAZORPAY_KEY_ID": "", "RAZORPAY_KEY": "k2"}, "RAZORPAY_KEY_ID", "RAZORPAY_KEY") == "k2"
    assert first_set({}, "RAZORPAY_KEY_ID", "RAZORPAY_KEY") == ""
    monkeypatch.setattr(settings, "razorpay_key_secret", "s")
    monkeypatch.setattr(settings, "razorpay_key_id", "rzp_test_abc")
    assert plans.test_mode() and plans.describe() == "Payments: Razorpay TEST mode (test key — no real money)"
    monkeypatch.setattr(settings, "razorpay_key_id", "rzp_live_abc")
    assert not plans.test_mode() and plans.describe() == "Payments: Razorpay LIVE (real money)"
