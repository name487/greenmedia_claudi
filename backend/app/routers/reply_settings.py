"""Reply Settings (mobile app): per star category, how long AI review replies are and which language they're written
in — stored in the client's brand voice and used by every AI draft."""

import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..ai import REPLY_LENGTH
from ..db import get_db
from ..models import Client, Review, User
from ..security import audit, can, current_user, get_client, load_role

router = APIRouter(prefix="/api/clients", tags=["reply settings"])

CATEGORIES = ("positive", "negative")  # 3-5★, 1-2★
DEFAULT = {"positive": {"length": "short", "language": "", "language_name": ""}, "negative": {"length": "medium", "language": "", "language_name": ""}}
COUNT = {"ultra": 1, "short": 2, "medium": 3, "long": 5}
SAMPLES = {
    ("positive", "en"): ["Thank you so much for your kind words! 😊", "We're really glad you liked your experience at {c}.",
                         "We always try to give every customer our very best.", "Your feedback means a lot to our whole team.",
                         "Looking forward to seeing you again soon!"],
    ("negative", "en"): ["We're really sorry to hear about your experience.", "This isn't the standard we hold ourselves to at {c}.",
                         "We'd like to make it right — please call us so we can look into it personally.",
                         "Your feedback helps us improve, and we've shared it with the team.", "We hope to welcome you back and do better."],
    ("positive", "hi"): ["आपके सुंदर शब्दों के लिए बहुत-बहुत धन्यवाद! 😊", "हमें ख़ुशी है कि {c} में आपका अनुभव अच्छा रहा।",
                         "हम हर ग्राहक को सबसे अच्छी सेवा देने की कोशिश करते हैं।", "आपकी राय हमारी पूरी टीम के लिए बहुत मायने रखती है।",
                         "जल्द ही फिर मिलेंगे!"],
    ("negative", "hi"): ["आपके अनुभव के बारे में जानकर हमें सचमुच खेद है।", "{c} में हम ऐसी सेवा नहीं देना चाहते।",
                         "कृपया हमें कॉल करें, ताकि हम ख़ुद इस पर ध्यान दे सकें।", "आपकी राय से हमें सुधार करने में मदद मिलती है।",
                         "हम आपको फिर से बेहतर सेवा देना चाहेंगे।"],
}


def _settings(c: Client) -> dict:
    saved = (c.brand_voice or {}).get("reply_settings") or {}
    out = {}
    for cat in CATEGORIES:
        rs = {**DEFAULT[cat], **(saved.get(cat) or {})}
        if "length" not in (saved.get(cat) or {}) and (c.brand_voice or {}).get("reply_length") in REPLY_LENGTH:
            rs["length"] = c.brand_voice["reply_length"]  # older single setting
        out[cat] = rs
    return out


def sample(company: str, category: str, rs: dict) -> dict:
    lang = rs.get("language") or "en"
    lines = SAMPLES.get((category, lang)) or SAMPLES[(category, "en")]
    text = " ".join(lines[:COUNT.get(rs.get("length"), 2)]).format(c=company)
    note = ""
    if not rs.get("language"):
        note = "Replies are written in the same language as the review."
    elif (category, lang) not in SAMPLES:
        note = f"Shown in English — AI replies will be written in {rs.get('language_name') or lang}."
    return {"text": text, "note": note}


def _out(db: Session, c: Client) -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    replies = db.scalar(select(func.count()).select_from(Review).where(Review.client_id == c.id, Review.reply_status == "published",
                                                                      Review.published_at >= since)) or 0
    contact = c.contacts[0] if c.contacts else None
    st = _settings(c)
    return {"account": {"name": c.company_name, "email": (c.gmb.google_email if c.gmb else "") or (contact.email if contact else ""),
                        "replies_24h": replies},
            "lengths": list(REPLY_LENGTH), "settings": st, "samples": {cat: sample(c.company_name, cat, st[cat]) for cat in CATEGORIES}}


def _may_edit(user: User, c: Client) -> bool:
    return user.client_id == c.id or can(user, "client.edit")


@router.get("/{client_id}/reply-settings")
def get_reply_settings(client_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = get_client(db, load_role(db, user), client_id)
    return _out(db, c)


class CategoryIn(BaseModel):
    length: str
    language: str = ""  # ISO 639 code; "" = same language as the review
    language_name: str = Field("", max_length=60)

    @field_validator("length")
    @classmethod
    def _length(cls, v: str) -> str:
        if v not in REPLY_LENGTH:
            raise ValueError(f"length must be one of {', '.join(REPLY_LENGTH)}")
        return v

    @field_validator("language")
    @classmethod
    def _language(cls, v: str) -> str:
        v = v.strip().lower()
        if v and not re.fullmatch(r"[a-z]{2,3}", v):
            raise ValueError("language must be a language code such as en or hi")
        return v


class ReplySettingsIn(BaseModel):
    positive: CategoryIn
    negative: CategoryIn


@router.put("/{client_id}/reply-settings")
def put_reply_settings(client_id: int, body: ReplySettingsIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = get_client(db, load_role(db, user), client_id)
    if not _may_edit(user, c):
        raise HTTPException(403, "Your role cannot change reply settings")
    new = {cat: {**getattr(body, cat).model_dump(), "language_name": getattr(body, cat).language_name.strip() if getattr(body, cat).language else ""}
           for cat in CATEGORIES}
    before = _settings(c)
    c.brand_voice = {**(c.brand_voice or {}), "reply_settings": new}  # new dict so the JSON column is saved
    audit(db, user, "changed reply settings", client_id=c.id, entity_type="client", entity_id=c.id, details={"before": before, "after": new})
    db.commit()
    return _out(db, c)
