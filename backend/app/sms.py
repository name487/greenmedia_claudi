"""Send the sign-in code by SMS. Provider chosen by SMS_PROVIDER (see config)."""

import base64
import logging

import httpx

from .config import settings

log = logging.getLogger("greenmedia.sms")

# Swappable in tests (httpx.MockTransport).
http = httpx.Client(timeout=15)


def describe() -> str:
    """One line for the startup log: which SMS sender is active."""
    if settings.sms_provider == "msg91":
        return "SMS: MSG91"
    if settings.sms_provider == "twilio":
        return f"SMS: Twilio from {settings.twilio_from or '(no TWILIO_FROM)'}"
    return "SMS: none — sign-in codes are only written to this log (set SMS_PROVIDER=msg91 or twilio to send real SMS)"


class SmsError(Exception):
    pass


def send_otp(phone: str, code: str) -> str:
    """phone in E.164. Returns the provider's reply; raises SmsError when it refuses."""
    provider = settings.sms_provider
    try:
        if provider == "msg91":
            # https://docs.msg91.com — OTP API with a DLT-approved template containing ##OTP##
            r = http.post("https://control.msg91.com/api/v5/otp", headers={"authkey": settings.msg91_auth_key},
                          params={"template_id": settings.msg91_template_id, "mobile": phone.lstrip("+"), "otp": code})
            body = r.json() if r.content else {}
            if r.status_code >= 400 or body.get("type") == "error":
                raise SmsError(f"MSG91: {body.get('message') or r.text[:200]}")
            return r.text[:500]
        if provider == "twilio":
            auth = base64.b64encode(f"{settings.twilio_account_sid}:{settings.twilio_auth_token}".encode()).decode()
            r = http.post(f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json",
                          headers={"Authorization": f"Basic {auth}"},
                          data={"To": phone, "From": settings.twilio_from, "Body": f"{code} is your Green Media sign-in code. It expires in {settings.otp_ttl_seconds // 60} minutes."})
            if r.status_code >= 400:
                raise SmsError(f"Twilio: {r.json().get('message', r.text[:200]) if r.content else r.status_code}")
            return r.text[:500]
        # console: development / demo only
        log.warning("OTP for %s: %s (SMS_PROVIDER=console — set msg91 or twilio to send real SMS)", phone, code)
        return "console: written to the server log only"
    except httpx.HTTPError as e:
        raise SmsError(f"SMS provider unreachable: {e.__class__.__name__}") from e
