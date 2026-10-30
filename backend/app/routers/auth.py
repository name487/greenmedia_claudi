import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import phone as phones
from .. import review_queue, sms
from ..config import settings
from ..db import get_db
from ..models import Client, OtpChallenge, Tenant, User
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


# ---------- phone OTP sign-in (mobile app) ----------

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
    phone: str
    country_code: str = "+91"


@router.post("/otp/request")
def otp_request(body: OtpRequestIn, db: Session = Depends(get_db)):
    """Send a sign-in code. The answer is the same whether or not the number has an account (no number
    probing); an SMS is only sent when at least one active account uses it."""
    phone = _phone(body.phone, body.country_code)
    now = datetime.now(timezone.utc)
    recent = list(db.scalars(select(OtpChallenge).where(OtpChallenge.phone == phone, OtpChallenge.created_at >= now - timedelta(hours=1))
                             .order_by(OtpChallenge.id.desc())))
    if recent:
        wait = settings.otp_resend_seconds - int((now - _aware(recent[0].created_at)).total_seconds())
        if wait > 0:
            raise HTTPException(429, f"Please wait {wait}s before asking for a new code")
    if len(recent) >= settings.otp_max_per_hour:
        raise HTTPException(429, "Too many codes requested for this number — try again in an hour")
    out = {"sent": True, "phone": phone, "masked": phones.masked(phone), "length": settings.otp_length,
           "expires_in": settings.otp_ttl_seconds, "resend_in": settings.otp_resend_seconds}
    has_account = db.scalar(select(User.id).where(User.phone == phone, User.status == "active").limit(1))
    code = "".join(secrets.choice("0123456789") for _ in range(settings.otp_length))
    db.add(OtpChallenge(phone=phone, code_hash=_hash(phone, code) if has_account else "-", expires_at=now + timedelta(seconds=settings.otp_ttl_seconds)))
    db.commit()
    if not has_account:  # the app gets the same answer (no number probing), but whoever runs the server can see why
        log.warning("No SMS sent to %s: no active user has this mobile number. Add it to a user (web app → Users).", phones.masked(phone))
    if has_account:
        try:
            sms.send_otp(phone, code)
        except sms.SmsError as e:
            log.warning("SMS to %s failed: %s", phones.masked(phone), e)
            raise HTTPException(502, f"Couldn't send the SMS: {e}") from e
        if settings.sms_provider == "console" and settings.seed_demo:
            out["dev_code"] = code  # demo installs only (no SMS provider): lets testers sign in
    return out


class OtpVerifyIn(BaseModel):
    phone: str
    country_code: str = "+91"
    code: str


def _profiles(db: Session, phone: str) -> list[dict]:
    out = []
    tenants = {}
    for u in db.scalars(select(User).where(User.phone == phone, User.status == "active").order_by(User.id)):
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
    """Check the code. Returns a short-lived token and every profile (account) linked to the number."""
    phone = _phone(body.phone, body.country_code)
    ch = db.scalar(select(OtpChallenge).where(OtpChallenge.phone == phone, OtpChallenge.verified_at.is_(None)).order_by(OtpChallenge.id.desc()).limit(1))
    now = datetime.now(timezone.utc)
    if ch is None or _aware(ch.expires_at) < now:
        raise HTTPException(400, "This code has expired — request a new one")
    if ch.attempts >= settings.otp_max_attempts:
        raise HTTPException(429, "Too many wrong codes — request a new one")
    ch.attempts += 1
    if not hmac.compare_digest(ch.code_hash, _hash(phone, body.code.strip())):
        db.commit()
        left = settings.otp_max_attempts - ch.attempts
        raise HTTPException(400, f"Incorrect code — {left} attempt{'s' if left != 1 else ''} left" if left else "Too many wrong codes — request a new one")
    ch.verified_at = now
    db.commit()
    token = jwt.encode({"purpose": "otp", "phone": phone, "exp": now + timedelta(minutes=10)}, settings.jwt_secret, algorithm="HS256")
    return {"otp_token": token, "phone": phone, "profiles": _profiles(db, phone)}


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
    if not user or user.phone != st["phone"] or user.status != "active":
        raise HTTPException(403, "That profile isn't linked to this number")
    load_role(db, user)
    if not user.sections:
        raise HTTPException(403, f"Your role “{user.role}” has no access. Ask an admin to fix it.")
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
