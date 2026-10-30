"""Phone OTP sign-in for the mobile app: request → verify → choose profile."""

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import sms
from app.config import settings
from app.db import SessionLocal
from app.models import OtpChallenge, User

from .conftest import login

OWNER = "+919876543210"  # demo: Dr. Anjali Rao → Smile Dental Studio and GlowUp Salon & Spa


@pytest.fixture(autouse=True)
def no_resend_wait(monkeypatch):
    monkeypatch.setattr(settings, "otp_resend_seconds", 0)


def _code(client, phone="9876543210", **kw):
    r = client.post("/api/auth/otp/request", json={"phone": phone, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _verify(client, code, phone="9876543210"):
    return client.post("/api/auth/otp/verify", json={"phone": phone, "code": code})


def test_owner_with_two_businesses_signs_in_and_picks_one(client):
    out = _code(client, "98765 43210")
    assert out["phone"] == OWNER and out["length"] == 4 and out["resend_in"] == 0 and out["masked"] == "+919876••••10"
    code = out["dev_code"]  # demo install with SMS_PROVIDER=console
    with SessionLocal() as db:
        assert code not in db.query(OtpChallenge).order_by(OtpChallenge.id.desc()).first().code_hash  # only a hash is stored
    v = _verify(client, code).json()
    profiles = {p["title"]: p for p in v["profiles"]}
    assert set(profiles) == {"Smile Dental Studio", "GlowUp Salon & Spa"}
    smile = profiles["Smile Dental Studio"]
    assert smile["kind"] == "business" and smile["google"]["state"] == "needs_google" and smile["group"] == "Not connected to Google"
    assert smile["subtitle"] == "Dental Clinic · Pune"
    signed = client.post("/api/auth/otp/select", json={"otp_token": v["otp_token"], "user_id": profiles["GlowUp Salon & Spa"]["user_id"]}).json()
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {signed['access_token']}"}).json()
    assert me["client_name"] == "GlowUp Salon & Spa" and me["role"] == "client"
    # the code was single use
    assert _verify(client, code).status_code == 400


def test_phone_formats_and_validation(client):
    for raw in ("+91 98765-43210", "919876543210", "09876543210", "(98765) 43210"):
        assert _code(client, raw)["phone"] == OWNER
    for bad in ("12345", "5876543210", "98765432101", "abc"):
        assert client.post("/api/auth/otp/request", json={"phone": bad}).status_code == 422
    assert client.post("/api/auth/otp/request", json={"phone": "501234567", "country_code": "+971"}).json()["phone"] == "+971501234567"


def test_wrong_codes_expiry_and_limits(client, monkeypatch):
    out = _code(client)
    wrong = "0000" if out["dev_code"] != "0000" else "1111"
    r = _verify(client, wrong)
    assert r.status_code == 400 and "4 attempts left" in r.json()["detail"]
    for _ in range(4):
        _verify(client, wrong)
    assert _verify(client, out["dev_code"]).status_code == 429  # locked after 5 wrong tries, even with the right code
    # expired
    out = _code(client)
    with SessionLocal() as db:
        ch = db.query(OtpChallenge).order_by(OtpChallenge.id.desc()).first()
        ch.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    assert "expired" in _verify(client, out["dev_code"]).json()["detail"]
    # resend wait and hourly cap
    monkeypatch.setattr(settings, "otp_resend_seconds", 30)
    r = client.post("/api/auth/otp/request", json={"phone": "9876543210"})
    assert r.status_code == 429 and "wait" in r.json()["detail"]
    monkeypatch.setattr(settings, "otp_resend_seconds", 0)
    while client.post("/api/auth/otp/request", json={"phone": "9876543210"}).status_code == 200:
        pass
    assert "Too many codes" in client.post("/api/auth/otp/request", json={"phone": "9876543210"}).json()["detail"]


def test_unknown_number_gets_the_same_answer_but_no_sms(client, monkeypatch):
    sent = []
    monkeypatch.setattr(sms, "send_otp", lambda phone, code: sent.append(phone))
    out = _code(client, "9123456789")
    assert out["sent"] and "dev_code" not in out and sent == []
    assert _verify(client, "1234", "9123456789").status_code == 400
    _code(client)
    assert sent == [OWNER]


def test_select_is_bound_to_the_verified_number(client):
    v = _verify(client, _code(client)["dev_code"]).json()
    with SessionLocal() as db:
        admin_id = db.query(User).filter_by(email="admin@greenmedia.in").one().id
    assert client.post("/api/auth/otp/select", json={"otp_token": v["otp_token"], "user_id": admin_id}).status_code == 403
    assert client.post("/api/auth/otp/select", json={"otp_token": "forged", "user_id": admin_id}).status_code == 401
    # a disabled account disappears from the list
    admin = login(client, "admin@greenmedia.in")
    glow = next(p for p in v["profiles"] if p["title"] == "GlowUp Salon & Spa")
    client.patch(f"/api/users/{glow['user_id']}", headers=admin, json={"status": "disabled"})
    v = _verify(client, _code(client)["dev_code"]).json()
    assert [p["title"] for p in v["profiles"]] == ["Smile Dental Studio"]
    assert client.post("/api/auth/otp/select", json={"otp_token": v["otp_token"], "user_id": glow["user_id"]}).status_code == 403


def test_staff_profile_and_no_dev_code_outside_demo(client, monkeypatch):
    v = _verify(client, _code(client, "9000000001")["dev_code"], "9000000001").json()
    assert [(p["kind"], p["title"], p["group"]) for p in v["profiles"]] == [("agency", "Green Media Technology", "Agency team")]
    monkeypatch.setattr(settings, "seed_demo", False)
    assert "dev_code" not in _code(client, "9000000001")


def test_users_api_manages_phone(client):
    admin = login(client, "admin@greenmedia.in")
    u = client.post("/api/users", headers=admin, json={"name": "Ravi Shah", "email": "ravi@spiceroute.in", "password": "longenough1",
                                                       "role": "client", "client_id": 2, "phone": "98111 22233"}).json()
    assert u["phone"] == "+919811122233"
    assert client.post("/api/users", headers=admin, json={"name": "X Y", "email": "x@y.in", "password": "longenough1", "role": "seo", "phone": "123"}).status_code == 422
    assert client.patch(f"/api/users/{u['id']}", headers=admin, json={"phone": ""}).json()["phone"] == ""


def _provider(monkeypatch, name, **cfg):
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(200, json={"type": "success", "sid": "SM1"})

    monkeypatch.setattr(sms, "http", httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(settings, "sms_provider", name)
    for k, v in cfg.items():
        monkeypatch.setattr(settings, k, v)
    return calls


def test_msg91(client, monkeypatch):
    calls = _provider(monkeypatch, "msg91", msg91_auth_key="mk", msg91_template_id="tpl")
    out = _code(client)
    assert "dev_code" not in out  # real SMS: the code is never in the response
    req = calls[0]
    assert req.url.host == "control.msg91.com" and req.headers["authkey"] == "mk"
    assert req.url.params["mobile"] == "919876543210" and req.url.params["template_id"] == "tpl" and len(req.url.params["otp"]) == 4


def test_provider_failure_is_reported(client, monkeypatch):
    monkeypatch.setattr(sms, "http", httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"type": "error", "message": "Invalid authkey"}))))
    monkeypatch.setattr(settings, "sms_provider", "msg91")
    r = client.post("/api/auth/otp/request", json={"phone": "9876543210"})
    assert r.status_code == 502 and "Invalid authkey" in r.json()["detail"]


def test_nimbusit_sends_the_dlt_template(client, monkeypatch):
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(200, json={"STATUS": "OK", "RESPONSE": {"CODE": "100", "INFO": "msg-1"}})

    monkeypatch.setattr(sms, "http", httpx.Client(transport=httpx.MockTransport(handler)))
    for k, v in {"sms_provider": "nimbusit", "sms_host": "nimbusit.net", "sms_user": "u1", "sms_authkey": "ak", "sms_sender": "SNDRID",
                 "sms_entityid": "ent1", "sms_templateid": "tpl1", "sms_rpt": "1",
                 "sms_text": "Your OTP is {otp}. Valid for {minutes} minutes."}.items():
        monkeypatch.setattr(settings, k, v)
    out = _code(client)
    assert "dev_code" not in out
    q = calls[0].url.params
    assert calls[0].url.scheme == "https" and calls[0].url.host == "nimbusit.net" and calls[0].url.path == "/api/pushsms"
    assert (q["usr"], q["user"], q["authkey"], q["sender"], q["mobile"], q["entityid"], q["templateid"], q["rpt"]) == \
        ("u1", "u1", "ak", "SNDRID", "9876543210", "ent1", "tpl1", "1")
    otp = q["text"].removeprefix("Your OTP is ").split(".")[0]
    assert q["text"] == f"Your OTP is {otp}. Valid for 5 minutes." and len(otp) == 4 and otp.isdigit()
    # the code in the SMS signs in
    assert _verify(client, otp).status_code == 200

    # the gateway's refusal reaches the app
    monkeypatch.setattr(sms, "http", httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"STATUS": "ERROR", "RESPONSE": {"CODE": "105", "INFO": "Invalid Template"}}))))
    r = client.post("/api/auth/otp/request", json={"phone": "9876543210"})
    assert r.status_code == 502 and "Invalid Template" in r.json()["detail"]
    monkeypatch.setattr(sms, "http", httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="ERROR: Invalid authkey"))))
    r = client.post("/api/auth/otp/request", json={"phone": "9876543210"})
    assert r.status_code == 502 and "Invalid authkey" in r.json()["detail"]

    # without the template text nothing is sent, and the app is told what's missing
    calls.clear()
    monkeypatch.setattr(sms, "http", httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(settings, "sms_text", "")
    r = client.post("/api/auth/otp/request", json={"phone": "9876543210"})
    assert r.status_code == 502 and "missing SMS_TEXT" in r.json()["detail"] and not calls


def test_sms_provider_choice():
    from app.config import sms_provider_from
    assert sms_provider_from({}) == "console"
    assert sms_provider_from({"SMS_PROVIDER": "", "SMS_AUTHKEY": "ak"}) == "nimbusit"  # the .env.example line left empty
    assert sms_provider_from({"SMS_PROVIDER": " ", "SMS_AUTHKEY": ""}) == "console"
    assert sms_provider_from({"SMS_PROVIDER": "MSG91", "SMS_AUTHKEY": "ak"}) == "msg91"


def test_nimbusit_plain_text_answers_and_http_fallback(client, monkeypatch):
    calls = []

    def handler(req):
        calls.append(req)
        if req.url.scheme == "https":
            raise httpx.ConnectError("no https here", request=req)
        return httpx.Response(200, text="SMS-SHOOT-ID/demo1234ab")  # NimbusIT answers in plain text

    monkeypatch.setattr(sms, "http", httpx.Client(transport=httpx.MockTransport(handler)))
    for k, v in {"sms_provider": "nimbusit", "sms_host": "nimbusit.net", "sms_user": "u1", "sms_authkey": "ak", "sms_sender": "SNDRID",
                 "sms_entityid": "", "sms_templateid": "", "sms_rpt": "1", "sms_text": "OTP {otp}"}.items():
        monkeypatch.setattr(settings, k, v)
    assert "dev_code" not in _code(client)
    assert [c.url.scheme for c in calls] == ["https", "http"]  # like NimbusIT's sample when the gateway has no https
    assert "entityid" not in calls[1].url.params  # the DLT ids are optional
    monkeypatch.setattr(settings, "sms_host", "http://nimbusit.net")  # a scheme in SMS_HOST is used as is
    calls.clear()
    _code(client)
    assert [c.url.scheme for c in calls] == ["http"]
    monkeypatch.setattr(sms, "http", httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="Wrong Username or Password"))))
    r = client.post("/api/auth/otp/request", json={"phone": "9876543210"})
    assert r.status_code == 502 and "Wrong Username or Password" in r.json()["detail"]
