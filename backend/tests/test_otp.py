"""Phone OTP sign-in for the mobile app: request → verify → choose profile."""

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

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
    assert out["phone"] == OWNER and out["length"] == 6 and out["resend_in"] == 0 and out["masked"] == "+919876••••10"
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


def test_msg91_and_twilio(client, monkeypatch):
    calls = _provider(monkeypatch, "msg91", msg91_auth_key="mk", msg91_template_id="tpl")
    out = _code(client)
    assert "dev_code" not in out  # real SMS: the code is never in the response
    req = calls[0]
    assert req.url.host == "control.msg91.com" and req.headers["authkey"] == "mk"
    assert req.url.params["mobile"] == "919876543210" and req.url.params["template_id"] == "tpl" and len(req.url.params["otp"]) == 6
    calls = _provider(monkeypatch, "twilio", twilio_account_sid="AC1", twilio_auth_token="tok", twilio_from="+15550001111")
    _code(client)
    form = parse_qs(calls[0].content.decode())
    assert calls[0].url.path == "/2010-04-01/Accounts/AC1/Messages.json" and form["To"] == [OWNER] and "sign-in code" in form["Body"][0]


def test_provider_failure_is_reported(client, monkeypatch):
    monkeypatch.setattr(sms, "http", httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"type": "error", "message": "Invalid authkey"}))))
    monkeypatch.setattr(settings, "sms_provider", "msg91")
    r = client.post("/api/auth/otp/request", json={"phone": "9876543210"})
    assert r.status_code == 502 and "Invalid authkey" in r.json()["detail"]


def test_sms_provider_choice():
    from app.config import sms_provider_from
    assert sms_provider_from({}) == "console"
    assert sms_provider_from({"SMS_PROVIDER": ""}) == "console"  # the .env.example line left empty
    assert sms_provider_from({"SMS_PROVIDER": " Twilio "}) == "twilio"


def test_unknown_number_is_explained_in_the_server_log(client, monkeypatch, caplog):
    calls = _provider(monkeypatch, "twilio", twilio_account_sid="AC1", twilio_auth_token="tok", twilio_from="+15550001111")
    with caplog.at_level("WARNING", logger="greenmedia.auth"):
        assert _code(client, "9123456789")["sent"] is True  # same answer for the app
    assert not calls and "No code sent to +919123••••89: no active user has this mobile number" in caplog.text


def test_send_test_sms_command_shows_the_provider_reply(monkeypatch):
    from app.manage import send_test_sms
    calls = _provider(monkeypatch, "twilio", twilio_account_sid="AC1", twilio_auth_token="tok", twilio_from="+15550001111")
    out = send_test_sms("98330 12303")  # no account needed
    assert "SMS: Twilio from +15550001111" in out and "To +919833012303" in out and "Provider replied:" in out
    assert parse_qs(calls[0].content.decode())["To"] == ["+919833012303"]
    monkeypatch.setattr(sms, "http", httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"message": "Authenticate"}))))
    assert "FAILED: Twilio: Authenticate" in send_test_sms("9833012303")


OWNER_EMAIL = "anjali@smiledental.in"  # demo: Dr. Anjali Rao (Smile Dental Studio)


class FakeSmtp:
    def __init__(self, fail=None):
        self.sent, self.logins, self.fail = [], [], fail

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, password):
        self.logins.append(user)

    def send_message(self, msg):
        if self.fail:
            raise self.fail
        self.sent.append(msg)


def test_email_code_signs_in(client, monkeypatch):
    from app import mailer
    out = client.post("/api/auth/otp/request", json={"email": " Anjali@SmileDental.in "}).json()
    assert out["channel"] == "email" and out["email"] == OWNER_EMAIL and out["masked"] == "an••••@smiledental.in" and out["phone"] == ""
    code = out["dev_code"]  # demo install without SMTP_HOST
    assert client.post("/api/auth/otp/verify", json={"email": OWNER_EMAIL, "code": "000000" if code != "000000" else "111111"}).status_code == 400
    v = client.post("/api/auth/otp/verify", json={"email": OWNER_EMAIL, "code": code}).json()
    assert v["channel"] == "email" and [p["title"] for p in v["profiles"]] == ["Smile Dental Studio"]
    signed = client.post("/api/auth/otp/select", json={"otp_token": v["otp_token"], "user_id": v["profiles"][0]["user_id"]}).json()
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {signed['access_token']}"}).json()
    assert me["email"] == OWNER_EMAIL and me["client_name"] == "Smile Dental Studio"
    # an email token can't open someone else's profile, and a phone code can't be verified as an email
    other = client.post("/api/auth/otp/select", json={"otp_token": v["otp_token"], "user_id": 1})
    assert other.status_code == 403 and "email" in other.json()["detail"]
    # through a real mail server (faked): the code is in the subject and body, never in the API answer
    fake = FakeSmtp()
    monkeypatch.setattr(mailer, "smtp_factory", fake)
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_user", "noreply@example.com")
    monkeypatch.setattr(settings, "smtp_from", "Green Media <noreply@example.com>")
    out = client.post("/api/auth/otp/request", json={"email": OWNER_EMAIL}).json()
    assert "dev_code" not in out and fake.logins == ["noreply@example.com"]
    msg = fake.sent[0]
    code = msg["Subject"].split()[0]
    assert msg["To"] == OWNER_EMAIL and len(code) == settings.otp_length and code in msg.get_content()
    assert client.post("/api/auth/otp/verify", json={"email": OWNER_EMAIL, "code": code}).status_code == 200


def test_email_unknown_failure_and_validation(client, monkeypatch, caplog):
    import smtplib

    from app import mailer
    with caplog.at_level("WARNING", logger="greenmedia.auth"):
        out = client.post("/api/auth/otp/request", json={"email": "nobody@example.com"}).json()
    assert out["sent"] and "dev_code" not in out  # same answer, nothing sent
    assert "No code sent to no••••@example.com: no active user has this email" in caplog.text
    assert client.post("/api/auth/otp/request", json={"email": "not-an-email"}).status_code == 422
    assert client.post("/api/auth/otp/request", json={}).status_code == 422
    monkeypatch.setattr(mailer, "smtp_factory", FakeSmtp(fail=smtplib.SMTPAuthenticationError(535, b"Bad credentials")))
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_from", "noreply@example.com")
    r = client.post("/api/auth/otp/request", json={"email": OWNER_EMAIL})
    assert r.status_code == 502 and r.json()["detail"].startswith("Couldn't send the email: SMTPAuthenticationError")


def test_contact_email_is_explained_and_zeptomail_style_settings(client, monkeypatch, caplog):
    from app import mailer
    # a business contact's email isn't a login: the log says whose it is
    with caplog.at_level("WARNING", logger="greenmedia.auth"):
        assert client.post("/api/auth/otp/request", json={"email": "owner@smiledentalstudio.in"}).json()["sent"]
    assert "It is the contact email of Dev Gupta at Smile Dental Studio, not a login" in caplog.text

    # ZeptoMail-style: SMTP user "emailapikey", MAIL_ENCRYPTION=ssl, and a From that must carry an address
    fake = FakeSmtp()
    monkeypatch.setattr(mailer, "smtp_factory", fake)
    for k, v in {"smtp_host": "smtp.zeptomail.in", "smtp_port": 465, "smtp_user": "emailapikey", "smtp_encryption": "ssl",
                 "smtp_from": "Green Media GMB"}.items():
        monkeypatch.setattr(settings, k, v)
    assert mailer.encryption() == "ssl" and "no sender address" in mailer.describe()
    r = client.post("/api/auth/otp/request", json={"email": OWNER_EMAIL})
    assert r.status_code == 502 and "SMTP_FROM needs an email address on your sending domain" in r.json()["detail"] and not fake.sent
    monkeypatch.setattr(settings, "smtp_from", "Green Media GMB <noreply@greenmedia.example>")
    assert client.post("/api/auth/otp/request", json={"email": OWNER_EMAIL}).status_code == 200
    assert fake.sent[0]["From"] == "Green Media GMB <noreply@greenmedia.example>" and fake.logins == ["emailapikey"]
    assert "smtp.zeptomail.in:465 (ssl) from Green Media GMB <noreply@greenmedia.example>" in mailer.describe()
    monkeypatch.setattr(settings, "smtp_encryption", "tls")
    assert mailer.encryption() == "starttls"
    monkeypatch.setattr(settings, "smtp_encryption", "")
    monkeypatch.setattr(settings, "smtp_port", 587)
    assert mailer.encryption() == "starttls"


def test_admin_puts_a_real_email_on_a_user_and_it_receives_the_code(client, monkeypatch, caplog):
    from app import mailer
    admin = login(client, "admin@greenmedia.in")
    anjali = next(u for u in client.get("/api/users", headers=admin).json() if u["email"] == OWNER_EMAIL)
    assert client.patch(f"/api/users/{anjali['id']}", headers=admin, json={"email": "admin@greenmedia.in"}).status_code == 409
    assert client.patch(f"/api/users/{anjali['id']}", headers=admin, json={"email": "nope"}).status_code == 422
    r = client.patch(f"/api/users/{anjali['id']}", headers=admin, json={"email": " Dr.Anjali.Rao@Gmail.com "})
    assert r.status_code == 200 and r.json()["email"] == "dr.anjali.rao@gmail.com"
    fake = FakeSmtp()
    monkeypatch.setattr(mailer, "smtp_factory", fake)
    monkeypatch.setattr(settings, "smtp_host", "smtp.zeptomail.in")
    monkeypatch.setattr(settings, "smtp_from", "Green Media GMB <noreply@greenmedia.example>")
    with caplog.at_level("INFO", logger="greenmedia.auth"):
        assert client.post("/api/auth/otp/request", json={"email": "dr.anjali.rao@gmail.com"}).status_code == 200
    assert fake.sent[0]["To"] == "dr.anjali.rao@gmail.com" and "Sign-in code sent by email to dr••••@gmail.com" in caplog.text
    # the old demo address is no longer a login
    assert client.post("/api/auth/otp/request", json={"email": OWNER_EMAIL}).status_code == 200 and len(fake.sent) == 1
