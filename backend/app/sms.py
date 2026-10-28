"""Send the sign-in code by SMS. Provider chosen by SMS_PROVIDER (see config)."""

import base64
import logging

import httpx

from .config import settings

log = logging.getLogger("greenmedia.sms")

# Swappable in tests (httpx.MockTransport).
http = httpx.Client(timeout=15)


class SmsError(Exception):
    pass


def send_otp(phone: str, code: str) -> None:
    """phone in E.164. Raises SmsError when the provider refuses."""
    provider = settings.sms_provider
    try:
        if provider == "msg91":
            # https://docs.msg91.com — OTP API with a DLT-approved template containing ##OTP##
            r = http.post("https://control.msg91.com/api/v5/otp", headers={"authkey": settings.msg91_auth_key},
                          params={"template_id": settings.msg91_template_id, "mobile": phone.lstrip("+"), "otp": code})
            body = r.json() if r.content else {}
            if r.status_code >= 400 or body.get("type") == "error":
                raise SmsError(f"MSG91: {body.get('message') or r.text[:200]}")
        elif provider == "twilio":
            auth = base64.b64encode(f"{settings.twilio_account_sid}:{settings.twilio_auth_token}".encode()).decode()
            r = http.post(f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json",
                          headers={"Authorization": f"Basic {auth}"},
                          data={"To": phone, "From": settings.twilio_from, "Body": f"{code} is your Green Media sign-in code. It expires in {settings.otp_ttl_seconds // 60} minutes."})
            if r.status_code >= 400:
                raise SmsError(f"Twilio: {r.json().get('message', r.text[:200]) if r.content else r.status_code}")
        else:  # console: development / demo only
            log.warning("OTP for %s: %s (SMS_PROVIDER=console — set msg91 or twilio to send real SMS)", phone, code)
    except httpx.HTTPError as e:
        raise SmsError(f"SMS provider unreachable: {e.__class__.__name__}") from e
