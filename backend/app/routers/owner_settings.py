"""The app's Settings for business owners: the summary card, Preference (business and brand details), My QRs and QR
standees (trackable "review us on Google" codes), Refund Request, and the legal pages."""

import io
import math
import secrets
import string
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Annotated, Literal
from urllib.parse import quote_plus

import jwt
import segno
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from PIL import Image, ImageDraw
from pydantic import BaseModel, ConfigDict, Field, create_model
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import legal, media, plans, preference
from ..ai_posts import _iso
from ..config import settings
from ..db import get_db
from ..media import font
from ..models import Client, PlanPayment, RefundRequest, ReviewQr, Task, User
from ..security import audit, can, get_client, require, require_section

router = APIRouter(prefix="/api/clients", tags=["settings"])
public = APIRouter(tags=["settings"])
staff = APIRouter(prefix="/api/qr-standees", tags=["settings"])
legal_router = APIRouter(prefix="/api/legal", tags=["settings"])

QR_LIMIT = 50
ALPHABET = string.ascii_lowercase + string.digits


def _owner(user: User, c: Client) -> None:
    if user.client_id != c.id and not can(user, "client.edit"):
        raise HTTPException(403, "Only the business owner can change this")


def qr_url(code: str) -> str:
    return f"{settings.public_base_url}/q/{code}"


def review_link(c: Client) -> str:
    if c.gmb and c.gmb.review_uri:
        return c.gmb.review_uri
    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(f'{c.company_name} {c.city}')}"


# ---------- Settings summary ----------

@router.get("/{client_id}/settings")
def summary(client_id: int, user: User = Depends(require_section("dashboard")), db: Session = Depends(get_db)):
    c = get_client(db, user, client_id)
    contact = c.contacts[0] if c.contacts else None
    return {"client": {"id": c.id, "company_name": c.company_name, "city": c.city, "phone": (contact.phone if contact else "") or user.phone,
                       "code": f"#{c.id:04d}"},
            "plan": plans.status(c), "google_connected": bool(c.gmb and c.gmb.status == "connected"),
            "qrs": db.scalar(select(func.count()).select_from(ReviewQr).where(ReviewQr.client_id == c.id)) or 0,
            "support_email": settings.legal_email, "company": settings.legal_company}


# ---------- Preference ----------

def _patch_model():
    """Every Preference field is optional (each one is edited and saved on its own in the app); "" clears a choice."""
    fields: dict = {k: (str | None, Field(None, max_length=n)) for k, (_, n) in preference.TEXT.items()}
    for k, opts in preference.CHOICES.items():
        fields[k] = (Literal[tuple(opts + [""])] | None, None)
    fields |= {"brand_color": (str | None, Field(None, pattern=r"^(#[0-9A-Fa-f]{6})?$")), "founder_in_promos": (bool | None, None),
               "hashtags": (list[Annotated[str, Field(max_length=60)]] | None, Field(None, max_length=30)),
               "publish": (dict[Literal[tuple(preference.PUBLISH)], bool] | None, None),
               "religious": (dict[Literal[tuple(preference.RELIGIONS)], bool] | None, None),
               "preferred_phrases": (list[str] | None, Field(None, max_length=10)), "prohibited_claims": (list[str] | None, Field(None, max_length=10))}
    return create_model("PreferencePatch", __config__=ConfigDict(extra="forbid"), **fields)


PreferencePatch = _patch_model()


@router.get("/{client_id}/preference")
def get_preference(client_id: int, user: User = Depends(require_section("dashboard")), db: Session = Depends(get_db)):
    return preference.view(db, get_client(db, user, client_id))


@router.patch("/{client_id}/preference")
def save_preference(client_id: int, body: PreferencePatch, user: User = Depends(require_section("dashboard")), db: Session = Depends(get_db)):
    c = get_client(db, user, client_id)
    _owner(user, c)
    changes = body.model_dump(exclude_none=True)
    if len(preference.hashtags(changes.get("hashtags", []), limit=None)) > preference.MAX_HASHTAGS:
        raise HTTPException(422, f"Up to {preference.MAX_HASHTAGS} hashtags")
    preference.update(c, changes)
    audit(db, user, "updated preference: " + ", ".join(sorted(changes)), client_id=c.id, entity_type="client", entity_id=c.id)
    db.commit()
    db.refresh(c)
    return preference.view(db, c)


@router.post("/{client_id}/preference/photos/{slot}")
async def add_preference_photo(client_id: int, slot: str, image: UploadFile = File(...), user: User = Depends(require_section("dashboard")),
                               db: Session = Depends(get_db)):
    c = get_client(db, user, client_id)
    _owner(user, c)
    if slot not in preference.PHOTO_SLOTS:
        raise HTTPException(404, "Unknown photo")
    try:
        rel = media.save_photo(c.id, await image.read(media.MAX_UPLOAD + 1))
    except media.MediaError as e:
        raise HTTPException(422, str(e))
    preference.set_photo(c, slot, rel)
    audit(db, user, f"preference photo added: {preference.PHOTO_SLOTS[slot]}", client_id=c.id, entity_type="client", entity_id=c.id)
    db.commit()
    db.refresh(c)
    return preference.view(db, c)


@router.delete("/{client_id}/preference/photos/{slot}")
def remove_preference_photo(client_id: int, slot: str, user: User = Depends(require_section("dashboard")), db: Session = Depends(get_db)):
    c = get_client(db, user, client_id)
    _owner(user, c)
    if slot not in preference.PHOTO_SLOTS:
        raise HTTPException(404, "Unknown photo")
    preference.set_photo(c, slot, None)
    db.commit()
    db.refresh(c)
    return preference.view(db, c)


# ---------- My QRs and QR standees ----------

def _new_code(db: Session) -> str:
    while True:
        code = "".join(secrets.choice(ALPHABET) for _ in range(7))
        if not db.scalar(select(ReviewQr.id).where(ReviewQr.code == code)):
            return code


def qr_out(q: ReviewQr) -> dict:
    return {"id": q.id, "code": q.code, "kind": q.kind, "label": q.label, "url": qr_url(q.code), "scans": q.scans,
            "created_at": _iso(q.created_at), "last_scan_at": _iso(q.last_scan_at)}


@router.get("/{client_id}/qrs")
def list_qrs(client_id: int, user: User = Depends(require_section("dashboard")), db: Session = Depends(get_db)):
    c = get_client(db, user, client_id)
    rows = list(db.scalars(select(ReviewQr).where(ReviewQr.client_id == c.id).order_by(ReviewQr.id.desc())))
    return {"items": [qr_out(q) for q in rows], "limit": QR_LIMIT, "used": sum(1 for q in rows if q.kind == "app"), "review_link": review_link(c)}


class QrIn(BaseModel):
    label: str = Field("", max_length=80)


@router.post("/{client_id}/qrs", status_code=201)
def generate_qr(client_id: int, body: QrIn | None = None, user: User = Depends(require_section("dashboard")), db: Session = Depends(get_db)):
    c = get_client(db, user, client_id)
    _owner(user, c)
    used = db.scalar(select(func.count()).select_from(ReviewQr).where(ReviewQr.client_id == c.id, ReviewQr.kind == "app")) or 0
    if used >= QR_LIMIT:
        raise HTTPException(429, f"You've made all {QR_LIMIT} QR codes")
    q = ReviewQr(tenant_id=c.tenant_id, client_id=c.id, code=_new_code(db), kind="app", label=(body.label.strip() if body else ""))
    db.add(q)
    db.flush()
    audit(db, user, f"generated review QR {q.code}", client_id=c.id, entity_type="review_qr", entity_id=q.id)
    db.commit()
    return qr_out(q)


class ClaimIn(BaseModel):
    code: str = Field(min_length=4, max_length=300)  # the code printed under the QR, or the whole scanned link


@router.post("/{client_id}/qrs/claim")
def claim_standee(client_id: int, body: ClaimIn, user: User = Depends(require_section("dashboard")), db: Session = Depends(get_db)):
    """Configure QR Standee: link a pre-printed standee to this business by scanning it (or typing its code)."""
    c = get_client(db, user, client_id)
    _owner(user, c)
    code = body.code.strip().rstrip("/").rsplit("/", 1)[-1].split("?")[0].lower()
    q = db.scalar(select(ReviewQr).where(ReviewQr.code == code, ReviewQr.tenant_id == c.tenant_id))
    if not q or q.kind != "standee":
        raise HTTPException(404, "That isn't one of our QR standees — check the code printed under the QR")
    if q.client_id and q.client_id != c.id:
        raise HTTPException(409, "This standee is already set up for another business")
    if q.client_id != c.id:
        q.client_id, q.claimed_at = c.id, datetime.now(timezone.utc)
        audit(db, user, f"configured QR standee {q.code}", client_id=c.id, entity_type="review_qr", entity_id=q.id)
        db.commit()
    return qr_out(q)


class StandeesIn(BaseModel):
    count: int = Field(ge=1, le=500)


@staff.post("", status_code=201)
def make_standees(body: StandeesIn, user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    """Agency: codes to print on standees. Each one works once a business claims it in the app."""
    rows = [ReviewQr(tenant_id=user.tenant_id, client_id=None, code=_new_code(db), kind="standee") for _ in range(body.count)]
    for r in rows:
        db.add(r)
        db.flush()
    audit(db, user, f"created {body.count} QR standee codes", entity_type="review_qr")
    db.commit()
    return {"items": [{"code": r.code, "url": qr_url(r.code), "png": f"{settings.public_base_url}/q/{r.code}.png"} for r in rows]}


def _qr_image(data: str, scale: int) -> Image.Image:
    buf = io.BytesIO()
    segno.make(data, error="m").save(buf, kind="png", scale=scale, border=2)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def standee_png(c: Client, q: ReviewQr) -> bytes:
    """A printable A5-ish "Review us on Google" standee with the business's name and the QR."""
    w, h = 1200, 1700
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w, 260], fill=(14, 26, 58))
    d.text((w // 2, 110), "Loved your visit?", font=font(64), fill="white", anchor="mm")
    d.text((w // 2, 190), "Review us on Google", font=font(54), fill=(255, 196, 0), anchor="mm", stroke_width=1, stroke_fill=(255, 196, 0))
    d.text((w // 2, 350), c.company_name, font=font(56), fill=(14, 26, 58), anchor="mm", stroke_width=1, stroke_fill=(14, 26, 58))
    if c.city:
        d.text((w // 2, 420), c.city, font=font(36), fill=(95, 107, 117), anchor="mm")
    qr = _qr_image(qr_url(q.code), 24).resize((760, 760), Image.NEAREST)
    img.paste(qr, ((w - 760) // 2, 480))
    for i in range(5):  # five stars, drawn (the built-in font has no ★)
        cx, cy, r = w // 2 - 240 + i * 120, 1330, 42
        pts = []
        for k in range(10):
            ang = math.pi / 2 + k * math.pi / 5
            rad = r if k % 2 == 0 else r * 0.45
            pts.append((cx + rad * math.cos(ang), cy - rad * math.sin(ang)))
        d.polygon(pts, fill=(251, 188, 5))
    d.text((w // 2, 1450), "Scan with your phone camera", font=font(40), fill=(20, 30, 40), anchor="mm")
    d.text((w // 2, 1600), f"Code {q.code}", font=font(26), fill=(150, 160, 170), anchor="mm")
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


@router.post("/{client_id}/qrs/{qr_id}/link")
def qr_download_link(client_id: int, qr_id: int, user: User = Depends(require_section("dashboard")), db: Session = Depends(get_db)):
    """A short-lived link the phone can open to save the printable standee."""
    c = get_client(db, user, client_id)
    q = db.scalar(select(ReviewQr).where(ReviewQr.id == qr_id, ReviewQr.client_id == c.id))
    if not q:
        raise HTTPException(404, "QR not found")
    token = jwt.encode({"purpose": "qr_standee", "qid": q.id, "exp": datetime.now(timezone.utc) + timedelta(minutes=15)}, settings.jwt_secret,
                       algorithm="HS256")
    return {"url": f"{settings.public_base_url}/api/clients/{c.id}/qrs/{q.id}/standee.png?t={token}", "filename": f"review_qr_{q.code}.png"}


@router.get("/{client_id}/qrs/{qr_id}/standee.png")
def qr_standee_file(client_id: int, qr_id: int, t: str, db: Session = Depends(get_db)):
    try:
        claims = jwt.decode(t, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "This download link has expired — download again from the app")
    q = db.get(ReviewQr, qr_id)
    if claims.get("purpose") != "qr_standee" or claims.get("qid") != qr_id or not q or q.client_id != client_id:
        raise HTTPException(401, "This download link is not valid")
    return Response(standee_png(db.get(Client, client_id), q), media_type="image/png",
                    headers={"Content-Disposition": f'attachment; filename="review_qr_{q.code}.png"'})


@public.get("/q/{code}.png")
def qr_png(code: str, db: Session = Depends(get_db)):
    q = db.scalar(select(ReviewQr).where(ReviewQr.code == code.lower()))
    if not q:
        raise HTTPException(404, "Unknown code")
    buf = io.BytesIO()
    _qr_image(qr_url(q.code), 16).save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png")


@public.get("/q/{code}")
def scan(code: str, db: Session = Depends(get_db)):
    """A customer scanned a review QR: count it and open the business's Google review form."""
    q = db.scalar(select(ReviewQr).where(ReviewQr.code == code.lower()))
    if not q:
        raise HTTPException(404, "This QR code isn't valid")
    if not q.client_id:
        return HTMLResponse("<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'>"
                            "<body style='font-family:system-ui;padding:24px'><h2>This standee isn't set up yet</h2>"
                            f"<p>Business owner: open the {escape(settings.legal_company)} app → Settings → Configure QR Standee, and scan it.</p>")
    q.scans += 1
    q.last_scan_at = datetime.now(timezone.utc)
    db.commit()
    return RedirectResponse(review_link(db.get(Client, q.client_id)), status_code=302)


# ---------- Refund Request ----------

def _refundable(p: PlanPayment, open_ids: set[int]) -> tuple[bool, str]:
    if not plans.PLAN.get(p.plan_key) or p.plan_key == "social_monthly":
        return False, "Monthly plans aren't refundable"
    if p.id in open_ids:
        return False, "Refund already requested"
    paid = p.paid_at.replace(tzinfo=timezone.utc) if p.paid_at and p.paid_at.tzinfo is None else p.paid_at
    if not paid or datetime.now(timezone.utc) - paid > timedelta(days=settings.refund_days):
        return False, f"More than {settings.refund_days} days since payment"
    return True, ""


@router.get("/{client_id}/refunds")
def refunds(client_id: int, user: User = Depends(require_section("dashboard")), db: Session = Depends(get_db)):
    c = get_client(db, user, client_id)
    reqs = list(db.scalars(select(RefundRequest).where(RefundRequest.client_id == c.id).order_by(RefundRequest.id.desc())))
    open_ids = {r.payment_id for r in reqs if r.status != "rejected"}
    pays = []
    for p in db.scalars(select(PlanPayment).where(PlanPayment.client_id == c.id, PlanPayment.status == "paid").order_by(PlanPayment.id.desc())):
        ok, why = _refundable(p, open_ids)
        pays.append({**plans.payment_out(p), "refundable": ok, "why_not": why})
    return {"policy": legal.refund_policy(), "payments": pays,
            "requests": [{"id": r.id, "payment_id": r.payment_id, "status": r.status, "reason": r.reason, "created_at": _iso(r.created_at)} for r in reqs]}


class RefundIn(BaseModel):
    payment_id: int
    reason: str = Field("", max_length=1000)


@router.post("/{client_id}/refunds", status_code=201)
def request_refund(client_id: int, body: RefundIn, user: User = Depends(require_section("dashboard")), db: Session = Depends(get_db)):
    c = get_client(db, user, client_id)
    _owner(user, c)
    p = db.scalar(select(PlanPayment).where(PlanPayment.id == body.payment_id, PlanPayment.client_id == c.id, PlanPayment.status == "paid"))
    if not p:
        raise HTTPException(404, "Payment not found")
    open_ids = set(db.scalars(select(RefundRequest.payment_id).where(RefundRequest.client_id == c.id, RefundRequest.status != "rejected")))
    ok, why = _refundable(p, open_ids)
    if not ok:
        raise HTTPException(409, why)
    r = RefundRequest(tenant_id=c.tenant_id, client_id=c.id, payment_id=p.id, reason=body.reason.strip(), created_by=user.id)
    db.add(r)
    db.add(Task(tenant_id=c.tenant_id, client_id=c.id, assigned_to=c.account_manager_id, priority="high",
                title=f"Refund request: {c.company_name} — {plans.PLAN[p.plan_key]['name']} ₹{p.amount // 100:,} (payment #{p.id})",
                due_date=(datetime.now(timezone.utc) + timedelta(days=2)).date()))
    db.flush()
    audit(db, user, f"requested a refund for payment #{p.id}", client_id=c.id, entity_type="refund_request", entity_id=r.id)
    db.commit()
    return {"id": r.id, "payment_id": p.id, "status": r.status, "created_at": _iso(r.created_at)}


# ---------- legal ----------

@legal_router.get("/{doc}")
def legal_doc(doc: str):
    if doc == "refund":
        return legal.refund_policy()
    if doc not in legal.DOCS:
        raise HTTPException(404, "Unknown document")
    return legal.DOCS[doc]()


@public.get("/legal/{doc}", response_class=HTMLResponse)
def legal_page(doc: str):
    """The same pages for a browser (store listings need a public privacy policy URL)."""
    if doc not in legal.DOCS:
        raise HTTPException(404, "Unknown document")
    d = legal.DOCS[doc]()
    body = "".join(f"<h2>{escape(s['heading'])}</h2>" + "".join(f"<p>{escape(p)}</p>" for p in s["paragraphs"]) for s in d["sections"])
    return HTMLResponse(f"<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
                        f"<title>{escape(d['title'])}</title><body style='font-family:system-ui;max-width:760px;margin:auto;padding:20px;line-height:1.55'>"
                        f"<h1>{escape(d['title'])}</h1><p><i>Last updated: {escape(d['updated'])}</i></p><p>{escape(d['intro'])}</p>{body}</body></html>")
