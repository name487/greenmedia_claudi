"""Send the sign-in code by SMS. Provider chosen by SMS_PROVIDER (see config)."""

import logging

import httpx

from .config import settings

log = logging.getLogger("greenmedia.sms")

# Swappable in tests (httpx.MockTransport).
http = httpx.Client(timeout=15)


# Where the code goes in SMS_TEXT: the template exactly as DLT shows it ({#var#}), or {otp}.
CODE_PLACEHOLDERS = ("{#var#}", "{otp}")


def describe() -> str:
    """One line for the startup log: which SMS sender is active."""
    if settings.sms_provider == "nimbusit":
        return f"SMS: NimbusIT via {settings.sms_host} as {settings.sms_sender or '(no SMS_SENDER)'}"
    if settings.sms_provider == "msg91":
        return "SMS: MSG91"
    return "SMS: none — sign-in codes are only written to this log (set SMS_AUTHKEY for NimbusIT)"


class SmsError(Exception):
    pass


def send_otp(phone: str, code: str) -> str:
    """phone in E.164. Returns the provider's reply; raises SmsError when it refuses."""
    provider = settings.sms_provider
    try:
        if provider == "nimbusit":
            return _nimbusit(phone, code)
        elif provider == "msg91":
            # https://docs.msg91.com — OTP API with a DLT-approved template containing ##OTP##
            r = http.post("https://control.msg91.com/api/v5/otp", headers={"authkey": settings.msg91_auth_key},
                          params={"template_id": settings.msg91_template_id, "mobile": phone.lstrip("+"), "otp": code})
            body = r.json() if r.content else {}
            if r.status_code >= 400 or body.get("type") == "error":
                raise SmsError(f"MSG91: {body.get('message') or r.text[:200]}")
            return r.text[:500]
        else:  # console: development / demo only
            log.warning("OTP for %s: %s (SMS_PROVIDER=console — set SMS_AUTHKEY (NimbusIT) to send real SMS)", phone, code)
            return "console: written to the server log only"
    except httpx.HTTPError as e:
        raise SmsError(f"SMS provider unreachable: {e.__class__.__name__}") from e


def _nimbusit(phone: str, code: str) -> str:
    """NimbusIT push SMS (India, DLT): GET {host}/api/pushsms?usr=&authkey=&sender=&mobile=&text=&rpt= as in NimbusIT's
    API sample, plus the DLT entityid/templateid when set. The text must match the approved template word for word, so
    it comes from SMS_TEXT with {otp} (and optionally {minutes}) filled in."""
    missing = [n for n, v in (("SMS_USER", settings.sms_user), ("SMS_AUTHKEY", settings.sms_authkey), ("SMS_SENDER", settings.sms_sender))
               if not v.strip()]
    if not any(p in settings.sms_text for p in CODE_PLACEHOLDERS):
        missing.append("SMS_TEXT (the DLT template with {#var#} or {otp} where the code goes)")
    if missing:  # DLT drops texts that don't match the template, so don't send a guess
        raise SmsError("NimbusIT isn't set up on the server: missing " + ", ".join(missing))
    text = settings.sms_text.replace("{minutes}", str(settings.otp_ttl_seconds // 60))
    for p in CODE_PLACEHOLDERS:
        text = text.replace(p, code)
    mobile = phone[3:] if phone.startswith("+91") else phone.lstrip("+")  # Indian numbers: the 10 digits
    # NimbusIT's sample calls the user "usr"; its other docs say "user" — both are sent, the gateway ignores the other one.
    params = {"usr": settings.sms_user, "user": settings.sms_user, "authkey": settings.sms_authkey, "sender": settings.sms_sender,
              "mobile": mobile, "text": text, "rpt": settings.sms_rpt}
    params |= {k: v for k, v in (("entityid", settings.sms_entityid), ("templateid", settings.sms_templateid)) if v.strip()}
    host = settings.sms_host.strip().rstrip("/")
    if host.startswith(("http://", "https://")):
        r = http.get(f"{host}/api/pushsms", params=params)
    else:  # https keeps the auth key private; NimbusIT's sample uses plain http, so fall back to it
        try:
            r = http.get(f"https://{host}/api/pushsms", params=params)
        except httpx.ConnectError:
            r = http.get(f"http://{host}/api/pushsms", params=params)
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
    elif r.status_code >= 400 or any(w in r.text.lower() for w in ("error", "invalid", "fail", "wrong")):
        raise SmsError(f"NimbusIT: {r.text[:200] or r.status_code}")
    else:
        log.info("NimbusIT accepted the sign-in SMS for %s: %s", phone, r.text[:200])
    return r.text[:500]
