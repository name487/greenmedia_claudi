"""AI connection (OpenAI by default) and per-client brand voice for review replies.

The API key lives only in the server environment (backend/.env: OPENAI_API_KEY), never in the database or a page.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import ai
from ..config import settings
from ..db import get_db
from ..models import User
from ..security import audit, get_client, require, require_section
from ..sentiment import detect_language, detect_sentiment
from .clients import BrandVoiceIn, merge_brand_voice

router = APIRouter(prefix="/api/ai", tags=["ai"])
client_router = APIRouter(prefix="/api/clients/{client_id}/brand-voice", tags=["ai"])

_last_test: dict = {}  # per process; shows "last checked" on the settings page


def _key_hint() -> str:
    k = settings.ai_key
    return f"{k[:3]}…{k[-4:]}" if len(k) > 10 else ("set" if k else "")


def status_out() -> dict:
    return {
        "enabled": ai.ai_enabled(), "provider": settings.ai_provider, "model": settings.model, "key_hint": _key_hint(),
        "base_url": settings.openai_base_url if settings.ai_provider == "openai" else "https://api.anthropic.com",
        "env_var": "OPENAI_API_KEY" if settings.ai_provider == "openai" else "ANTHROPIC_API_KEY",
        "last_test": _last_test or None,
    }


@router.get("/status")
def status(user: User = Depends(require_section("settings"))):
    return status_out()


@router.post("/test")
def test(user: User = Depends(require("settings.edit")), db: Session = Depends(get_db)):
    """Send one tiny request to the provider and report what happened (latency, model, or the error and how to fix it)."""
    if not ai.ai_enabled():
        result = {"ok": False, "code": "not_configured", "error": f"No API key. Set {status_out()['env_var']} in backend/.env and restart the API.", "hint": ""}
    else:
        try:
            res = ai.complete("You are a connection check. Reply with the single word OK.", "Connection check", 16)
            result = {"ok": True, "model": res["model"], "ms": res["ms"], "usage": res["usage"], "reply": res["text"][:40]}
        except ai.AiError as e:
            result = {"ok": False, "code": e.code, "error": str(e), "hint": e.hint}
    _last_test.clear()
    _last_test.update({**result, "provider": settings.ai_provider, "at": datetime.now(timezone.utc).isoformat()})
    audit(db, user, f"AI connection test: {'ok' if result['ok'] else result['code']} ({settings.ai_provider}/{settings.model})", entity_type="settings",
          details={k: v for k, v in result.items() if k != "reply"})
    db.commit()
    return {**status_out(), "result": result}


# ---------- per-client brand voice ----------

def _prompt(c, voice: dict) -> str:
    return ai.review_system_prompt(company=c.company_name, industry=c.industry, city=c.city, phone=c.contacts[0].phone if c.contacts else "", brand_voice=voice)


@client_router.get("")
def brand_voice(client_id: int, user: User = Depends(require_section("clients")), db: Session = Depends(get_db)):
    """The client's brand voice and the exact system prompt the AI receives for review replies."""
    c = get_client(db, user, client_id)
    return {"brand_voice": c.brand_voice, "system_prompt": _prompt(c, c.brand_voice), "ai": status_out()}


class TryIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    text: str = Field(default="", max_length=4000)
    author: str = Field(default="Priya Sharma", max_length=120)
    instruction: str = Field(default="", max_length=500)
    brand_voice: BrandVoiceIn | None = None  # unsaved edits to preview; omitted = the saved voice


@client_router.post("/try")
def try_voice(client_id: int, body: TryIn, user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    """Draft a reply to an example review with this client's voice, without saving anything except an audit entry."""
    c = get_client(db, user, client_id)
    voice = merge_brand_voice(c.brand_voice, body.brand_voice) if body.brand_voice else c.brand_voice
    lang = detect_language(body.text)
    reply, meta = ai.review_reply(company=c.company_name, industry=c.industry, city=c.city, phone=c.contacts[0].phone if c.contacts else "",
                                  brand_voice=voice, author=body.author, rating=body.rating, text=body.text, language=lang,
                                  sentiment=detect_sentiment(body.text, body.rating), instruction=body.instruction)
    audit(db, user, f"tried brand voice ({meta['source']})", client_id=c.id, entity_type="client", entity_id=c.id,
          details={k: meta[k] for k in ("source", "provider", "model", "usage", "ms", "error") if meta.get(k) not in (None, "")})
    db.commit()
    return {"reply": reply, "ai": meta, "system_prompt": _prompt(c, voice)}
