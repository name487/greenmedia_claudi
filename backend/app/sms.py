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
        if provider == "nimbusit":
            _nimbusit(phone, code)
        elif provider == "msg91":
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
            log.warning("OTP for %s: %s (SMS_PROVIDER=console — set nimbusit, msg91 or twilio to send real SMS)", phone, code)
    except httpx.HTTPError as e:
        raise SmsError(f"SMS provider unreachable: {e.__class__.__name__}") from e


def _nimbusit(phone: str, code: str) -> None:
    """NimbusIT push SMS (India, DLT). The text must match the approved template word for word, so it comes from
    SMS_TEXT with {otp} (and optionally {minutes}) filled in."""
    host = settings.sms_host.strip().removeprefix("https://").removeprefix("http://").strip("/")
    text = settings.sms_text.replace("{otp}", code).replace("{minutes}", str(settings.otp_ttl_seconds // 60))
    mobile = phone[3:] if phone.startswith("+91") else phone.lstrip("+")  # Indian numbers: the 10 digits
    r = http.get(f"https://{host}/api/pushsms", params={
        "user": settings.sms_user, "authkey": settings.sms_authkey, "sender": settings.sms_sender, "mobile": mobile, "text": text,
        "entityid": settings.sms_entityid, "templateid": settings.sms_templateid, "rpt": settings.sms_rpt})
    try:
        body = r.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        status = str(body.get("STATUS") or body.get("status") or "").upper()
        info = body.get("RESPONSE") or body.get("response") or {}
        if r.status_code >= 400 or status not in ("OK", "SUCCESS"):
            reason = (info.get("INFO") or info.get("info")) if isinstance(info, dict) else info
            raise SmsError(f"NimbusIT: {reason or r.text[:200]}")
        log.info("NimbusIT accepted the sign-in SMS for %s: %s", phone, info)
    elif r.status_code >= 400 or any(w in r.text.lower() for w in ("error", "invalid", "fail")):
        raise SmsError(f"NimbusIT: {r.text[:200] or r.status_code}")
