import hashlib
import hmac
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import phone as phones
from .. import mailer, review_queue, sms
from ..config import settings
from ..db import get_db
from ..models import Client, ClientContact, OtpChallenge, Tenant, User
from ..security import ROLE_LABELS, audit, create_token, current_user, load_role, verify_password
from ..serializers import me_out, user_out

log = logging.getLogger("greenmedia.auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str
    password: str


def _me(db: Session, user: User) -> dict:
    client = db.get(Client, user.client_id) if user.client_id else None
    return me_out(user, client.company_name if client else None)


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.strip().lower()))
    if not user or user.status != "active" or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Incorrect email or password")
    load_role(db, user)
    if not user.sections:
        raise HTTPException(403, f"Your role “{user.role}” has no access. Ask an admin to fix it.")
    audit(db, user, "signed in", entity_type="user", entity_id=user.id)
    db.commit()
    return {"access_token": create_token(user), "token_type": "bearer", "user": _me(db, user)}


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _me(db, user)


@router.get("/users")
def users(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Staff directory for task assignment."""
    rows = db.scalars(select(User).where(User.tenant_id == user.tenant_id, User.role != "client").order_by(User.name))
    return [user_out(u) for u in rows]


# ---------- OTP sign-in by SMS or email (mobile app) ----------

def _aware(dt):
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def _hash(phone: str, code: str) -> str:
    return hmac.new(settings.jwt_secret.encode(), f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


def _phone(raw: str, cc: str) -> str:
    try:
        return phones.normalize(raw, cc)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


class OtpRequestIn(BaseModel):
    phone: str = ""
    country_code: str = "+91"
    email: str = ""  # the app's "Email" option: send the code by email instead of SMS


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _target(phone: str, country_code: str, email: str) -> tuple[str, str]:
    """("sms", +91…) or ("email", address) from what the app sent."""
    email = (email or "").strip().lower()
    if email:
        if len(email) > 200 or not EMAIL_RE.match(email):
            raise HTTPException(422, "Enter a valid email address")
        return "email", email
    if not (phone or "").strip():
        raise HTTPException(422, "Enter your mobile number or email")
    return "sms", _phone(phone, country_code)


def _challenges(channel: str, to: str):
    return OtpChallenge.email == to if channel == "email" else OtpChallenge.phone == to


def _users(channel: str, to: str):
    return select(User).where(func.lower(User.email) == to if channel == "email" else User.phone == to, User.status == "active")


def _masked(channel: str, to: str) -> str:
    return mailer.masked(to) if channel == "email" else phones.masked(to)


@router.post("/otp/request")
def otp_request(body: OtpRequestIn, db: Session = Depends(get_db)):
    """Send a sign-in code by SMS (phone) or email. The answer is the same whether or not an account uses the number
    or address (no probing); a code is only sent when at least one active account does."""
    channel, to = _target(body.phone, body.country_code, body.email)
    what = "email address" if channel == "email" else "number"
    now = datetime.now(timezone.utc)
    recent = list(db.scalars(select(OtpChallenge).where(_challenges(channel, to), OtpChallenge.created_at >= now - timedelta(hours=1))
                             .order_by(OtpChallenge.id.desc())))
    if recent:
        wait = settings.otp_resend_seconds - int((now - _aware(recent[0].created_at)).total_seconds())
        if wait > 0:
            raise HTTPException(429, f"Please wait {wait}s before asking for a new code")
    if len(recent) >= settings.otp_max_per_hour:
        raise HTTPException(429, f"Too many codes requested for this {what} — try again in an hour")
    out = {"sent": True, "channel": channel, "phone": to if channel == "sms" else "", "email": to if channel == "email" else "",
           "masked": _masked(channel, to), "length": settings.otp_length, "expires_in": settings.otp_ttl_seconds,
           "resend_in": settings.otp_resend_seconds}
    has_account = db.scalar(_users(channel, to).with_only_columns(User.id).limit(1))
    code = "".join(secrets.choice("0123456789") for _ in range(settings.otp_length))
    db.add(OtpChallenge(phone=to if channel == "sms" else "", email=to if channel == "email" else "",
                        code_hash=_hash(_key(channel, to), code) if has_account else "-", expires_at=now + timedelta(seconds=settings.otp_ttl_seconds)))
    db.commit()
    if not has_account:  # the app gets the same answer (no probing), but whoever runs the server can see why
        log.warning("No code sent to %s: no active user has this %s. Add it to a user (web app → Users).%s", _masked(channel, to),
                    "email" if channel == "email" else "mobile number", _contact_hint(db, channel, to))
        return out
    try:
        if channel == "email":
            mailer.send_otp(to, code)
        else:
            sms.send_otp(to, code)
    except (sms.SmsError, mailer.MailError) as e:
        log.warning("%s to %s failed: %s", "Email" if channel == "email" else "SMS", _masked(channel, to), e)
        raise HTTPException(502, f"Couldn't send the {'email' if channel == 'email' else 'SMS'}: {e}") from e
    console = not mailer.enabled() if channel == "email" else settings.sms_provider == "console"
    if console and settings.seed_demo:
        out["dev_code"] = code  # demo installs only (nothing really sent): lets testers sign in
    return out


def _contact_hint(db: Session, channel: str, to: str) -> str:
    """When the address or number is a business's contact (not a login), say whose — the usual mix-up."""
    col = func.lower(ClientContact.email) if channel == "email" else ClientContact.phone
    contact = db.scalar(select(ClientContact).where(col == to).limit(1))
    if contact is None:
        return ""
    client = db.get(Client, contact.client_id)
    return (f" It is the contact {'email' if channel == 'email' else 'number'} of {contact.name} at "
            f"{client.company_name if client else 'a client'}, not a login: sign in with the business user's email, or give that user this one.")


def _key(channel: str, to: str) -> str:
    """What the code's hash is bound to (a phone number keeps its old form)."""
    return f"email:{to}" if channel == "email" else to


class OtpVerifyIn(BaseModel):
    phone: str = ""
    country_code: str = "+91"
    email: str = ""
    code: str


def _profiles(db: Session, phone: str, channel: str = "sms") -> list[dict]:
    out = []
    tenants = {}
    for u in db.scalars(_users(channel, phone).order_by(User.id)):
        load_role(db, u)
        if not u.sections:
            continue
        t = tenants.get(u.tenant_id) or db.get(Tenant, u.tenant_id)
        tenants[u.tenant_id] = t
        c = db.get(Client, u.client_id) if u.client_id else None
        google = None
        if c:
            g = c.gmb
            state = review_queue.source_state(c, 0) if g else "none"
            email = (g.connection.email if g and g.connection else (g.google_email if g else "")) or ""
            google = {"state": "connected" if state in ("live", "error") else ("approval_pending" if state == "approval_pending" else "needs_google"),
                      "email": email, "title": g.title if g else ""}
        out.append({
            "user_id": u.id, "name": u.name, "role": u.role, "role_label": getattr(u, "role_label", ROLE_LABELS.get(u.role, u.role)),
            "kind": "business" if c else "agency", "tenant_name": t.name if t else "",
            "title": c.company_name if c else (t.name if t else u.name),
            "subtitle": " · ".join(x for x in ((c.industry, c.city) if c else (u.role_label if hasattr(u, "role_label") else u.role,)) if x),
            "client_id": c.id if c else None, "google": google,
            "group": (google["email"] if google and google["email"] else ("Not connected to Google" if c else "Agency team")),
        })
    return out


@router.post("/otp/verify")
def otp_verify(body: OtpVerifyIn, db: Session = Depends(get_db)):
    """Check the code. Returns a short-lived token and every profile (account) linked to the number or email."""
    channel, to = _target(body.phone, body.country_code, body.email)
    ch = db.scalar(select(OtpChallenge).where(_challenges(channel, to), OtpChallenge.verified_at.is_(None)).order_by(OtpChallenge.id.desc()).limit(1))
    now = datetime.now(timezone.utc)
    if ch is None or _aware(ch.expires_at) < now:
        raise HTTPException(400, "This code has expired — request a new one")
    if ch.attempts >= settings.otp_max_attempts:
        raise HTTPException(429, "Too many wrong codes — request a new one")
    ch.attempts += 1
    if not hmac.compare_digest(ch.code_hash, _hash(_key(channel, to), body.code.strip())):
        db.commit()
        left = settings.otp_max_attempts - ch.attempts
        raise HTTPException(400, f"Incorrect code — {left} attempt{'s' if left != 1 else ''} left" if left else "Too many wrong codes — request a new one")
    ch.verified_at = now
    db.commit()
    claim = {"email": to} if channel == "email" else {"phone": to}
    token = jwt.encode({"purpose": "otp", **claim, "exp": now + timedelta(minutes=10)}, settings.jwt_secret, algorithm="HS256")
    return {"otp_token": token, "channel": channel, "phone": to if channel == "sms" else "", "email": to if channel == "email" else "",
            "profiles": _profiles(db, to, channel)}


class OtpSelectIn(BaseModel):
    otp_token: str
    user_id: int


@router.post("/otp/select")
def otp_select(body: OtpSelectIn, db: Session = Depends(get_db)):
    """Open one of the verified number's profiles: returns the normal access token."""
    try:
        st = jwt.decode(body.otp_token, settings.jwt_secret, algorithms=["HS256"])
        assert st.get("purpose") == "otp"
    except (jwt.PyJWTError, AssertionError) as e:
        raise HTTPException(401, "Verification expired — sign in again") from e
    user = db.get(User, body.user_id)
    by_email = "email" in st
    linked = (user.email or "").lower() == st["email"] if by_email and user else bool(user and st.get("phone") and user.phone == st["phone"])
    if not user or not linked or user.status != "active":
        raise HTTPException(403, f"That profile isn't linked to this {'email' if by_email else 'number'}")
    load_role(db, user)
    if not user.sections:
        raise HTTPException(403, f"Your role “{user.role}” has no access. Ask an admin to fix it.")
    if by_email:
        audit(db, user, "signed in (email OTP)", entity_type="user", entity_id=user.id, details={"email": mailer.masked(st["email"])})
    else:
        audit(db, user, "signed in (phone OTP)", entity_type="user", entity_id=user.id, details={"phone": phones.masked(user.phone)})
    db.commit()
    return {"access_token": create_token(user), "token_type": "bearer", "user": _me(db, user)}


# ---------- the app's Settings: Change Profile, privacy choice, Delete Account ----------

@router.get("/profiles")
def my_profiles(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Every profile linked to the signed-in person's mobile number (Change Profile), without a new code."""
    if not user.phone:
        return {"profiles": [], "current": user.id}
    return {"profiles": _profiles(db, user.phone), "current": user.id}


class SwitchIn(BaseModel):
    user_id: int


@router.post("/switch")
def switch_profile(body: SwitchIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Open another profile on the same verified number (the person proved the number when signing in)."""
    other = db.get(User, body.user_id)
    if not user.phone or not other or other.phone != user.phone or other.status != "active":
        raise HTTPException(403, "That profile isn't linked to your number")
    load_role(db, other)
    if not other.sections:
        raise HTTPException(403, f"Your role “{other.role}” has no access. Ask an admin to fix it.")
    audit(db, other, "switched profile in the app", entity_type="user", entity_id=other.id, details={"from_user": user.id})
    db.commit()
    return {"access_token": create_token(other), "token_type": "bearer", "user": _me(db, other)}


class PrefsIn(BaseModel):
    analytics: bool | None = None


@router.put("/prefs")
def save_prefs(body: PrefsIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.prefs = {**(user.prefs or {}), **body.model_dump(exclude_none=True)}
    db.commit()
    return {"prefs": user.prefs}


class DeleteAccountIn(BaseModel):
    confirm: str


@router.post("/delete-account")
def delete_account(body: DeleteAccountIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The person closes their own login at once (it stops working everywhere). For a business owner, deleting the
    business's data is a task for the account manager — done within 30 days, as the Privacy Policy says."""
    if body.confirm.strip().upper() != "DELETE":
        raise HTTPException(422, 'Type DELETE to confirm')
    from ..models import Task

    c = db.get(Client, user.client_id) if user.client_id else None
    audit(db, user, "deleted their own account in the app", entity_type="user", entity_id=user.id, client_id=c.id if c else None)
    if c:
        db.add(Task(tenant_id=user.tenant_id, client_id=c.id, assigned_to=c.account_manager_id, priority="high",
                    title=f"Account deleted in the app by {user.name} — delete {c.company_name}'s data within 30 days (or confirm they keep it)",
                    due_date=(datetime.now(timezone.utc) + timedelta(days=30)).date()))
    user.status, user.phone, user.prefs = "deleted", "", {}
    user.email = f"deleted-{user.id}@deleted.invalid"
    db.commit()
    return {"deleted": True}
